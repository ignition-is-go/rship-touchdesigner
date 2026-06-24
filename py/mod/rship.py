"""
rship — first-class Python API for defining rship targets/actions/emitters/properties
from TouchDesigner user code (e.g. a custom extension exposing its own control surface).

Mental model mirrors the rship SDK: Instance -> Target -> { Emitter | Action | Property }.
  - Emitter   = a readable value you pulse().
  - Action    = an invokable with a typed input.
  - Property  = an emitter (read) paired with a canonical writer action (write); the
                emitter is the identity, the action writes it (Action.writesTo).

Schemas are derived from the handler's signature by reflection (param/return type hints),
with an explicit schema=/type= override. A target created here is registered in a module
registry; RshipExt collects it alongside the tag-based COMP targets and drives the same
send / seed / reconcile lifecycle.

Usage (imperative):
    import rship
    class MyExt:
        def __init__(self, ownerComp):
            self._level = 0.0
            t = rship.target(ownerComp, "My Effect")
            t.action("Trigger", self.trigger)
            t.property("Level", get=self.get_level, set=self.set_level)
            self.beat = t.emitter("Beat")
        def trigger(self): ...
        def get_level(self) -> float: return self._level
        def set_level(self, v: float) -> rship.WriteOutcome:
            self._level = v
            return rship.Applied(v)

Usage (declarative):
    class MyExt(rship.TargetExt):
        rship_name = "My Effect"
        @rship.action
        def trigger(self): ...
        @rship.property
        def level(self) -> float: return self._level
        @level.setter
        def level(self, v: float) -> rship.WriteOutcome:
            self._level = v; return rship.Applied(v)
"""
import dataclasses
import inspect
import re
import typing

import td

from exec import CLIENT, Action, Emitter, Instance, Stream, Target, makeWriterRef
from target import TouchTarget
from util import (makeEmitterChangeKey, RS_TARGET_ID_STORAGE_KEY, RS_TARGET_INFO_PAGE,
                  RS_BUNDLE_COMPLETE_PAR)
from par_shape import buildShape, SequenceParShape
import par_schema


# region WriteOutcome

class WriteOutcome:
    """Result of a property setter. Every setter must return one of:
    Applied(value) | Deferred | Rejected(reason)."""


class Applied(WriteOutcome):
    """The write was applied. The framework pulses `value` (or the getter's current
    value if omitted) back as the new readback so the server reconciles."""
    def __init__(self, value=None):
        self.value = value


class Rejected(WriteOutcome):
    """The write was refused; nothing is pulsed."""
    def __init__(self, reason=""):
        self.reason = reason


class _Deferred(WriteOutcome):
    """The write was accepted but the new value isn't known yet; pulse later via
    the property's .pulse()."""


Deferred = _Deferred()

# endregion WriteOutcome


# region type aliases (TD-friendly payload shapes)

@dataclasses.dataclass
class Color:
    r: float = 0.0
    g: float = 0.0
    b: float = 0.0
    a: float = 1.0


@dataclasses.dataclass
class XYZ:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


@dataclasses.dataclass
class XY:
    x: float = 0.0
    y: float = 0.0

# endregion type aliases


# region helpers

def _slug(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", str(name)).strip("-").lower()
    return s or "item"


def _humanize(name: str) -> str:
    s = re.sub(r"[_\-]+", " ", str(name))           # snake/kebab -> spaces
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", s)    # split camelCase
    words = s.split()
    # Capitalize each word's first letter, preserving the rest (keeps acronyms like RGB).
    return " ".join(w[:1].upper() + w[1:] for w in words) if words else str(name)


def _to_jsonable(value):
    """Coerce a handler/getter return value into a JSON-serializable shape."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return dataclasses.asdict(value)
    return value


_PRIMITIVE_SCHEMA = {
    float: {"type": "number"},
    int: {"type": "integer"},
    str: {"type": "string"},
    bool: {"type": "boolean"},
}

_TOKEN_SCHEMA = {
    "number": {"type": "number"},
    "float": {"type": "number"},
    "int": {"type": "integer"},
    "integer": {"type": "integer"},
    "string": {"type": "string"},
    "str": {"type": "string"},
    "bool": {"type": "boolean"},
    "boolean": {"type": "boolean"},
    "toggle": {"type": "boolean"},
    "rgb": {"type": "object", "properties": {c: {"type": "number"} for c in "rgb"}},
    "rgba": {"type": "object", "properties": {c: {"type": "number"} for c in "rgba"}},
    "xy": {"type": "object", "properties": {c: {"type": "number"} for c in "xy"}},
    "xyz": {"type": "object", "properties": {c: {"type": "number"} for c in "xyz"}},
}


def _token_to_schema(token):
    if token is None:
        return None
    if isinstance(token, dict):
        return token
    return _TOKEN_SCHEMA.get(str(token).lower(), {})


def _safe_hints(fn):
    try:
        return typing.get_type_hints(fn)
    except Exception:
        return {}


def _type_to_schema(tp):
    if tp is None or tp is inspect.Parameter.empty:
        return {}
    origin = typing.get_origin(tp)
    args = typing.get_args(tp)
    if origin is typing.Union:  # Optional[X] / Union
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1:
            return _type_to_schema(non_none[0])
        return {}
    if tp in _PRIMITIVE_SCHEMA:
        return dict(_PRIMITIVE_SCHEMA[tp])
    if origin in (list, tuple):
        item = _type_to_schema(args[0]) if args else {}
        return {"type": "array", "items": item or {}}
    if origin is dict:
        return {"type": "object"}
    if dataclasses.is_dataclass(tp):
        hints = _safe_hints(tp)
        props = {f.name: _type_to_schema(hints.get(f.name)) for f in dataclasses.fields(tp)}
        return {"type": "object", "properties": props}
    return {}  # unknown -> permissive


def _reflect(fn, schema_override=None, type_override=None):
    """Return (schema, adapter). adapter(data) calls fn with arguments shaped from
    the incoming payload and returns fn's result.

    Call convention by arity of fn's parameters (bound methods already exclude self):
      0 params            -> null schema; fn()
      1 unannotated param -> raw dict passthrough; fn(data)
      1 dataclass param   -> object schema from fields; fn(Cls(**data))
      1 scalar param      -> bare schema of that type; fn(data)
      N params            -> object schema {name: type}; fn(**data)
    schema=/type= override the derived schema (call convention is unchanged).
    """
    params = [p for p in inspect.signature(fn).parameters.values()
              if p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)]
    hints = _safe_hints(fn)
    n = len(params)

    if n == 0:
        derived, adapter = {}, (lambda data: fn())
    elif n == 1:
        ann = hints.get(params[0].name, None)
        if ann is None:
            derived, adapter = {"type": "object"}, (lambda data: fn(data))
        elif dataclasses.is_dataclass(ann):
            derived = _type_to_schema(ann)
            adapter = (lambda data, _a=ann: fn(_a(**(data or {}))))
        else:
            derived, adapter = _type_to_schema(ann), (lambda data: fn(data))
    else:
        props = {p.name: _type_to_schema(hints.get(p.name)) for p in params}
        derived = {"type": "object", "properties": props}
        adapter = (lambda data: fn(**(data or {})))

    schema = schema_override if schema_override is not None else (
        _token_to_schema(type_override) if type_override is not None else derived)
    return schema, adapter

# endregion helpers


# region registry

# The registry + dirty flag are anchored on the process-global `td` module (a true
# singleton in sys.modules). TD duplicates DAT modules — including this one and
# exec/CLIENT — across compile/reinit epochs, so neither module globals nor CLIENT
# are reliably shared between the user's extension and RshipExt. `td` always is.
# (Handlers are closures, so the registry can't live in op storage either — it would
# fail to pickle on project save.)

def _state() -> dict:
    s = getattr(td, '_rship_state', None)
    if s is None:
        s = {'registry': {}, 'dirty': False}
        td._rship_state = s
    return s


def _mark_dirty():
    _state()['dirty'] = True


def consume_dirty() -> bool:
    """RshipExt calls this each tick; returns True (and clears) if targets changed."""
    s = _state()
    was = s['dirty']
    s['dirty'] = False
    return was


def get_targets() -> typing.List["TargetProxy"]:
    return list(_state()['registry'].values())


def target(ownerComp, name, *, short_id=None, category="python") -> "TargetProxy":
    """Create (or replace) a Python-defined rship target. Returns a TargetProxy you
    add actions/emitters/properties to. Re-creating with the same key replaces the
    prior registration (clean extension re-init)."""
    short = short_id or _slug(name)
    key = f"{ownerComp.path}:{short}"
    proxy = TargetProxy(ownerComp, name, short, category, key)
    _state()['registry'][key] = proxy
    _mark_dirty()
    return proxy


def prune_dead() -> typing.List["TargetProxy"]:
    """Remove targets whose owner COMP was deleted from the registry, returning them so the
    caller can mark them OFFLINE on the server. Deleting a base does NOT auto-clean its
    td-anchored registration, so without this a removed target re-publishes as online every
    connect."""
    reg = _state()['registry']
    dead = []
    for key, proxy in list(reg.items()):
        try:
            alive = proxy.ownerComp is not None and proxy.ownerComp.valid
        except Exception:
            alive = False
        if not alive:
            dead.append(proxy)
            del reg[key]
    if dead:
        _mark_dirty()
    return dead


def _seq_change_keys(ownerComp, sequence) -> list:
    """A sequence emitter's parexec keys: the header + every block's par groups (dedup)."""
    cks = [makeEmitterChangeKey(ownerComp, sequence.name)]
    for block in sequence.blocks:
        for bpg in block:
            cks.append(makeEmitterChangeKey(ownerComp, bpg.name))
    return list(dict.fromkeys(cks))


def _bulk_entries(page, ownerComp, section_prefix=None) -> list:
    """Reproduce PageTarget.buildBulkSchemaEntries: ordered {path,label,section,schema} over a
    page's pars (a Header par sets the running section; a sequence -> its array schema; a par
    group -> {type:object, properties:...}). Dedup by path."""
    entries, seen, section = [], set(), None
    for par in page.pars:
        if getattr(par, "style", None) == "Header":
            section = (par.label or par.name)
            continue
        pg = getattr(par, "parGroup", None)
        if pg is None:
            continue
        seq = getattr(pg, "sequence", None)
        if seq is not None:
            path, label = seq.name, (getattr(seq, "label", None) or seq.name)
            if path in seen:
                continue
            seqPgs = [p for p in page.parGroups if getattr(p, "sequence", None) and p.sequence.name == seq.name]
            try:
                node = SequenceParShape(ownerComp, pg, sequenceParGroups=seqPgs).buildSchemaProperties()
            except Exception:
                node = None
        else:
            path, label = pg.name, (par.label or pg.name)
            if path in seen:
                continue
            try:
                node = {"type": "object", "properties": buildShape(ownerComp, pg).buildSchemaProperties()}
            except Exception:
                node = None
        if node is None:
            continue
        seen.add(path)
        sec = section
        if section_prefix:
            sec = f"{section_prefix} / {section}" if section else section_prefix
        entries.append({"path": path, "label": label, "section": sec, "schema": node})
    return entries


def _bulk_reg(entries, pages, ownerComp, complete_par=None) -> "_Reg":
    """The bulk_set action _Reg: schema {path: node} + ordered schemaLayout. The handler writes
    each path across `pages` then pulses complete_par (behavior only — stripped from the wire)."""
    properties = {e["path"]: e["schema"] for e in entries}
    layout = []
    for e in entries:
        le = {"path": e["path"]}
        if e["label"] is not None:
            le["label"] = e["label"]
        if e["section"] is not None:
            le["section"] = e["section"]
        layout.append(le)

    def handler(action, data, _pages=pages, _own=ownerComp, _cp=complete_par):
        if not isinstance(data, dict):
            return None
        for page in _pages:
            done = set()
            for pg in page.parGroups:
                if pg.style == "Header":
                    continue
                seq = getattr(pg, "sequence", None)
                name = seq.name if seq is not None else pg.name
                if name in done or data.get(name) is None:
                    continue
                done.add(name)
                try:
                    if seq is not None:
                        seqPgs = [p for p in page.parGroups if getattr(p, "sequence", None) and p.sequence.name == seq.name]
                        SequenceParShape(_own, pg, sequenceParGroups=seqPgs).setData(data[name])
                    else:
                        buildShape(_own, pg).setData(data[name])
                except Exception:
                    pass
        if _cp is not None and _own.par[_cp] is not None and _own.par[_cp].isPulse:
            _own.par[_cp].pulse()
        return None

    return _Reg("Bulk Set", "bulk_set", {"type": "object", "properties": properties},
                handler=handler, schema_layout=layout)


def reflect_comp(ownerComp, instance) -> "TargetProxy":
    """Reflect a tagged COMP into a TargetProxy tree IDENTICAL to the legacy tag-based
    OPTarget/PageTarget/ParGroupTarget/SequenceTarget output, consolidating those 4 classes:
    root id = the COMP's stored UUID (survives TD restarts), children = UUID:Page / UUID:Par /
    UUID:Seq, schemas via par_shape (byte-unchanged), set/updated/bulk_set naming. Flag-gated.
    TODO: stream (getStreamInfo / rship_stream)."""
    uid = ownerComp.storage.get(RS_TARGET_ID_STORAGE_KEY)
    if not uid:
        import uuid as _uuid
        uid = str(_uuid.uuid4())
        ownerComp.storage[RS_TARGET_ID_STORAGE_KEY] = uid
    root = TargetProxy(ownerComp, ownerComp.name, ownerComp.name, ownerComp.OPType,
                       f"{ownerComp.path}:reflect", id_override=uid)
    root.instance = instance

    pages = [p for p in ownerComp.customPages if p.name != RS_TARGET_INFO_PAGE]   # skip util page
    if "Notch" in ownerComp.pages:
        pages.append(ownerComp.pages["Notch"])
    op_entries = []
    for page in pages:
        pageNode = TargetProxy(ownerComp, page.name, page.name, "Page",
                               f"{uid}:{page.name}", parent=root, id_override=f"{uid}:{page.name}")
        root._children.append(pageNode)
        seen_seq = set()
        for pg in page.parGroups:
            if pg.style == "Header":
                continue
            seq = getattr(pg, "sequence", None)
            if seq is not None:                                  # sequence -> array property
                if seq.name in seen_seq:
                    continue
                seen_seq.add(seq.name)
                seqPgs = [p for p in page.parGroups if getattr(p, "sequence", None) and p.sequence.name == seq.name]
                try:
                    sshape = SequenceParShape(ownerComp, pg, sequenceParGroups=seqPgs)
                    sschema = sshape.buildSchemaProperties()
                except Exception as e:
                    op.RS_LOG.Warning(f"[reflect_comp]: skipping sequence {seq.name}: {e}")
                    continue
                sqNode = TargetProxy(ownerComp, seq.name, seq.name, "Sequence",
                                     f"{uid}:{seq.name}", parent=pageNode, id_override=f"{uid}:{seq.name}")
                eid = f"{uid}:{seq.name}:updated"
                sqNode._emitters["updated"] = _Reg(
                    seq.name, "updated", sschema, change_key=makeEmitterChangeKey(ownerComp, seq.name),
                    change_keys=_seq_change_keys(ownerComp, seq), provider=sshape.buildData)

                def _seqset(a, d, _s=sshape, _eid=eid):
                    _s.setData(d)
                    CLIENT.pulseEmitter(_eid, _to_jsonable(_s.buildData()))   # sequence parexec is unreliable
                    return None
                sqNode._actions.append(_Reg(f"Set {seq.name}", "set", sschema,
                                            handler=_seqset, writesTo=makeWriterRef(eid)))
                pageNode._children.append(sqNode)
                continue
            try:                                                 # par group -> property
                shape = buildShape(ownerComp, pg)
            except Exception as e:
                op.RS_LOG.Warning(f"[reflect_comp]: skipping {pg.name} ({pg.style}): {e}")
                continue
            schema = {"type": "object", "properties": shape.buildSchemaProperties()}
            pgNode = TargetProxy(ownerComp, pg.name, pg.name, pg.style,
                                 f"{uid}:{pg.name}", parent=pageNode, id_override=f"{uid}:{pg.name}")
            pgNode._emitters["updated"] = _Reg(
                pg.name, "updated", schema,
                change_key=makeEmitterChangeKey(ownerComp, pg.name), provider=shape.buildData)
            pgNode._actions.append(_Reg(
                f"Set {pg.name}", "set", schema,
                handler=(lambda a, d, _s=shape: _s.setData(d)),
                writesTo=makeWriterRef(f"{uid}:{pg.name}:updated")))
            pageNode._children.append(pgNode)
        # page-level bulk_set (this page's pars)
        pageNode._actions.append(_bulk_reg(_bulk_entries(page, ownerComp), [page], ownerComp))
        op_entries.extend(_bulk_entries(page, ownerComp, section_prefix=page.name))
    # OP-level bulk_set (every page, sections prefixed by page name)
    root._actions.append(_bulk_reg(op_entries, pages, ownerComp, complete_par=RS_BUNDLE_COMPLETE_PAR))
    return root

# endregion registry


# region proxies

class _Reg:
    """Internal record of a registered action/emitter."""
    __slots__ = ("name", "short", "schema", "handler", "writesTo", "provider",
                 "change_key", "change_keys", "schema_ref", "schema_layout")

    def __init__(self, name, short, schema, handler=None, writesTo=None, provider=None,
                 change_key=None, change_keys=None, schema_ref=None, schema_layout=None):
        self.name = name
        self.short = short
        self.schema = schema
        self.handler = handler      # CLIENT-shape: (action, data) -> response  (actions)
        self.writesTo = writesTo    # dict | None  (property writer actions)
        self.provider = provider    # () -> value  (emitters)
        self.change_key = change_key    # parexec change key (op,par) for par-backed emitters
        self.change_keys = change_keys  # MULTIPLE keys (a sequence emitter: header + all blocks)
        self.schema_ref = schema_ref    # rship SchemaRef (WellKnown/Custom) for the typed widget
        self.schema_layout = schema_layout  # Action schemaLayout (bulk_set: ordered path/label/section)


class EmitterProxy:
    def __init__(self, target_proxy, short):
        self._t = target_proxy
        self._short = short
        self._last = None

    def pulse(self, value):
        """Publish a value to the server (call when it changes)."""
        self._last = value
        eid = self._t._child_id(self._short)
        if eid is not None:
            CLIENT.pulseEmitter(eid, _to_jsonable(value))


class PropertyProxy(EmitterProxy):
    """Same handle as an emitter; .pulse() is used for Deferred / external updates."""


class TargetProxy(TouchTarget):
    """A user-defined target. Implements the TouchTarget interface so RshipExt can
    collect it alongside tag-based targets and run the normal send/seed lifecycle."""

    def __init__(self, ownerComp, name, short, category, key, parent=None, id_override=None):
        # NOTE: instance is injected later by RshipExt.buildTargets once known.
        self.instance: Instance | None = None
        self.ownerComp = ownerComp
        self.name = name
        self.short = short
        self.category = category
        self.key = key
        self.parent = parent                          # nesting: parent TargetProxy (op->page->par)
        self._id_override = id_override               # explicit id (reflect_comp: the stored UUID scheme)
        self._children: typing.List["TargetProxy"] = []
        self._actions: typing.List[_Reg] = []
        self._emitters: typing.Dict[str, _Reg] = {}
        self._monitor_ops: typing.Set[str] = set()   # op paths backing par() properties
        # required by RshipExt's stream handling on opTargets values:
        self.streamSource = None

    # --- identity ---
    @property
    def id(self) -> str:
        if self._id_override is not None:
            return self._id_override                  # explicit (reflect_comp: stored UUID)
        if self.parent is not None:
            return f"{self.parent.id}:{self.short}"   # nested -> parentId:short
        sid = self.instance.serviceId if self.instance else "td"
        return f"{sid}:{self.short}"

    def _child_id(self, short):
        if self.instance is None:
            return None
        return f"{self.id}:{short}"

    # --- public registration API ---
    def action(self, name, handler=None, *, short_id=None, schema=None, type=None):
        """Register an action. Usable imperatively (action("Go", self.go)) or as a
        decorator (@t.action("Go") / @t.action)."""
        if callable(name) and handler is None:        # @t.action (bare)
            fn = name
            return self._add_action(_humanize(fn.__name__), fn, None, None, None)
        if handler is None:                            # @t.action("Name")
            def deco(fn):
                self._add_action(name, fn, short_id, schema, type)
                return fn
            return deco
        return self._add_action(name, handler, short_id, schema, type)  # imperative

    def _add_action(self, name, fn, short_id, schema, type):
        short = short_id or _slug(name)
        sch, adapter = _reflect(fn, schema, type)
        self._actions.append(_Reg(name, short, sch, handler=(lambda action, data: adapter(data))))
        _mark_dirty()
        return self

    def emitter(self, name, *, get=None, short_id=None, type=None, schema=None) -> EmitterProxy:
        """Register an emitter (read-only value). With get=, it's a polled value
        source (seeded/resent on demand). Without, it's push-only via .pulse()."""
        short = short_id or _slug(name)
        proxy = EmitterProxy(self, short)
        if get is not None:
            ret = _safe_hints(get).get("return")
            sch = schema if schema is not None else (_token_to_schema(type) if type else _type_to_schema(ret))
            provider = (lambda g=get: _to_jsonable(g()))
        else:
            sch = schema if schema is not None else (_token_to_schema(type) or {})
            provider = (lambda p=proxy: _to_jsonable(p._last))
        self._emitters[short] = _Reg(name, short, sch, provider=provider)
        _mark_dirty()
        return proxy

    def property(self, name, *, get, set=None, short_id=None, type=None, schema=None) -> PropertyProxy:
        """Register a property: a read value source (get) optionally paired with a
        canonical writer (set). set=None -> read-only property."""
        short = short_id or _slug(name)
        proxy = PropertyProxy(self, short)

        ret = _safe_hints(get).get("return")
        read_schema = schema if schema is not None else (_token_to_schema(type) if type else _type_to_schema(ret))
        self._emitters[short] = _Reg(name, short, read_schema, provider=(lambda g=get: _to_jsonable(g())))

        if set is not None:
            write_schema, set_adapter = _reflect(set, schema, type)
            # emitterId needs the instance (serviceId), unknown until RshipExt injects
            # it — defer resolution to getActions via a sentinel encoding the emitter short.
            self._actions.append(_Reg(
                f"Set {name}", f"{short}-set", write_schema,
                handler=self._make_writer(short, get, set_adapter),
                writesTo=makeWriterRef(f"__SELF__:{short}"),
            ))
        _mark_dirty()
        return proxy

    def _make_writer(self, emitter_short, getter, set_adapter):
        def handler(action, data):
            outcome = set_adapter(data)
            eid = self._child_id(emitter_short)
            if isinstance(outcome, Applied):
                val = outcome.value if outcome.value is not None else (getter() if getter else None)
                if eid is not None and val is not None:
                    CLIENT.pulseEmitter(eid, _to_jsonable(val))
            elif isinstance(outcome, Rejected):
                op.RS_LOG.Warning(f"[rship]: write to {self.name} rejected: {outcome.reason}")
            elif isinstance(outcome, _Deferred):
                pass  # property will pulse later
            else:
                op.RS_LOG.Warning(f"[rship]: setter for {self.name} did not return a WriteOutcome")
                if eid is not None and getter is not None:
                    CLIENT.pulseEmitter(eid, _to_jsonable(getter()))
            return None
        return handler

    # --- par-backed reflection (TD parameter -> rship control via par_schema) ---
    def par(self, par_group, *, name=None, short_id=None):
        """Expose a TD ParGroup as an rship control, reflected via par_schema:
          - a VALUE par -> a PROPERTY: a read emitter the parexec auto-pulses on ANY TD-side
            change (changeKey = (op, par)), paired with a ParMode-safe writer.
          - a PULSE/Momentary par -> a no-payload ACTION (a fire), NOT a property.
        Returns the PropertyProxy (or None for a trigger). The owner op is registered for
        parexec monitoring (RshipExt.buildTargets reads monitored_ops())."""
        label = name or _humanize(par_group.name)
        short = short_id or _slug(par_group.name)
        self._monitor_ops.add(par_group.owner.path)

        if par_schema.is_trigger(par_group):
            self._actions.append(_Reg(label, short, {},
                handler=(lambda action, data, _pg=par_group: par_schema.write(_pg, None))))
            _mark_dirty()
            return None

        ref = par_schema.schema_ref(par_group) or par_schema.custom_schema_ref(par_group)
        inline = par_schema.inline_schema(par_group)
        proxy = PropertyProxy(self, short)
        self._emitters[short] = _Reg(
            label, short, inline, schema_ref=ref,
            change_key=makeEmitterChangeKey(par_group.owner, par_group.name),
            provider=(lambda _pg=par_group: _to_jsonable(par_schema.read(_pg))))
        self._actions.append(_Reg(
            f"Set {label}", f"{short}-set", inline, schema_ref=ref,
            handler=self._make_par_writer(short, par_group),
            writesTo=makeWriterRef(f"__SELF__:{short}")))
        _mark_dirty()
        return proxy

    def _make_par_writer(self, emitter_short, par_group):
        def handler(action, data, _pg=par_group, _short=emitter_short):
            if par_schema.write(_pg, data):
                eid = self._child_id(_short)
                if eid is not None:
                    CLIENT.pulseEmitter(eid, _to_jsonable(par_schema.read(_pg)))
            else:
                op.RS_LOG.Warning(
                    f"[rship]: par '{_pg.name}' not writable (expression/export/bind mode); write ignored")
            return None
        return handler

    def monitored_ops(self) -> typing.Set[str]:
        """Op paths whose parameters back this target's par() properties — RshipExt adds
        these to the parexec's monitored ops so a TD-side par change auto-pulses its emitter."""
        ops = set(self._monitor_ops)
        for ch in self._children:                  # children's bound ops bubble up
            ops |= ch.monitored_ops()
        return ops

    # --- nested targets (op -> page -> par trees) ---
    def child(self, name, *, short_id=None, category="python"):
        """Create a NESTED child target under this one (its parentTargets = [self.id]).
        Children are reached via collectChildren(), not the global registry, so build a tree
        by calling t.child(...).par(...) etc. Returns the child TargetProxy."""
        short = short_id or _slug(name)
        ch = TargetProxy(self.ownerComp, name, short, category, f"{self.key}:{short}", parent=self)
        self._children.append(ch)
        _mark_dirty()
        return ch

    # --- sequence as an array property ---
    def sequence(self, sequence, *, name=None, short_id=None):
        """Expose a TD Sequence as an rship array PROPERTY: read = the blocks as a list of
        field-objects (the emitter watches the header + EVERY block par, so any block change
        auto-pulses the whole array), write = set the block count + each field. Each field is
        reflected via par_schema."""
        seq = sequence
        owner = seq.owner
        label = name or _humanize(seq.name)
        short = short_id or _slug(seq.name)
        self._monitor_ops.add(owner.path)
        prefix = f"{seq.name}0"
        fields = [pg.name[len(prefix):] for pg in seq.blockParGroups if pg.name.startswith(prefix)]

        def block_pg(i, field):
            return owner.parGroup[f"{seq.name}{i}{field}"]

        item_props = {f: par_schema.inline_schema(block_pg(0, f))
                      for f in fields if block_pg(0, f) is not None}
        schema = {"type": "array", "items": {"type": "object", "properties": item_props}}

        def read_blocks():
            return [{f: par_schema.read(block_pg(i, f)) for f in fields if block_pg(i, f) is not None}
                    for i in range(seq.numBlocks)]

        def writer(action, data, _short=short):
            if not isinstance(data, list):
                return None
            seq.numBlocks = len(data)
            for i, bd in enumerate(data):
                if isinstance(bd, dict):
                    for f in fields:
                        if f in bd and block_pg(i, f) is not None:
                            par_schema.write(block_pg(i, f), bd[f])
            eid = self._child_id(_short)
            if eid is not None:
                CLIENT.pulseEmitter(eid, _to_jsonable(read_blocks()))
            return None

        cks = [makeEmitterChangeKey(owner, seq.name)] + \
              [makeEmitterChangeKey(owner, pg.name) for pg in seq.blockParGroups]
        cks = list(dict.fromkeys(cks))                    # dedup, preserve order
        proxy = PropertyProxy(self, short)
        self._emitters[short] = _Reg(label, short, schema, change_key=cks[0], change_keys=cks,
                                     provider=(lambda: _to_jsonable(read_blocks())))
        self._actions.append(_Reg(f"Set {label}", f"{short}-set", schema, handler=writer,
                                  writesTo=makeWriterRef(f"__SELF__:{short}")))
        _mark_dirty()
        return proxy

    # --- bulk set (one action spanning several pars) ---
    def bulk(self, name, par_groups, *, short_id=None):
        """A bulk-set ACTION over several pars: takes an object {key: value} and writes each
        (ParMode-safe, via par_schema). Mirrors the tag-based page/op bulk set."""
        short = short_id or _slug(name)
        items = {_slug(pg.name): pg for pg in par_groups}
        schema = {"type": "object", "properties": {k: par_schema.inline_schema(pg) for k, pg in items.items()}}
        for pg in par_groups:
            self._monitor_ops.add(pg.owner.path)

        def handler(action, data, _items=items):
            if isinstance(data, dict):
                for k, v in data.items():
                    if k in _items:
                        par_schema.write(_items[k], v)
            return None
        self._actions.append(_Reg(name, short, schema, handler=handler))
        _mark_dirty()
        return self

    # --- video stream source ---
    def stream(self, source):
        """Mark this target as a video STREAM source (a TOP path or op). The server uses it
        to establish WebRTC (mirrors the tag-based rship_stream tag)."""
        self.streamSource = source if isinstance(source, str) else source.path
        _mark_dirty()
        return self

    # --- TouchTarget interface (consumed by RshipExt.sendProjectData) ---
    def getTarget(self) -> Target:
        return Target(
            id=self.id,
            name=self.name,
            parentTargets=([self.parent.id] if self.parent is not None else []),
            category=self.category,
            serviceId=self.instance.serviceId,
        )

    def getActions(self) -> typing.List[Action]:
        actions = []
        for reg in self._actions:
            writesTo = reg.writesTo
            if writesTo is not None and str(writesTo.get("emitterId", "")).startswith("__SELF__:"):
                em_short = writesTo["emitterId"].split(":", 1)[1]
                writesTo = makeWriterRef(self._child_id(em_short))
            actions.append(Action(
                id=self._child_id(reg.short),
                name=reg.name,
                targetId=self.id,
                schema=reg.schema,
                serviceId=self.instance.serviceId,
                handler=reg.handler,
                writesTo=writesTo,
                schemaRef=reg.schema_ref,
                schemaLayout=reg.schema_layout,
            ))
        return actions

    def getEmitters(self) -> typing.List[Emitter]:
        emitters = []
        for short, reg in self._emitters.items():
            eid = self._child_id(short)
            em = Emitter(
                id=eid,
                name=reg.name,
                targetId=self.id,
                serviceId=self.instance.serviceId,
                schema=reg.schema,
                # par-backed emitters carry the real (op,par) change key so the parexec
                # auto-pulses them; push-only emitters keep the synthetic id key.
                changeKey=(reg.change_key or eid),
                handler=reg.provider,
                schemaRef=reg.schema_ref,
            )
            # a sequence emitter watches MANY pars (header + every block field); RshipExt
            # indexes all of these so any block change re-pulses the whole array.
            if reg.change_keys:
                em.changeKeys = reg.change_keys
            emitters.append(em)
        return emitters

    def collectChildren(self):
        out = [self]
        for ch in self._children:
            ch.instance = self.instance          # propagate the instance down the target tree
            out.extend(ch.collectChildren())
        return out

    def getStreamInfo(self):
        if self.streamSource is None or self.instance is None:
            return None
        return Stream(id=f"{self.id}-{self.instance.id}-stream", name=self.name)

# endregion proxies


# region declarative (TargetExt + decorators)

class _Marker:
    def __init__(self, kind, name, schema, type):
        self.kind = kind
        self.name = name
        self.schema = schema
        self.type = type


def action(name=None, *, schema=None, type=None):
    """Decorator marking a TargetExt method as an action. @rship.action or
    @rship.action("Name")."""
    def deco(fn):
        fn._rship_marker = _Marker("action", name or _humanize(fn.__name__), schema, type)
        return fn
    if callable(name):  # bare @rship.action
        fn, name = name, None
        return deco(fn)
    return deco


def emitter(name=None, *, schema=None, type=None):
    """Decorator marking a TargetExt method as a read-only emitter value source."""
    def deco(fn):
        fn._rship_marker = _Marker("emitter", name or _humanize(fn.__name__), schema, type)
        return fn
    if callable(name):
        fn, name = name, None
        return deco(fn)
    return deco


class _RshipProperty:
    """A descriptor carrying rship metadata. Behaves like @property for the user's
    own code (instance access calls the getter, assignment calls the setter) and is
    collected by TargetExt for registration."""
    def __init__(self, fget=None, fset=None, rship_name=None, rship_type=None, rship_schema=None):
        self.fget = fget
        self.fset = fset
        self.rship_name = rship_name
        self.rship_type = rship_type
        self.rship_schema = rship_schema

    def __get__(self, obj, objtype=None):
        if obj is None:
            return self
        if self.fget is None:
            raise AttributeError("rship property has no getter")
        return self.fget(obj)

    def __set__(self, obj, value):
        if self.fset is None:
            raise AttributeError("rship property has no setter")
        self.fset(obj, value)

    def setter(self, fset):
        return _RshipProperty(self.fget, fset, self.rship_name, self.rship_type, self.rship_schema)


def property(fget=None, *, name=None, type=None, schema=None):  # shadows builtin within module
    """Decorator marking a TargetExt getter as an rship property. Pair with
    @<name>.setter for the writer (must return a WriteOutcome)."""
    def deco(fn):
        return _RshipProperty(fn, rship_name=name or _humanize(fn.__name__),
                              rship_type=type, rship_schema=schema)
    if callable(fget):
        return deco(fget)
    return deco


class TargetExt:
    """Base for declarative targets. Subclass, set rship_name, decorate methods with
    @rship.action / @rship.emitter / @rship.property. Call super().__init__(ownerComp)."""
    rship_name = None

    def __init__(self, ownerComp):
        self.ownerComp = ownerComp
        t = target(ownerComp, self.rship_name or _humanize(type(self).__name__))
        for attrname, attr in _iter_class_attrs(type(self)):
            if isinstance(attr, _RshipProperty):
                getter = attr.fget.__get__(self) if attr.fget else None
                setter = attr.fset.__get__(self) if attr.fset else None
                t.property(attr.rship_name or _humanize(attrname), get=getter, set=setter,
                           type=attr.rship_type, schema=attr.rship_schema)
            else:
                m = getattr(attr, "_rship_marker", None)
                if m is None:
                    continue
                bound = getattr(self, attrname)
                if m.kind == "action":
                    t.action(m.name, bound, schema=m.schema, type=m.type)
                elif m.kind == "emitter":
                    t.emitter(m.name, get=bound, schema=m.schema, type=m.type)
        self.rship = t


def _iter_class_attrs(klass):
    seen = set()
    for base in klass.__mro__:
        for attrname, attr in vars(base).items():
            if attrname in seen:
                continue
            seen.add(attrname)
            yield attrname, attr

# endregion declarative
