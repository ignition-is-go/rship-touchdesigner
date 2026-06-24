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
import tdu

from exec import CLIENT, Action, Emitter, Status, Target, makeWriterRef

# Top-level (NOT lazy) so it resolves in comp_engine's OWN module context. A lazy `import
# par_schema` inside a function resolves relative to the CALLER's op (a base outside rship
# when these reflect-helpers run from an extension), which fails — same trap as `import rship`.
import par_schema


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
    def inputs(self, inputdefs): self._k.inputs.extend(inputdefs); return self
    def singleton(self): self._k.instanceability = Instanceability.SINGLETON; return self
    def instanceability(self, v): self._k.instanceability = v; return self
    def instance_ordering(self, v): self._k.instance_ordering = v; return self
    def instance_capacity(self, c: CapacityConstraint): self._k.instance_capacity = c; return self
    def build(self) -> KindDef: return self._k

# endregion


# region reflection helpers (TD pars <-> caps) — ergonomic primitives for extension devs

def cap_from_par_group(par_group, *, cap_id=None, label=None, prep=PrepClass.IMMEDIATE) -> CapDef:
    """Reflect a TD ParGroup into a SINGLE comp-engine cap, typed from the par style via the
    unified reflector (par_schema): Float->Scalar, Int->Int, Toggle->Bool, RGB/RGBA->Color,
    XYZ->Vec3, Menu->EnumOf(menuNames), Str/File->String. Multi-component styles with no
    well-known type (XY/XYZW/UV/UVW/WH — no Vec2/Vec4) have no single WellKnown cap; the
    SequenceReflector DECOMPOSES those into one scalar cap per component (best UX). If this
    helper meets such a style directly it falls back to a Custom (inline-JSON) schema_ref —
    lossless, generic widget."""
    cap_id = cap_id or par_group.name
    label = label if label is not None else (par_group.label or cap_id)
    # WellKnown if one fits, else a Custom (inline-JSON) ref — both LOSSLESS, never a lossy
    # Scalar collapse. (SequenceReflector decomposes multi-component fields before reaching
    # here; this Custom path only bites a direct call on a no-well-known style.)
    ref = par_schema.schema_ref(par_group) or par_schema.custom_schema_ref(par_group)
    return custom_cap(cap_id, ref, label=label, prep=prep)


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


class WireInput:
    """Marks a sequence block field as filled by WIRE-ROUTING (a comp-engine input)
    instead of a draggable cap. Its value comes from an upstream producer's output channel
    wired in by the operator, resolved LOCALLY on apply/tick (no value travels):

        SequenceReflector(owner, "Sequence", wired={
            "float3": WireInput(accepts_kinds=["seq.source"], channel="value"),
        })

    Wires say WHO feeds the field (topology); per-producer weights, if any, arrive as
    input caps on the value plane. fan_in=True accepts multiple producers (blend yourself)."""
    def __init__(self, accepts_kinds, channel, *, fan_in=False,
                 ordering=InputOrdering.UNORDERED, blend="weighted",
                 required_min=None, capacity=None):
        self.accepts_kinds = list(accepts_kinds)
        self.channel = channel
        self.fan_in = fan_in
        self.ordering = ordering
        self.blend = blend
        self.required_min = required_min
        self.capacity = capacity


class SequenceReflector:
    """Two-way bridge between a TD sequence's block parameters and comp-engine caps/inputs.

    Reflects each block field into a cap (typed from the TD par style) for the kind
    declaration, and writes values back into a placed block's parameters on apply:

        refl = comp_engine.SequenceReflector(ownerComp, "Sequence",
                                             wired={"float3": WireInput(["seq.source"], "value")})
        kind = (KindDefBuilder("seq.block", "Block", "CompElementClipPayload")
                .instanceability(Instanceability.INSTANCEABLE)
                .instance_ordering(InputOrdering.ORDERED)
                .caps(refl.caps())        # non-wired fields -> draggable caps
                .build())
        for i in refl.inputs():           # wired fields -> comp-engine inputs
            kind ... (KindDefBuilder.input(i))   # see _build below
        ...
        def on_apply(self, ctx, batch):
            refl.render(batch)            # caps from cap values; wired fields from resolved upstream output

    Mark a field wired via `wired={field: WireInput(...)}`; everything else reflects as a
    cap. Call refresh() (or rebuild) after editing the block's parameters in TD."""
    def __init__(self, owner, sequence_name, wired=None, length_par=None):
        self.owner = owner
        self.sequence_name = sequence_name
        self._wired_spec = dict(wired or {})
        # Auto par holding the TRUE placed count (see render). Derived from the sequence name
        # so it's UNIQUE per sequence — a base may host several engines (several sequences),
        # and TD requires custom par names to be unique on a COMP. Note: TD custom par names
        # must be uppercase-first then lowercase/digits only, so the suffix is lowercase.
        self._length_name = length_par or f"{sequence_name}length"
        self._block_index = {}              # inst_key -> block index, for trigger fire routing
        self.refresh()
        self._ensure_length_par()

    @property
    def sequence(self):
        return self.owner.seq[self.sequence_name]

    def _ensure_length_par(self):
        """A TD sequence must have >= 1 block, so numBlocks can't represent an empty (or
        N-element) comp-engine stack faithfully. Expose a read-only Int par holding the TRUE
        placed count (0..N); downstream logic reads THIS, not numBlocks. Created next to the
        sequence (idempotent)."""
        if not self._length_name:
            return None
        # tolerant lookup — TD may canonicalize the par name's casing on creation
        p = self.owner.par[self._length_name] or next(
            (q for q in self.owner.customPars if q.name.lower() == self._length_name.lower()), None)
        if p is None:
            seq = self.sequence
            page = None
            try:
                sp = seq.sequencePar
                page = sp.page if sp is not None else None
            except Exception:
                page = None
            if page is None:
                page = next((pg for pg in self.owner.customPages if pg.name == "Comp Engine"), None) \
                    or self.owner.appendCustomPage("Comp Engine")
            pg = page.appendInt(self._length_name, label=f"{self.sequence_name} Length")
            p = self.owner.par[self._length_name] or (pg[0] if pg is not None else None)
            try:
                p.readOnly = True           # engine-driven, not hand-edited
            except Exception:
                pass
        if p is not None:
            self._length_name = p.name      # cache the actual (canonical) name
        return p

    def refresh(self):
        """(Re)reflect block-0 template fields into wired-input, trigger, or cap descriptors."""
        prefix = f"{self.sequence_name}0"
        self._cap_fields = []
        self._wire_fields = []
        self._trigger_fields = []
        for pg in self.sequence.blockParGroups:
            if not pg.name.startswith(prefix):
                continue
            field = pg.name[len(prefix):]                       # e.g. "float3"
            suffixes = [m.name[len(prefix):] for m in pg]       # e.g. ["float2r","float2g",...]
            spec = self._wired_spec.get(field)
            if spec is not None:
                self._wire_fields.append({
                    "pin_id": field, "suffixes": suffixes, "spec": spec,
                    "input": InputDef(id=field, display_name=(pg.label or field),
                                      accepts_kinds=spec.accepts_kinds, accepts_channel=spec.channel,
                                      fan_in=spec.fan_in, ordering=spec.ordering, blend=spec.blend,
                                      required_min=spec.required_min, capacity=spec.capacity),
                })
            elif par_schema.is_trigger(pg):
                # Pulse/Momentary is a FIRE input, not a value -> a comp-engine trigger (fire
                # button) that pulses the block par on press (see fire()). NOT a cap.
                self._trigger_fields.append({
                    "field": field,
                    "trigger": TriggerDef(id=field, display_name=(pg.label or field)),
                })
            elif par_schema.schema_ref(pg) is None and len(suffixes) > 1:
                # Multi-component field with no well-known type (XY/XYZW/UV/UVW/WH — no
                # Vec2/Vec4) has no single-cap representation (cap schema_ref is WellKnown-
                # only). DECOMPOSE into one typed scalar cap per component — lossless, and
                # each component gets a proper slider. (Petition Vec2/Vec4 to recombine.)
                comp = "Int" if pg.style == "WH" else "Scalar"
                for m, suf in zip(pg, suffixes):
                    self._cap_fields.append({
                        "cap_id": suf, "suffixes": [suf],
                        "cap": custom_cap(suf, schema(comp), label=(m.label or suf)),
                    })
            else:
                self._cap_fields.append({
                    "cap_id": field, "suffixes": suffixes,
                    "cap": cap_from_par_group(pg, cap_id=field),
                })
        return self

    def caps(self) -> list:
        return [f["cap"] for f in self._cap_fields]

    def inputs(self) -> list:
        return [f["input"] for f in self._wire_fields]

    def triggers(self) -> list:
        return [f["trigger"] for f in self._trigger_fields]

    def fire(self, instance, field):
        """A trigger fired (button_id == field): pulse the matching par on the block that
        currently holds `instance`. No-op if the instance isn't placed or field isn't a par."""
        key = (instance.get("compElementId"), instance.get("instanceTag", ""))
        i = self._block_index.get(key)
        if i is None:
            return
        p = self.owner.par[f"{self.sequence_name}{i}{field}"]
        if p is not None:
            p.pulse()

    def render(self, batch):
        """Materialize an ordered batch as sequence blocks: cap fields from cap values,
        wired fields from the resolved upstream producer output."""
        ordered = sorted(batch, key=lambda ka: (ka.order_index if ka.order_index is not None else 0))
        n = len(ordered)
        # block index per instance, so a fired trigger can pulse the right block's par (fire())
        self._block_index = {(ka.instance.get("compElementId"), ka.instance.get("instanceTag", "")): i
                             for i, ka in enumerate(ordered)}
        # Publish the TRUE placed count (0..N) on the stack-length par. TD can't have 0 blocks,
        # so numBlocks is clamped to >=1 (a placeholder block when empty) — downstream reads
        # the length par, not numBlocks.
        lp = self._ensure_length_par()
        if lp is not None and lp.eval() != n:
            lp.val = n
        blocks = max(1, n)
        if self.sequence.numBlocks != blocks:              # only resize on actual change (avoid block churn)
            self.sequence.numBlocks = blocks
        for i, ka in enumerate(ordered):
            for f in self._cap_fields:
                self._write_field(i, f["suffixes"], ka.caps.get(f["cap_id"]))
            for f in self._wire_fields:
                self._bind_wire(i, f, ka.wire_inputs)
        return ordered      # block-ordered batch, so a producer can map block index -> instance

    def _blend(self, values, spec):
        """Combine resolved fan-in values for one pin. Single source -> its value. Default
        fan-in -> mean of present numeric values; override per kind for richer blends.
        (Blend is advisory metadata; the executor composites — per the wire protocol.)"""
        vals = [v for v in values if v is not None]
        if not vals:
            return None
        if len(vals) == 1 or not spec.fan_in:
            return vals[0]
        if all(isinstance(v, (int, float)) for v in vals):
            return sum(vals) / len(vals)
        return vals[-1]

    def _write_field(self, i, suffixes, v):
        if v is None:
            return
        if len(suffixes) > 1:                                   # Color/Vec -> spread components
            for suf, c in zip(suffixes, _components(v, len(suffixes))):
                self._set(f"{self.sequence_name}{i}{suf}", c)
        else:
            self._set(f"{self.sequence_name}{i}{suffixes[0]}", v)

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

    def _bind_wire(self, i, f, wire_inputs):
        """Bind a wire-fed field's par to its producer(s)' LIVE output via a TD expression
        (resolve_ref). TD evaluates it every frame — it reads the source output channel's
        actual current value, nothing fabricated — and we only (re)set the expression on
        apply/topology change, never per frame. Single-par fields; unbound -> constant."""
        sufs = f["suffixes"]
        refs = [e.get("source") for e in (wire_inputs or [])
                if e.get("pinId") == f["pin_id"] and e.get("source")]
        if not refs or len(sufs) != 1:
            for suf in sufs:                                    # unbound (or multi-component) -> constant
                self._set_constant(f"{self.sequence_name}{i}{suf}")
            return
        par_name = f"{self.sequence_name}{i}{sufs[0]}"
        exprs = [b for b in (resolve_binding(r) for r in refs) if b]
        if not exprs:                                           # producer(s) not registered yet
            self._set_constant(par_name)
            return
        expr = exprs[0] if len(exprs) == 1 else "(" + " + ".join(f"({e} or 0)" for e in exprs) + ")"
        self._set_expr(par_name, expr)

    def _set_expr(self, par_name, expr):
        p = self.owner.par[par_name]
        if p is None:
            return
        p.expr = expr                                           # setting .expr auto-enters EXPRESSION mode
        p.mode = ParMode.EXPRESSION

    def _set_constant(self, par_name):
        p = self.owner.par[par_name]
        if p is not None and p.mode != ParMode.CONSTANT:
            p.mode = ParMode.CONSTANT

# endregion


# region handler interface

@dataclasses.dataclass
class KindAssignment:
    """One placed instance handed to a kind's on_apply."""
    instance: dict          # {"compElementId":.., "instanceTag":..}
    caps: dict              # {cap_id: value}  (current value-plane bag)
    presence: float
    wire_inputs: list       # [WireInputEntry] raw {pinId, source: CrossEngineRef}
    order_index: int | None = None
    # Resolved wire inputs, grouped by pin, in fan-in (wireInputValues) order — the
    # framework resolves each CrossEngineRef against the local output registry before
    # on_apply. {pinId: [value, ...]}. Empty for an unbound pin.
    resolved_inputs: dict = dataclasses.field(default_factory=dict)

    def inputs(self, pin_id) -> list:
        """All resolved values wired into `pin_id`, in fan-in order (blend yourself)."""
        return self.resolved_inputs.get(pin_id, [])

    def input1(self, pin_id, default=None):
        """First resolved value for a single-source input (default if unbound/cleared)."""
        vals = self.resolved_inputs.get(pin_id, [])
        return vals[0] if vals and vals[0] is not None else default


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

    def resolve(self, ref):
        """Resolve a single CrossEngineRef to its producer's current output (local
        registry); None if unresolved. Usually you read ka.inputs(pin)/input1(pin)
        instead — the framework pre-resolves wire inputs before on_apply."""
        return resolve_ref(ref)

    def bind_output(self, instance: dict, channel: str, expr: str):
        """Expose this instance's output as a TD reference EXPRESSION (e.g. the par that
        holds its value, "me.par.Source0value") for native par-to-par binding: a wired
        consumer binds its par directly to it, so TD's cook graph tracks the producer par."""
        register_output_expr(self.engine.id, instance, channel, expr)



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


def prune_dead_engines() -> list:
    """Remove engines whose owner COMP was deleted from the registry, returning them so the
    caller can mark their Target OFFLINE (a deleted base otherwise re-publishes its engine
    as online every connect — same td-anchored-registry staleness as rship targets)."""
    out = []
    for key, eng in list(_engines().items()):
        try:
            alive = eng.ownerComp is not None and eng.ownerComp.valid
        except Exception:
            alive = False
        if not alive:
            out.append(eng)
            del _engines()[key]
    return out


# --- cross-engine output registry: a producer registers a placed instance's current
# output value here; a consumer resolves CrossEngineRefs against it LOCALLY (no value
# travels over wires — comp-engine-wire-protocol §7-§11). td-anchored so resolve works
# across module epochs and across every engine in this process (refs are same-process in v1).
def _outputs() -> dict:
    o = getattr(td, "_rship_outputs", None)
    if o is None:
        o = {}
        td._rship_outputs = o
    return o


def _output_key(engine_id, instance, channel) -> tuple:
    # instance None => engine-level (singleton/aggregator) ref; else element-level.
    if instance is None:
        return (engine_id, None, channel)
    return (engine_id, (instance.get("compElementId"), instance.get("instanceTag", "")), channel)


def register_output(engine_id, instance, channel, value):
    """Expose a producer instance's current output VALUE for cross-engine resolve. Stored in a
    tdu.Dependency so a bound consumer par EXPRESSION participates in TD's cook/dependency
    system: reading dep.val in the expression registers the dependency, and setting it here
    marks those expressions dirty -> TD re-cooks them. (A plain dict is invisible to TD's
    change detection, so the consumer would NOT update when the producer's value changes.)"""
    key = _output_key(engine_id, instance, channel)
    o = _outputs()
    dep = o.get(key)
    if dep is None:
        o[key] = tdu.Dependency(value)
    elif dep.val != value:
        dep.val = value     # marks dependent expressions dirty -> re-cook


def resolve_ref(ref) -> typing.Any:
    """Resolve a CrossEngineRef to the producer's current output VALUE. Reading the
    tdu.Dependency's .val here — when called from inside a consumer's par expression —
    registers a TD dependency, so the expression re-cooks when the producer emits a new
    value. None if unresolved or if the producer exposed a reference instead of a value."""
    if not ref:
        return None
    entry = _outputs().get(_output_key(
        ref.get("sourceEngineId"), ref.get("sourceInstance"), ref.get("outputChannelId")))
    return entry.val if isinstance(entry, tdu.Dependency) else None


class OutputExpr:
    """Marks a producer output as living at a TD parameter/op the consumer can reference
    DIRECTLY. `expr` is a real TD reference (e.g. a sequence block par, "me.par.Source0value"),
    NOT a fabricated signal — so binding a consumer par to it is native par-to-par: TD's cook
    graph tracks the producer par with no tdu.Dependency bridge needed."""
    __slots__ = ("expr",)

    def __init__(self, expr):
        self.expr = str(expr)

    def __eq__(self, other):
        return isinstance(other, OutputExpr) and other.expr == self.expr

    def __repr__(self):
        return f"OutputExpr({self.expr!r})"


_reprojecting = {"active": False}


def register_output_expr(engine_id, instance, channel, expr):
    """Expose a producer instance's output as a TD reference EXPRESSION (e.g. the par that
    holds its value) for native par-to-par binding. If the reference CHANGED (e.g. the
    producer reordered to a new block index, so its value now lives at a different par),
    re-project wire-driven consumers so they re-bind to the new reference. Reference changes
    are topology-rare (reorder/placement), so this never runs per frame."""
    key = _output_key(engine_id, instance, channel)
    o = _outputs()
    new = OutputExpr(expr)
    if o.get(key) == new:
        return
    o[key] = new
    if _reprojecting["active"]:
        return
    _reprojecting["active"] = True
    try:
        for eng in get_engines():
            eng.tick()
    finally:
        _reprojecting["active"] = False


def resolve_binding(ref) -> typing.Optional[str]:
    """The par expression a wired consumer should bind to. If the producer exposed a TD
    reference (register_output_expr / ctx.bind_output) -> that reference directly (par-to-par,
    natively cook-tracked). Otherwise -> a resolve_ref() call reading the tdu.Dependency-backed
    value. None if the producer isn't registered yet (consumer falls back to a constant)."""
    entry = _outputs().get(_output_key(
        ref.get("sourceEngineId"), ref.get("sourceInstance"), ref.get("outputChannelId")))
    if entry is None:
        return None
    # None-safe: a producer momentarily missing (mid re-solve / teardown) resolves to 0
    # rather than erroring a numeric par (the "missing -> treat as clear" rule).
    if isinstance(entry, OutputExpr):
        return f"({entry.expr} or 0)"
    return f"(op.RSHIP.CompEngine.resolve_ref({ref!r}) or 0)"

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
    # reuse rship's dirty flag so RshipExt re-publishes. Use op.RSHIP.Api (global) rather
    # than `import rship`, which only resolves for DATs inside the rship comp.
    try:
        op.RSHIP.Api._mark_dirty()
    except Exception:
        pass
    return proxy


def _engine_slug(name: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in str(name).lower()).strip("-") or "engine"


def _field_schema(refl, sequence, field):
    """Schema for a sequence field's output channel — WellKnown if one fits, else a Custom
    (inline-JSON) ref; both lossless, never a lossy Scalar collapse. None if the field is
    missing (a misconfigured output — surfaces rather than masks)."""
    pg = next((p for p in refl.sequence.blockParGroups if p.name == f"{sequence}0{field}"), None)
    return (par_schema.schema_ref(pg) or par_schema.custom_schema_ref(pg)) if pg is not None else None


def sequence_manager(ownerComp, *, kind, engine_name, sequence="Sequence", short_id=None,
                     kind_label=None, wired=None, outputs=None, host=None, length_par=None,
                     payload="CompElementClipPayload", ordered=True):
    """Declare a SEQUENCE MANAGER: a comp engine backed by a TD sequence — the whole ceremony
    in one call.

    Reflects the sequence block's fields to caps (or to wired INPUTS via
    wired={field: WireInput(...)}); each placed element renders into a block; and a PRODUCER
    exposes block fields as output channels via outputs={channelId: fieldBase} (bound as
    own-op-path par references, for cross-op par-to-par). Returns (reflector, engine).

    Defaults: kind_label = kind.title(); host = an rship target named engine_name;
    short_id = '<engine_name>-engine' (slugged); INSTANCEABLE + ORDERED."""
    refl = SequenceReflector(ownerComp, sequence, wired=wired, length_par=length_par)
    outs = dict(outputs or {})

    class _Handler(KindHandler):
        def on_apply(self, ctx, batch):
            ordered_batch = refl.render(batch)                 # render caps + wired fields
            for chan, field in outs.items():                   # producer: expose block fields as outputs
                for i, ka in enumerate(ordered_batch):
                    ctx.bind_output(ka.instance, chan,
                                    f"op({ownerComp.path!r}).par.{sequence}{i}{field}")

        def on_button_pressed(self, instance, button_id, data):
            refl.fire(instance, button_id)                     # trigger (Pulse field) -> pulse the block par

    builder = (KindDefBuilder(kind, kind_label or kind.title(), payload)
               .instanceability(Instanceability.INSTANCEABLE)
               .caps(refl.caps()))
    if ordered:
        builder.instance_ordering(InputOrdering.ORDERED)
    if refl.inputs():
        builder.inputs(refl.inputs())
    for t in refl.triggers():
        builder.trigger(t)
    for chan, field in outs.items():
        builder.output_channel(OutputChannelDef(chan, chan.title(),
                                                _field_schema(refl, sequence, field), "signal"))
    reg = KindRegistryBuilder().register_with_handler(builder.build(), _Handler()).build()

    if host is None:
        # op.RSHIP.Api (global) — NOT `import rship`, which only resolves for DATs inside
        # the rship comp; sequence_manager is called from arbitrary bases.
        host = op.RSHIP.Api.target(ownerComp, engine_name)
    engine = comp_engine(ownerComp, CompEngineArgs(
        short_id=short_id or f"{_engine_slug(engine_name)}-engine",
        display_name=engine_name, kind_registry=reg, host_target=host))
    return refl, engine


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

    def offline(self):
        """Mark this engine's Target offline (e.g. its owner base was deleted)."""
        if self.instance is not None:
            CLIENT.setTargetStatus(self.id, self.instance.id, Status.Offline)

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
        op.RS_LOG.Info(f"[CompEngine] {self.id} INBOUND apply gen={assignment.get('generation')} "
                       f"slots={len(assignment.get('slotStates', []))}")
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
    def _inst_key(self, inst: dict) -> tuple:
        return (inst.get("compElementId"), inst.get("instanceTag", ""))

    def _resolve_inputs(self, wire_inputs) -> dict:
        """Group wireInputValues by pin and resolve each CrossEngineRef LOCALLY, in the
        server's pre-sorted fan-in order. {pinId: [value, ...]}; None where a producer's
        resource is momentarily missing (treat as clear — self-heals next tick)."""
        out: typing.Dict[str, list] = {}
        for entry in wire_inputs or []:
            out.setdefault(entry.get("pinId"), []).append(resolve_ref(entry.get("source", {})))
        return out

    def _ka_for_slot(self, s) -> KindAssignment:
        slot = s["slot"]
        return KindAssignment(
            instance=slot.get("boundInstance", {}),
            caps=dict(s["bag"]),
            presence=s.get("presence"),
            wire_inputs=slot.get("wireInputValues", []),
            order_index=slot.get("orderIndex"),
            resolved_inputs=self._resolve_inputs(slot.get("wireInputValues", [])),
        )

    def _batch_for_kind(self, kind_id) -> list:
        """The full current batch for a kind (handler's contract is the COMPLETE
        assignment), ordered by the kind's own orderIndex. Note: a producer's own
        orderIndex is its z-order; fan-in blend order lives in each consumer's
        resolved_inputs sequence, not here."""
        batch = [self._ka_for_slot(s) for s in self._slots.values()
                 if s["slot"].get("kind") == kind_id]
        batch.sort(key=lambda ka: (ka.order_index if ka.order_index is not None else 0))
        return batch

    def _project_kind(self, kind_id, transaction_id=None):
        handler = self.args.kind_registry.handlers.get(kind_id)
        if handler is None:
            return
        ctx = ApplyCtx(self, self._committed.get("generation", 0), transaction_id)
        handler.on_apply(ctx, self._batch_for_kind(kind_id))

    def _render(self, assignment, transaction_id):
        # Register every per-instance entity VERBATIM from the envelope ids and seed the
        # value-plane bag (caps = Properties), then project each kind from its full batch.
        prev_kinds = {s["slot"].get("kind") for s in self._slots.values()}   # for teardown of vacated kinds
        new_slots: typing.Dict[tuple, dict] = {}
        for slot in assignment.get("slotStates", []):
            inst = slot.get("boundInstance", {})
            ik = self._inst_key(inst)
            bag = {}
            for cv in slot.get("capValues", []):
                self._register_cap(inst, cv["capId"], cv["actionId"], cv["emitterId"])
                bag[cv["capId"]] = cv.get("value")
                # Forced seed-on-materialize (don't dedup): a static/default cap gets no
                # value-plane SetCap, so this is its only readback; a lost optimistic seed
                # would never re-fire. (See _seed_readback.)
                self._seed_readback(cv["emitterId"], cv.get("value"))
            if slot.get("presenceActionId"):
                self._register_presence(inst, slot["presenceActionId"], slot["presenceEmitterId"])
            for ba in slot.get("buttonActions", []) or []:
                self._register_button(inst, ba["buttonId"], ba["actionId"])
            new_slots[ik] = {"slot": slot, "bag": bag, "presence": None}
        self._slots = new_slots

        # Persistent slot map => intra-apply slot order doesn't matter, but to resolve
        # wires within the SAME apply we project PRODUCER kinds (those with output
        # channels) first so their outputs are registered before consumers resolve. (A
        # straggler still self-heals on the next per-tick re-projection.)
        reg = self.args.kind_registry
        # Project the UNION of previously- and currently-present kinds: a kind whose instances
        # ALL vacated (including an empty apply -> no kinds present) must still be projected so
        # its handler runs with an EMPTY batch and tears down its TD representation (e.g. the
        # SequenceReflector collapses to numBlocks=1 / length 0). Without this a 2->0 apply
        # leaves the kind's last render stale.
        kinds = {s["slot"].get("kind") for s in self._slots.values()} | prev_kinds
        for kind_id in sorted(kinds, key=lambda k: 0 if (reg.get(k) and reg.get(k).output_channels) else 1):
            self._project_kind(kind_id, transaction_id)

    def tick(self):
        """Per-tick re-projection of WIRE-DRIVEN instances only: an upstream producer's
        output changes WITHOUT a re-apply (topology unchanged), so re-resolve refs +
        re-project every tick. Cap-only instances aren't ticked — they re-project on
        SetCap/apply. No wire-driven slots => no-op (cheap)."""
        kinds = {s["slot"].get("kind") for s in self._slots.values()
                 if s["slot"].get("wireInputValues")}
        for kind_id in kinds:
            self._project_kind(kind_id)

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
        """Re-project on a value-plane change (cap/presence) — re-run on_apply with the
        FULL kind batch (the handler's contract is the complete assignment for the kind,
        e.g. a sequence handler sets numBlocks = len(batch)), not just the changed slot."""
        s = self._slots.get(ik)
        if s is not None:
            self._project_kind(s["slot"].get("kind"))

    def _emit_output(self, inst, channel, value):
        eid = f"{self.id}:output:{inst.get('compElementId')}:{inst.get('instanceTag','')}:{channel}"
        self._register_emitter(eid, channel)
        # consumption path: expose this instance's current output for cross-engine resolve
        # (local registry; no value travels over the wire). Engine-level (singleton)
        # producers register under instance=None — pass None as inst there.
        register_output(self.id, inst, channel, value)
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
