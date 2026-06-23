"""
comp_engine — Python port of the rship comp-engine executor SDK.

Comp engine = server-authoritative dynamic placement/topology. You declare element
KINDS once; the rship server's reactive solver decides which element instances are
placed, ordered, wired, and animated, and hands you an Assignment to RENDER. You never
author placement/merge/order/capacity.

Two planes:
  - TOPOLOGY  — which instances exist (kind, wiring, order). Arrives via the reserved
    `apply` action carrying an Assignment; you render it. Only on structural change.
  - VALUE     — animated per-instance caps + presence. These are literally Properties
    (SetCap action + cap readback emitter); driven every frame, reconciled by the same
    readback-pulse machinery as the rest of the executor (exec.CLIENT).

Strictly opt-in: declare no kinds and you simply aren't a comp engine.

This mirrors libs/sdk/rs/src/comp_engine/ (KindDefBuilder / KindRegistryBuilder /
KindHandler / CompEngineProxy). See memory rship-comp-engine for the full spec/casing.

WIRE-SHAPE TODOs (confirm with malcolm:rship before relying on server round-trip):
  - The CompEngine *declaration* item shape (how the engine + KindRegistry is published
    and how the server maps its reserved verbs to our action ids). `_declarationItem()`
    is a best-guess; flagged below.
  - SchemaRef wire shape — passed through verbatim for now.
  - Reserved-action id scheme — we mint `<engine_id>:apply` etc.; spot-check vs a live frame.
"""
import dataclasses
import typing

import td

from exec import CLIENT, Action, Emitter, Status, Target, makeWriterRef


# region enum string values (snake_case on the wire)

class Instanceability:
    INSTANCEABLE = "instanceable"
    SINGLETON = "singleton"


class InputOrdering:
    UNORDERED = "unordered"
    ORDERED = "ordered"


class PrepClass:
    IMMEDIATE = "immediate"
    REQUIRES_PREP = "requires_prep"


# Built-in cap kinds (internally tagged on "kind"). Never declare PRESENCE as a cap —
# it's a server-injected intrinsic.
BUILTIN_CAPS = (
    "weight", "mask_source", "blend_mode", "tint", "intensity",
    "opacity", "crossfade_t", "position_xy", "scale",
)

# endregion


# region declaration types (what we SEND in the KindRegistry)

def schema(type_name: str, **extra) -> dict:
    """Build a SchemaRef. NOTE the casing trap: SchemaRef is PascalCase-tagged
    {"kind":"WellKnown","value":{"type":"Bool"}} — unlike the snake_case Cap tags.
    type_name is a WellKnownSchema PascalCase name (Bool/Scalar/Scalar01/Int/String/
    Color/Vec3/Signal/Mask/Texture/EnumOf/CompElementClipPayload/…). EnumOf takes
    variants=[...]."""
    value = {"type": type_name}
    value.update(extra)
    return {"kind": "WellKnown", "value": value}


def _schema_ref_wire(s):
    if s is None:
        return None
    if isinstance(s, str):          # convenience: "Bool" -> full SchemaRef
        return schema(s)
    return s                        # already a SchemaRef dict


@dataclasses.dataclass
class CapDef:
    """An animated property on an instance. `cap` is a built-in name or "custom"."""
    cap: str
    default: typing.Any = None
    label: str | None = None
    widget: str | None = None
    prep_class: str = PrepClass.IMMEDIATE
    custom_id: str | None = None     # required when cap == "custom"
    schema_ref: typing.Any = None    # required when cap == "custom"

    def to_wire(self) -> dict:
        if self.cap == "custom":
            # NOTE the two traps: tag values are snake_case, and Cap::Custom's inner
            # field is `schema_ref` (snake_case), unlike the camelCase struct fields.
            cap_wire = {"kind": "custom", "id": self.custom_id, "schema_ref": _schema_ref_wire(self.schema_ref)}
        else:
            cap_wire = {"kind": self.cap}
        return {
            "cap": cap_wire,
            "default": self.default,
            "constraints": {"label": self.label, "widget": self.widget},
            "prepClass": self.prep_class,
        }


def cap(kind: str, *, default=None, label=None, widget=None, prep=PrepClass.IMMEDIATE) -> CapDef:
    """A built-in cap (intensity, opacity, tint, scale, …)."""
    return CapDef(cap=kind, default=default, label=label, widget=widget, prep_class=prep)


def custom_cap(cap_id: str, schema_ref, *, default=None, label=None, widget=None, prep=PrepClass.IMMEDIATE) -> CapDef:
    """A custom-typed cap with your own schema."""
    return CapDef(cap="custom", custom_id=cap_id, schema_ref=schema_ref,
                  default=default, label=label, widget=widget, prep_class=prep)


@dataclasses.dataclass
class TriggerDef:
    id: str
    display_name: str
    payload_schema: typing.Any = None   # always null in v1

    def to_wire(self) -> dict:
        return {"id": self.id, "displayName": self.display_name,
                "payloadSchema": _schema_ref_wire(self.payload_schema)}


@dataclasses.dataclass
class OutputChannelDef:
    id: str
    display_name: str
    schema_ref: typing.Any
    semantic: typing.Any = "signal"     # "mask"|"texture"|"signal"|{"custom":{"tag":..}}

    def to_wire(self) -> dict:
        return {"id": self.id, "displayName": self.display_name,
                "schemaRef": _schema_ref_wire(self.schema_ref), "semantic": self.semantic}


@dataclasses.dataclass
class CapacityConstraint:
    max: int
    eviction: str = "lowest_presence"   # snake_case enum
    index_reuse_cost: float = 0.0

    def to_wire(self) -> dict:
        return {"max": int(self.max), "eviction": self.eviction, "indexReuseCost": self.index_reuse_cost}


@dataclasses.dataclass
class InputDef:
    id: str
    display_name: str
    accepts_kinds: list                  # [KindId]
    accepts_channel: str
    fan_in: bool = False
    ordering: str = InputOrdering.UNORDERED
    blend: typing.Any = "weighted"
    caps: list = dataclasses.field(default_factory=list)   # [CapDef]
    capacity: CapacityConstraint | None = None
    required_min: int | None = None

    def to_wire(self) -> dict:
        w = {
            "id": self.id,
            "displayName": self.display_name,
            "fanIn": self.fan_in,
            # Accepts is internally tagged on "level"; only "element" exists. Inner
            # field names are lowercase single words (another snake-ish trap).
            "accepts": {"level": "element", "kinds": list(self.accepts_kinds), "channel": self.accepts_channel},
            "ordering": self.ordering,
            "blend": self.blend,
            "caps": [c.to_wire() for c in self.caps],
        }
        if self.capacity is not None:
            w["capacity"] = self.capacity.to_wire()
        if self.required_min is not None:
            w["requiredMin"] = int(self.required_min)
        return w


@dataclasses.dataclass
class KindDef:
    id: str
    display_name: str
    payload_schema: typing.Any
    cap_schema: list = dataclasses.field(default_factory=list)
    trigger_schema: list = dataclasses.field(default_factory=list)
    output_channels: list = dataclasses.field(default_factory=list)
    inputs: list = dataclasses.field(default_factory=list)
    instanceability: str = Instanceability.INSTANCEABLE
    instance_ordering: str = InputOrdering.UNORDERED
    instance_capacity: CapacityConstraint | None = None

    def is_sink(self) -> bool:
        return len(self.output_channels) == 0

    def to_wire(self) -> dict:
        w = {
            "id": self.id,
            "displayName": self.display_name,
            "payloadSchema": _schema_ref_wire(self.payload_schema),
            "capSchema": [c.to_wire() for c in self.cap_schema],
            "triggerSchema": [t.to_wire() for t in self.trigger_schema],
            "outputChannels": [o.to_wire() for o in self.output_channels],
            "inputs": [i.to_wire() for i in self.inputs],
            "instanceability": self.instanceability,
            "instanceOrdering": self.instance_ordering,
        }
        if self.instance_capacity is not None:
            w["instanceCapacity"] = self.instance_capacity.to_wire()
        return w


class KindDefBuilder:
    """Fluent KindDef builder (mirrors the Rust SDK)."""
    def __init__(self, id, display_name, payload_schema):
        self._k = KindDef(id=id, display_name=display_name, payload_schema=payload_schema)

    def cap(self, capdef: CapDef): self._k.cap_schema.append(capdef); return self
    def caps(self, capdefs): self._k.cap_schema.extend(capdefs); return self
    def trigger(self, t: TriggerDef): self._k.trigger_schema.append(t); return self
    def output_channel(self, oc: OutputChannelDef): self._k.output_channels.append(oc); return self
    def input(self, i: InputDef): self._k.inputs.append(i); return self
    def singleton(self): self._k.instanceability = Instanceability.SINGLETON; return self
    def instanceability(self, v): self._k.instanceability = v; return self
    def instance_ordering(self, v): self._k.instance_ordering = v; return self
    def instance_capacity(self, c: CapacityConstraint): self._k.instance_capacity = c; return self
    def build(self) -> KindDef: return self._k

# endregion


# region reflection helpers (TD pars <-> caps) — ergonomic primitives for extension devs

# TD par style -> WellKnown cap schema type. Menu is special-cased (EnumOf w/ variants).
_PAR_STYLE_SCHEMA = {
    "Float": "Scalar", "Int": "Int",
    "Toggle": "Bool", "Pulse": "Bool", "Momentary": "Bool",
    "RGB": "Vec3", "XYZ": "Vec3", "UV": "Vec3", "WH": "Vec3",
    "RGBA": "Color", "XYZW": "Color",
    "Str": "String", "StrMenu": "String", "File": "String", "Folder": "String",
}


def cap_from_par_group(par_group, *, cap_id=None, label=None, prep=PrepClass.IMMEDIATE) -> CapDef:
    """Reflect a TD ParGroup into a comp-engine cap, typed from the par style:
    Float->Scalar, Int->Int, Toggle->Bool, RGB/XYZ->Vec3, RGBA->Color, Menu->EnumOf(menuNames),
    Str->String. Unknown styles fall back to a Scalar (a draggable number)."""
    cap_id = cap_id or par_group.name
    label = label if label is not None else (par_group.label or cap_id)
    if par_group.style == "Menu":
        schema_ref = schema("EnumOf", variants=list(par_group[0].menuNames))
    else:
        schema_ref = _PAR_STYLE_SCHEMA.get(par_group.style, "Scalar")
    return custom_cap(cap_id, schema_ref, label=label, prep=prep)


def _components(v, n) -> list:
    """Normalize a Color/Vec cap value (dict {r,g,b,a}/{x,y,z} or list) to n FLOAT
    components. Coercing to float keeps our writes consistent (the wire sends whole-number
    color channels as Int; see rship-k1f)."""
    if isinstance(v, dict):
        keys = ["r", "g", "b", "a"] if n == 4 else ["x", "y", "z"] if n == 3 else list(v.keys())
        vals = [v.get(k, 0.0) for k in keys[:n]]
    elif isinstance(v, (list, tuple)):
        vals = list(v)[:n] + [0.0] * max(0, n - len(v))
    else:
        vals = [v] * n
    return [float(x) if isinstance(x, (int, float)) else x for x in vals]


class SequenceReflector:
    """Two-way bridge between a TD sequence's block parameters and comp-engine caps.

    Reflects each block field into one cap (typed from the TD par style) for the kind
    declaration, and writes cap values back into a placed block's parameters on apply:

        refl = comp_engine.SequenceReflector(ownerComp, "Sequence")
        kind = (KindDefBuilder("seq.block", "Block", "CompElementClipPayload")
                .instanceability(Instanceability.INSTANCEABLE)
                .instance_ordering(InputOrdering.ORDERED)
                .caps(refl.caps())                  # caps ARE the reflected block fields
                .build())
        ...
        def on_apply(self, ctx, batch):
            refl.render(batch)                      # ordered placement -> sequence blocks

    Call refl.refresh() after editing the block's parameters in TD to re-reflect the
    cap list. (Wire-routed fields — block pars filled by an upstream engine's output
    rather than a cap — are a planned extension; the routing model is being settled with
    the Unreal executor before wiring it in.)
    """
    def __init__(self, owner, sequence_name):
        self.owner = owner
        self.sequence_name = sequence_name
        self.refresh()

    @property
    def sequence(self):
        return self.owner.seq[self.sequence_name]

    def refresh(self):
        """(Re)reflect the block-0 template fields into cap + writer descriptors."""
        prefix = f"{self.sequence_name}0"
        self._fields = []
        for pg in self.sequence.blockParGroups:
            if not pg.name.startswith(prefix):
                continue
            field = pg.name[len(prefix):]                       # e.g. "float3"
            suffixes = [m.name[len(prefix):] for m in pg]       # e.g. ["float2r","float2g",...]
            self._fields.append({
                "cap_id": field,
                "suffixes": suffixes,
                "cap": cap_from_par_group(pg, cap_id=field),
            })
        return self

    def caps(self) -> list:
        return [f["cap"] for f in self._fields]

    def render(self, batch):
        """Materialize an ordered batch of placed instances as sequence blocks, writing
        each cap value back to its block parameter(s)."""
        ordered = sorted(batch, key=lambda ka: (ka.order_index if ka.order_index is not None else 0))
        self.sequence.numBlocks = len(ordered)
        for i, ka in enumerate(ordered):
            self.write_block(i, ka.caps)

    def write_block(self, i, caps: dict):
        for f in self._fields:
            v = caps.get(f["cap_id"])
            if v is None:
                continue
            sufs = f["suffixes"]
            if len(sufs) > 1:                                   # Color/Vec -> spread components
                for suf, c in zip(sufs, _components(v, len(sufs))):
                    self._set(f"{self.sequence_name}{i}{suf}", c)
            else:
                self._set(f"{self.sequence_name}{i}{sufs[0]}", v)

    def _set(self, par_name, value):
        p = self.owner.par[par_name]
        if p is None or value is None:
            return
        try:
            p.val = value
        except Exception:
            try:
                p.menuIndex = int(value)                        # Menu cap that arrived as an index
            except Exception:
                pass

# endregion


# region handler interface

@dataclasses.dataclass
class KindAssignment:
    """One placed instance handed to a kind's on_apply."""
    instance: dict          # {"compElementId":.., "instanceTag":..}
    caps: dict              # {cap_id: value}  (current value-plane bag)
    presence: float
    wire_inputs: list       # [WireInputEntry]
    order_index: int | None = None


class PrepReport:
    @staticmethod
    def ready(): return {"kind": "ready"}
    @staticmethod
    def failed(reason): return {"kind": "failed", "reason": reason}
    @staticmethod
    def progress(p): return {"kind": "progress", "progress": p}


class ApplyCtx:
    def __init__(self, engine: "CompEngineProxy", generation: int, transaction_id: str):
        self.engine = engine
        self.generation = generation
        self.transaction_id = transaction_id

    def emit_output(self, instance: dict, channel: str, value):
        self.engine._emit_output(instance, channel, value)


class KindHandler:
    """Subclass and implement on_apply. The rest are optional. Note: synchronous —
    TD callbacks aren't async (the Rust SDK trait is async)."""
    def on_apply(self, ctx: ApplyCtx, batch: list):
        raise NotImplementedError("KindHandler.on_apply must be implemented")

    def on_prepare(self, ctx: ApplyCtx, batch: list):
        return PrepReport.ready()

    def on_cancel(self, ctx: ApplyCtx):
        pass

    def on_button_pressed(self, instance: dict, button_id: str, data):
        pass

# endregion


# region registry

class KindRegistry:
    def __init__(self):
        self.kinds: typing.Dict[str, KindDef] = {}
        self.handlers: typing.Dict[str, KindHandler] = {}

    def get(self, kind_id): return self.kinds.get(kind_id)
    def to_wire(self) -> dict:
        return {"kinds": [k.to_wire() for k in self.kinds.values()]}


class KindRegistryBuilder:
    def __init__(self):
        self._reg = KindRegistry()

    def register(self, kind: KindDef):
        if kind.id in self._reg.kinds:
            raise ValueError(f"duplicate kind id {kind.id}")
        self._reg.kinds[kind.id] = kind
        return self

    def register_with_handler(self, kind: KindDef, handler: KindHandler):
        self.register(kind)
        self._reg.handlers[kind.id] = handler
        return self

    def build(self) -> KindRegistry:
        return self._reg

# endregion


# region engine registry (td-anchored, same reason as rship.py)

def _engines() -> dict:
    s = getattr(td, "_rship_engines", None)
    if s is None:
        s = {}
        td._rship_engines = s
    return s


def get_engines() -> list:
    return list(_engines().values())

# endregion


@dataclasses.dataclass
class CompEngineArgs:
    short_id: str
    display_name: str
    kind_registry: KindRegistry
    host_target: typing.Any = None      # optional: nest under a user-facing Target
    prep_timeout_ms: int = 5000


def comp_engine(ownerComp, args: CompEngineArgs) -> "CompEngineProxy":
    """Stand up (or replace) a comp engine. Registered into the td-anchored engine
    registry; RshipExt publishes the engine Target + reserved verbs and the engine
    renders Assignments. Strictly opt-in."""
    key = f"{ownerComp.path}:{args.short_id}"
    proxy = CompEngineProxy(ownerComp, args, key)
    _engines()[key] = proxy
    # reuse rship's dirty flag so RshipExt re-publishes
    try:
        import rship
        rship._mark_dirty()
    except Exception:
        pass
    return proxy


class CompEngineProxy:
    """The engine runtime. Stands itself up on the server via publish() (the ordered
    sequence the SDK requires) and renders Assignments. The value plane (caps/presence)
    and committed_state ride exec.CLIENT's property/provider machinery, so reconnect
    re-pulse is handled by RshipExt.seedProperties."""

    def __init__(self, ownerComp, args: CompEngineArgs, key: str):
        self.instance = None            # injected by RshipExt before publish()
        self.ownerComp = ownerComp
        self.args = args
        self.key = key
        # last committed Assignment (the committed_state readback + cold-start gate)
        self._committed = {"slotStates": [], "overflow": [], "generation": 0}
        # current rendered slots, keyed by instance id "(compElementId, instanceTag)"
        self._slots: typing.Dict[tuple, dict] = {}
        self._readback_last: typing.Dict[str, typing.Any] = {}   # emitterId -> last pulsed (dedup)

    # --- identity ---
    @property
    def id(self) -> str:
        sid = self.instance.serviceId if self.instance else "td"
        return f"{sid}:{self.args.short_id}"

    def _rid(self, suffix):   # reserved action/emitter id
        return f"{self.id}:{suffix}"

    def _host_id(self):
        """host_target may be a target id string or any object with an `.id`."""
        h = self.args.host_target
        if h is None:
            return None
        return h if isinstance(h, str) else h.id

    # --- publish (ordered stand-up sequence; order matters) ---
    def publish(self):
        """Stand the engine up on the server in the exact order the SDK requires:
        target -> reserved EMITTERS -> reserved ACTIONS (apply writes committed_state)
        -> CompEngine entity -> initial committed_state pulse. Idempotent: re-publishing
        on reconnect re-sends and re-pulses the last committed state (cold-start gate)."""
        if self.instance is None:
            return
        eid = self.id
        # 1. engine Target (online). A host_target is REQUIRED for UI discoverability:
        # the Comp Elements palette answers "what kinds can I drop here?" via
        # CompEngineKindsByHostTarget keyed on the host, so a host-less engine's kinds
        # surface nowhere. When hosted: parent the engine target to the host and mark it
        # managed so the scene-editor tree hides the wire actions/emitters.
        host_id = self._host_id()
        parents = [host_id] if host_id else []
        engine_target = Target(id=eid, name=self.args.display_name, parentTargets=parents,
                               category="comp-engine", serviceId=self.instance.serviceId)
        if host_id:
            engine_target.managed = True
        CLIENT.set(engine_target)
        CLIENT.setTargetStatus(eid, self.instance.id, Status.Online)
        # 2. reserved EMITTERS first (committed_state must exist before the apply action)
        self._register_emitter(self._rid("prep_report"), "Prep Report", provider=(lambda: None))
        self._register_emitter(self._rid("committed_state"), "Committed State",
                               provider=(lambda: self._committed))
        # 3. reserved ACTIONS — apply is the CANONICAL WRITER of committed_state
        self._register_action(self._rid("apply"), "Apply", self._handle_apply,
                              writesTo=makeWriterRef(self._rid("committed_state")))
        self._register_action(self._rid("prepare"), "Prepare", self._handle_prepare)
        self._register_action(self._rid("cancel"), "Cancel", self._handle_cancel)
        self._register_action(self._rid("request_state"), "Request State", self._handle_request_state)
        # 4. the CompEngine entity (server maps verbs -> ids via its named fields)
        CLIENT.sendEvent(CLIENT.buildSetEvent(self._engine_entity(), itemType="CompEngine"))
        # 5. initial committed_state baseline (empty on first stand-up; last committed on reconnect)
        CLIENT.pulseEmitter(self._rid("committed_state"), self._committed)
        # 6. re-register per-instance readback providers. RshipExt.sendProjectData calls
        # clearEmitterValueProviders() before each publish, which wipes the cap/presence/
        # output providers registered during apply; restore them from the readback cache
        # so seedProperties force-re-pulses every per-instance readback on reconnect.
        # (Inbound SetCap handlers live in CLIENT.handlers, which is never cleared.)
        for emitter_id in list(self._readback_last.keys()):
            CLIENT.saveEmitterValueProvider(emitter_id,
                                            (lambda eid=emitter_id: self._readback_last.get(eid)))

    def _engine_entity(self) -> dict:
        eid = self.id
        return {
            "id": eid,                                  # same string as engineTargetId
            "serviceId": self.instance.serviceId,
            "engineTargetId": eid,
            "hostTargetId": self._host_id(),
            "displayName": self.args.display_name,
            "kindRegistry": self.args.kind_registry.to_wire(),
            "prepTimeoutMs": self.args.prep_timeout_ms,
            # the server maps verb -> action/emitter id via THESE named fields (not id suffix)
            "prepareActionId": self._rid("prepare"),
            "applyActionId": self._rid("apply"),
            "cancelActionId": self._rid("cancel"),
            "requestStateActionId": self._rid("request_state"),
            "prepReportEmitterId": self._rid("prep_report"),
            "committedStateEmitterId": self._rid("committed_state"),
            "caps": [],                                 # server-mutated; always empty at creation
            "outputs": [],
        }

    # --- reserved-action inbound handlers (server -> executor) ---
    def _handle_prepare(self, action, data):
        env = data or {}
        assignment = env.get("targetState", {})
        ctx = ApplyCtx(self, assignment.get("generation", 0), env.get("transactionId"))
        batch_by_kind = self._batch_by_kind(assignment)
        report = PrepReport.ready()
        for kind_id, batch in batch_by_kind.items():
            handler = self.args.kind_registry.handlers.get(kind_id)
            if handler is not None:
                r = handler.on_prepare(ctx, batch)
                if r and r.get("kind") == "failed":
                    report = r
                    break
        CLIENT.pulseEmitter(self._rid("prep_report"), report)
        return None

    def _handle_apply(self, action, data):
        env = data or {}
        assignment = env.get("targetState", {"slotStates": [], "overflow": [], "generation": 0})
        self._render(assignment, env.get("transactionId"))
        self._committed = assignment
        CLIENT.pulseEmitter(self._rid("committed_state"), assignment)
        return None

    def _handle_cancel(self, action, data):
        ctx = ApplyCtx(self, self._committed.get("generation", 0), (data or {}).get("transactionId"))
        for handler in set(self.args.kind_registry.handlers.values()):
            handler.on_cancel(ctx)
        return None

    def _handle_request_state(self, action, data):
        # Re-report our committed Assignment.
        CLIENT.pulseEmitter(self._rid("committed_state"), self._committed)
        return None

    # --- render pipeline ---
    def _batch_by_kind(self, assignment) -> dict:
        out: typing.Dict[str, list] = {}
        for slot in assignment.get("slotStates", []):
            kind_id = slot.get("kind")
            caps = {c["capId"]: c.get("value") for c in slot.get("capValues", [])}
            ka = KindAssignment(
                instance=slot.get("boundInstance", {}),
                caps=caps,
                presence=None,   # presence value isn't in slotState; arrives via SetPresence
                wire_inputs=slot.get("wireInputValues", []),
                order_index=slot.get("orderIndex"),
            )
            out.setdefault(kind_id, []).append(ka)
        return out

    def _inst_key(self, inst: dict) -> tuple:
        return (inst.get("compElementId"), inst.get("instanceTag", ""))

    def _render(self, assignment, transaction_id):
        gen = assignment.get("generation", 0)
        ctx = ApplyCtx(self, gen, transaction_id)

        # Register every per-instance entity VERBATIM from the envelope ids, and seed
        # the value-plane bag. These are standard Actions/Emitters (caps = properties).
        new_slots: typing.Dict[tuple, dict] = {}
        for slot in assignment.get("slotStates", []):
            inst = slot.get("boundInstance", {})
            ik = self._inst_key(inst)
            bag = {}
            for cv in slot.get("capValues", []):
                self._register_cap(inst, cv["capId"], cv["actionId"], cv["emitterId"])
                bag[cv["capId"]] = cv.get("value")
                # Seed the readback on (re)materialize. FORCE it (don't dedup): the
                # contract is "empty dedup table at materialize → seed fires for EVERY
                # cap". A static/default cap (e.g. an un-animated custom cap) gets no
                # value-plane SetCap, so this seed is its ONLY readback — and an
                # optimistically-deduped seed that was lost (raced registration / sent
                # during a connection blip) would otherwise never re-fire.
                self._seed_readback(cv["emitterId"], cv.get("value"))
            # presence (always present per the wire spec)
            if slot.get("presenceActionId"):
                self._register_presence(inst, slot["presenceActionId"], slot["presenceEmitterId"])
            # trigger buttons
            for ba in slot.get("buttonActions", []) or []:
                self._register_button(inst, ba["buttonId"], ba["actionId"])
            new_slots[ik] = {"slot": slot, "bag": bag, "presence": None}
        self._slots = new_slots

        # Hand each kind its batch to render.
        for kind_id, batch in self._batch_by_kind(assignment).items():
            handler = self.args.kind_registry.handlers.get(kind_id)
            if handler is not None:
                handler.on_apply(ctx, batch)

    # --- per-instance value-plane entities (caps = properties) ---
    def _register_cap(self, inst, cap_id, action_id, emitter_id):
        ik = self._inst_key(inst)

        def on_set(action, value, _ik=ik, _cap=cap_id, _eid=emitter_id):
            slot = self._slots.get(_ik)
            if slot is None:
                return
            # cap BAG is sole source of truth: same-value early-out, then re-project.
            if _values_equivalent(slot["bag"].get(_cap), value):
                return
            slot["bag"][_cap] = value
            self._reproject(_ik)
            self._pulse_readback(_eid, value)

        self._register_action(action_id, f"Set {cap_id}", on_set, writesTo=makeWriterRef(emitter_id))
        self._register_emitter(emitter_id, cap_id)

    def _register_presence(self, inst, action_id, emitter_id):
        ik = self._inst_key(inst)

        def on_set(action, value, _ik=ik, _eid=emitter_id):
            slot = self._slots.get(_ik)
            if slot is None:
                return
            if _values_equivalent(slot.get("presence"), value):
                return
            slot["presence"] = value
            self._reproject(_ik)
            self._pulse_readback(_eid, value)

        self._register_action(action_id, "Set Presence", on_set, writesTo=makeWriterRef(emitter_id))
        self._register_emitter(emitter_id, "presence")

    def _register_button(self, inst, button_id, action_id):
        ik = self._inst_key(inst)

        def on_fire(action, data, _ik=ik, _btn=button_id):
            slot = self._slots.get(_ik)
            if slot is None:
                return
            kind_id = slot["slot"].get("kind")
            handler = self.args.kind_registry.handlers.get(kind_id)
            if handler is not None:
                handler.on_button_pressed(slot["slot"].get("boundInstance", {}), _btn, data)

        self._register_action(action_id, f"Fire {button_id}", on_fire)   # no emitter, no reconcile

    def _reproject(self, ik):
        """Re-render after a value-plane change (cap/presence). Re-run on_apply with the
        FULL current batch for the changed instance's kind — not just that instance. The
        handler's contract is the complete assignment for the kind (e.g. a sequence
        handler sets numBlocks = len(batch)), so every sibling must be re-projected from
        its current bag, ordered by orderIndex."""
        slot = self._slots.get(ik)
        if slot is None:
            return
        kind_id = slot["slot"].get("kind")
        handler = self.args.kind_registry.handlers.get(kind_id)
        if handler is None:
            return
        batch = [
            KindAssignment(
                instance=s["slot"].get("boundInstance", {}),
                caps=dict(s["bag"]),
                presence=s.get("presence"),
                wire_inputs=s["slot"].get("wireInputValues", []),
                order_index=s["slot"].get("orderIndex"),
            )
            for s in self._slots.values()
            if s["slot"].get("kind") == kind_id
        ]
        batch.sort(key=lambda ka: (ka.order_index if ka.order_index is not None else 0))
        ctx = ApplyCtx(self, self._committed.get("generation", 0), None)
        handler.on_apply(ctx, batch)

    def _emit_output(self, inst, channel, value):
        eid = f"{self.id}:output:{inst.get('compElementId')}:{inst.get('instanceTag','')}:{channel}"
        self._register_emitter(eid, channel)
        self._pulse_readback(eid, value)

    # --- low-level register/pulse (sends to server via CLIENT) ---
    def _register_action(self, action_id, name, handler, writesTo=None):
        a = Action(id=action_id, name=name, targetId=self.id, serviceId=self.instance.serviceId,
                   schema=None, handler=handler, writesTo=writesTo)
        CLIENT.saveHandler(action_id, handler)
        CLIENT.actions[action_id] = a
        del a.handler
        CLIENT.set(a)

    def _register_emitter(self, emitter_id, name, provider=None):
        # Default provider reads the last-pulsed value, so RshipExt.seedProperties
        # force-re-pulses every cap/presence/output readback on reconnect (capability #5).
        if provider is None:
            provider = (lambda eid=emitter_id: self._readback_last.get(eid))
        e = Emitter(id=emitter_id, name=name, targetId=self.id, serviceId=self.instance.serviceId,
                    schema=None, changeKey=emitter_id, handler=provider)
        CLIENT.saveEmitterValueProvider(emitter_id, provider)
        del e.handler
        del e.changeKey
        CLIENT.set(e)

    def _pulse_readback(self, emitter_id, value):
        # dedup-pulsed change-gate (capability #5) — for the high-frequency value plane
        if emitter_id in self._readback_last and _values_equivalent(self._readback_last[emitter_id], value):
            return
        self._readback_last[emitter_id] = value
        CLIENT.pulseEmitter(emitter_id, value)

    def _seed_readback(self, emitter_id, value):
        """Force a readback pulse on (re)materialize — NO dedup. A static/default cap
        gets no value-plane SetCap, so this seed is its only readback; it must reach the
        server even if an earlier seed was lost (raced registration / connection blip)."""
        self._readback_last[emitter_id] = value
        CLIENT.pulseEmitter(emitter_id, value)


def _values_equivalent(a, b) -> bool:
    """Same-value early-out. Mirrors BindingValue::equivalent's lossless Int<->Float
    coercion at the scalar level (a JSON 1 and 1.0 are equal), and — going BEYOND the
    server's equivalent() on purpose — also DEEP-coerces inside Color/Vec values
    (list/dict of components). The wire sends whole-number color channels as Int, so a
    {a:1} intent vs a {a:1.0} readback must compare equal or our same-value/dedup gate
    churns the value plane (rship-k1f is the server-side counterpart)."""
    if a is b:
        return True
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return float(a) == float(b)
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_values_equivalent(a[k], b[k]) for k in a)
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(_values_equivalent(x, y) for x, y in zip(a, b))
    return a == b
