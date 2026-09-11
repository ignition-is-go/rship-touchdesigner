"""
comp_engine — Python port of the rship comp-engine executor SDK.

Comp engine = server-authoritative dynamic placement/topology. You declare element
KINDS once; native required-state rows describe which instances must be placed,
ordered, wired, and animated. You never author placement/merge/order/capacity.

Two planes:
  - TOPOLOGY  — Element rows describe which instances exist, their kind, wiring,
    and order. Structural changes render coherent assignments.
  - VALUE     — Cap and Presence rows update applied instances without rebuilding
    topology.

Strictly opt-in: declare no kinds and you simply aren't a comp engine.

This mirrors libs/sdk/rs/src/comp_engine/ (KindDefBuilder / KindRegistryBuilder /
KindHandler / CompEngineProxy). See memory rship-comp-engine for the full spec/casing.

The native wire contract is pinned to rship b8a2739dd4.
"""
import dataclasses
import math
import typing

import td
import tdu

from exec import CLIENT, Emitter, Status, Target

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
    # reflect the par's DEFAULT alongside its schema so the server seeds newly-placed instances
    # with the TD-authored defaults (not null).
    return custom_cap(cap_id, ref, default=par_schema.read_default(par_group), label=label, prep=prep)


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
        key = instance.get("compElementId")
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
        self._block_index = {ka.instance.get("compElementId"): i
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
    instance: dict          # {"compElementId":..}
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
    wants_tick = True   # set False when the handler renders ONLY from topology + the value plane
                        # (no dynamic wire VALUES to re-resolve per frame) — tick() then skips it,
                        # avoiding a wasteful per-tick rebuild of an identical render.
    def on_apply(self, ctx: ApplyCtx, batch: list):
        raise NotImplementedError("KindHandler.on_apply must be implemented")

    def on_prepare(self, ctx: ApplyCtx, batch: list):
        return PrepReport.ready()

    def on_cancel(self, ctx: ApplyCtx):
        pass

    def on_button_pressed(self, instance: dict, button_id: str, data):
        pass

    def on_value(self, ctx: ApplyCtx, instance: dict, kind_id: str, change: dict):
        """A SINGLE instance's value plane changed (presence or one cap) — topology UNCHANGED.
        Default re-runs the full holistic on_apply (correct but O(kind batch) — re-walks/rewrites
        everything). OVERRIDE to update just this instance's render for an O(1) value update (the
        common per-frame animation path). change = {"what": "presence"|"cap", "cap_id": <id|None>,
        "value": <new value>}."""
        self.on_apply(ctx, ctx.engine._batch_for_kind(kind_id))

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
    engines = list(_engines().values())
    for engine in engines:
        engine.__class__ = CompEngineProxy
    return engines


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
    return (engine_id, instance.get("compElementId"), channel)


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


def _output_emitter_id(engine_id, instance, channel):
    return f"{engine_id}:output:{instance.get('compElementId')}::{channel}"


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
    """The engine declaration and local materialization runtime."""

    def __init__(self, ownerComp, args: CompEngineArgs, key: str):
        self.instance = None            # injected by RshipExt before publish()
        self.ownerComp = ownerComp
        self.args = args
        self.key = key
        # Last locally applied assignment; used by existing handler contexts.
        self._committed = {"slotStates": [], "overflow": [], "generation": 0}
        # Current rendered slots, keyed by binding-node compElementId.
        # Holds {"slot": <slotState>, "state": <ref into _inst_state>} — rebuilt every apply.
        self._slots: typing.Dict[tuple, dict] = {}
        # PERSISTENT per-instance value-plane state (caps + presence), keyed by the SAME instance id
        # and OWNED here independent of topology. The apply payload carries no presence value and
        # the server sends cap/presence updates only on CHANGE, so the executor is the authority for
        # "current value per instance". A topology apply re-binds this onto the current slots (see
        # _render) so values SURVIVE an unrelated re-apply instead of resetting to None/disabled.
        self._inst_state: typing.Dict[tuple, dict] = {}          # ik -> {"bag": {capId: val}, "presence": val}
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

    # --- publish ---
    def publish(self, online=True, seed=True):
        """Publish the engine target and native required-state declaration."""
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
        if online:
            CLIENT.setTargetStatus(eid, self.instance.id, Status.Online)
        # DAT reloads preserve CLIENT, so explicitly remove the superseded protocol.
        for suffix in ('prep_report', 'committed_state', 'apply', 'prepare', 'cancel', 'request_state'):
            legacy_id = self._rid(suffix)
            CLIENT.actions.pop(legacy_id, None)
            CLIENT.handlers.pop(legacy_id, None)
            CLIENT.emitterValueProviders.pop(legacy_id, None)
        for slot_state in self._slots.values():
            slot = slot_state.get('slot', {})
            action_ids = [cv.get('actionId') for cv in slot.get('capValues', [])]
            action_ids += [slot.get('presenceActionId')]
            action_ids += [button.get('actionId') for button in slot.get('buttonActions', [])]
            emitter_ids = [cv.get('emitterId') for cv in slot.get('capValues', [])]
            emitter_ids += [slot.get('presenceEmitterId')]
            for action_id in filter(None, action_ids):
                CLIENT.actions.pop(action_id, None)
                CLIENT.handlers.pop(action_id, None)
            for emitter_id in filter(None, emitter_ids):
                CLIENT.emitterValueProviders.pop(emitter_id, None)
        CLIENT.sendEvent(CLIENT.buildSetEvent(self._engine_entity(), itemType="CompEngine"))

    def _engine_entity(self) -> dict:
        eid = self.id
        return {
            "id": eid,                                  # same string as engineTargetId
            "serviceId": self.instance.serviceId,
            "engineTargetId": eid,
            "hostTargetId": self._host_id(),
            "displayName": self.args.display_name,
            "kindRegistry": self.args.kind_registry.to_wire(),
            "outputs": [],
        }

    # --- render pipeline ---
    def _inst_key(self, inst: dict) -> tuple:
        return inst.get("compElementId")

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
        st = s["state"]
        return KindAssignment(
            instance=slot.get("boundInstance", {}),
            caps=dict(st["bag"]),
            presence=st.get("presence"),
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
            # Value state is OWNED per-instance and persists across applies; topology just re-binds
            # it to the current slot. Re-register the value-plane actions/emitters (their ids may be
            # re-issued per apply) but OVERLAY values rather than wiping — exactly how caps already
            # behave, so presence and caps stay consistent.
            state = self._inst_state.setdefault(ik, {"bag": {}, "presence": None})
            state["bag"] = {}
            for cv in slot.get("capValues", []):
                state["bag"][cv["capId"]] = cv.get("value")
            # Presence, treated like a cap: if the apply SEEDS a value (server-side resting presence —
            # contract C, a "presence" value on the slot) overlay it (level-triggered, authoritative);
            # otherwise CARRY FORWARD the last-known value. Today's apply is presence-less (edge-
            # triggered via SetPresence only), so the carry-forward keeps a persisting slot from
            # resetting to None/dark when an UNRELATED topology change triggers a re-apply.
            pv = slot.get("presence")
            state["presence"] = pv
            new_slots[ik] = {"slot": slot, "state": state}
        self._slots = new_slots
        # PRUNE value-state for instances no longer in the topology. Now that contract C re-seeds
        # caps+presence on every apply, a re-placed instance is repopulated from the apply, so we
        # needn't retain vacated instances — keeping them leaks _inst_state across scene changes and
        # holds stale presence. Still-placed instances are in new_slots, so their carry-forward is
        # untouched; only genuinely-vacated keys are dropped.
        for _ik in list(self._inst_state.keys()):
            if _ik not in new_slots:
                del self._inst_state[_ik]

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
        SetCap/apply. Handlers with wants_tick=False (render from static topology + the
        value plane, no dynamic wire values) are skipped — re-projecting them every tick
        would just rebuild the same render. No wire-driven slots => no-op (cheap)."""
        kinds = {s["slot"].get("kind") for s in self._slots.values()
                 if s["slot"].get("wireInputValues")}
        for kind_id in kinds:
            handler = self.args.kind_registry.handlers.get(kind_id)
            if handler is not None and not getattr(handler, "wants_tick", True):
                continue
            self._project_kind(kind_id)

    def _reproject(self, ik, change=None):
        """Re-render ONE instance on a value-plane change (cap/presence) — topology is UNCHANGED,
        so route to the handler's on_value, which can update just the changed block (O(1)) instead
        of re-walking + rewriting the whole kind. Default on_value falls back to a full on_apply,
        so handlers that don't optimize keep the old holistic behavior. No-op if unplaced."""
        s = self._slots.get(ik)
        if s is None:
            return
        kind_id = s["slot"].get("kind")
        handler = self.args.kind_registry.handlers.get(kind_id)
        if handler is None:
            return
        ctx = ApplyCtx(self, self._committed.get("generation", 0), None)
        handler.on_value(ctx, s["slot"].get("boundInstance", {}), kind_id, change or {})

    def _emit_output(self, inst, channel, value):
        eid = _output_emitter_id(self.id, inst, channel)
        self._register_emitter(eid, channel)
        # consumption path: expose this instance's current output for cross-engine resolve
        # (local registry; no value travels over the wire). Engine-level (singleton)
        # producers register under instance=None — pass None as inst there.
        register_output(self.id, inst, channel, value)
        self._pulse_readback(eid, value)

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


def _byte_len(value):
    return len(str(value).encode('utf-8'))


def _required_key_id(key):
    kind = key.get('rowKind')
    fields = [key.get('engineId'), (key.get('element') or {}).get('compElementId')]
    if kind == 'cap':
        fields.append(key.get('capId'))
    elif kind == 'dependency':
        fields.extend([
            key.get('sourceEngineId'),
            (key.get('sourceElement') or {}).get('compElementId'),
        ])
    if kind not in ('element', 'cap', 'presence', 'dependency') or any(not isinstance(v, str) for v in fields):
        raise ValueError('Invalid required comp-engine key')
    return kind + ':' + ''.join(f'{_byte_len(v)}:{v}' for v in fields)


class RequiredCompEngineController:
    def __init__(self):
        self.client = None
        self.instance = None
        self.engines = {}
        self.view = None
        self.desired = {}
        self.recent_events = []

    def replace_engines(self, client, instance, engines):
        self.client = client
        self.instance = instance
        self.engines = {engine.id: engine for engine in engines}

    def view_changed(self, view, change):
        self.view = view
        if not view.ready:
            return
        try:
            desired, dependencies = self._parse(view.rows.values())
        except Exception as error:
            op.RS_LOG.Error(f'[comp_engine]: invalid required-state view: {error}')
            return
        desired = self._eligible(desired, dependencies)
        old = self.desired
        self.desired = desired
        for engine_id, engine in self.engines.items():
            before = {k: v for k, v in old.items() if k[0] == engine_id}
            after = {k: v for k, v in desired.items() if k[0] == engine_id}
            if self._structures(before) != self._structures(after):
                self._render_engine(engine, before, after)
            else:
                self._apply_value_changes(engine, before, after)
                if change.reset:
                    for key, item in after.items():
                        self._observe_components(key, item)
                        self._observe_element(key, 'ready', None, item['value'])

    def _parse(self, rows):
        elements = {}
        components = []
        dependencies = {}
        seen_keys = set()
        for row in rows:
            key = row.get('key') or {}
            value = row.get('value') or {}
            kind = key.get('rowKind')
            if kind != value.get('rowKind') or row.get('id') != _required_key_id(key):
                raise ValueError(f"row {row.get('id')} has inconsistent key/value/id")
            key_id = _required_key_id(key)
            if key_id in seen_keys:
                raise ValueError(f'duplicate required key {key_id}')
            seen_keys.add(key_id)
            element_id = (key.get('element') or {}).get('compElementId')
            ek = (key.get('engineId'), element_id)
            if kind == 'element':
                elements[ek] = {
                    'row': row,
                    'value': dict(value),
                    'caps': {},
                    'presence': None,
                }
            elif kind == 'dependency':
                source = (key.get('sourceEngineId'), (key.get('sourceElement') or {}).get('compElementId'))
                dependencies[(ek, source)] = bool(value.get('ready'))
            else:
                components.append((kind, ek, key, value))
        for kind, ek, key, value in components:
            item = elements.get(ek)
            if item is None:
                raise ValueError(f'{kind} row has no Element row')
            if item['value'].get('singleton') and kind in ('cap', 'presence'):
                raise ValueError(f'{kind} row cannot target a singleton element')
            if kind == 'cap':
                cap_id = key.get('capId')
                if cap_id not in item['value'].get('caps', []):
                    raise ValueError(f'undeclared cap {cap_id}')
                item['caps'][cap_id] = value.get('value')
            elif kind == 'presence':
                weight = value.get('weight')
                if (not isinstance(weight, (int, float)) or isinstance(weight, bool)
                        or not math.isfinite(weight) or not 0 <= weight <= 1):
                    raise ValueError('presence must be between zero and one')
                item['presence'] = float(weight)
        for (consumer, source), _ready in dependencies.items():
            item = elements.get(consumer)
            if item is None:
                raise ValueError('dependency row has no Element row')
            declared = any(
                (wire.get('source') or {}).get('sourceEngineId') == source[0]
                and ((wire.get('source') or {}).get('sourceInstance') or {}).get('compElementId') == source[1]
                for wire in item['value'].get('wireInputs', [])
            )
            if not declared:
                raise ValueError('dependency row is not declared by an Element wire')
        return elements, dependencies

    def _eligible(self, desired, dependencies):
        local_ids = set(self.engines)
        eligible = {}
        for ek, item in desired.items():
            if ek[0] not in local_ids:
                continue
            ok = True
            for wire in item['value'].get('wireInputs', []):
                source = wire.get('source') or {}
                source_instance = source.get('sourceInstance') or {}
                source_key = (source.get('sourceEngineId'), source_instance.get('compElementId'))
                if source_key[0] in local_ids:
                    ok = source_key in desired
                else:
                    ok = dependencies.get((ek, source_key), False)
                if not ok:
                    break
            if ok:
                eligible[ek] = item
        return eligible

    def _structures(self, items):
        return {key: repr({k: v for k, v in item['value'].items() if k != 'rowKind'}) for key, item in items.items()}

    def _assignment(self, items):
        slots = []
        for (_, element_id), item in items.items():
            value = item['value']
            slots.append({
                'boundInstance': {'compElementId': element_id},
                'kind': value.get('kind'),
                'wireInputValues': value.get('wireInputs', []),
                'orderIndex': value.get('orderIndex'),
                'capValues': [{'capId': cap_id, 'value': cap_value}
                              for cap_id, cap_value in item['caps'].items()],
                'presence': item['presence'],
            })
        return {'slotStates': slots, 'overflow': [], 'generation': 0}

    def _render_engine(self, engine, before, after):
        for key, item in before.items():
            if key not in after or self._structures({key: item}) != self._structures({key: after[key]}):
                self._observe_element(key, 'removing', None, item['value'])
                self._delete_components(key, item)
        for key, item in after.items():
            if key not in before or self._structures({key: item}) != self._structures({key: before[key]}):
                self._observe_element(key, 'preparing', None, None)
        try:
            assignment = self._assignment(after)
            engine._render(assignment, None)
            engine._committed = assignment
        except Exception as error:
            for key, item in after.items():
                self._observe_element(key, 'failed', str(error), None)
            return
        for key, item in before.items():
            if key not in after:
                self._observe_element(key, 'removed', None, None)
        for key, item in after.items():
            self._observe_components(key, item)
            self._observe_element(key, 'ready', None, item['value'])

    def _apply_value_changes(self, engine, before, after):
        for key, item in after.items():
            previous = before.get(key, {'caps': {}, 'presence': None})
            slot = engine._slots.get(key[1])
            if slot is None:
                continue
            state = slot['state']
            for cap_id in set(previous['caps']) - set(item['caps']):
                state['bag'].pop(cap_id, None)
                engine._reproject(key[1], {'what': 'cap', 'cap_id': cap_id, 'value': None})
                self._del_observation(self._observation_id(key, 'cap', cap_id))
            for cap_id, value in item['caps'].items():
                if not _values_equivalent(previous['caps'].get(cap_id), value):
                    state['bag'][cap_id] = value
                    engine._reproject(key[1], {'what': 'cap', 'cap_id': cap_id, 'value': value})
                    self._observe_cap(key, cap_id, value)
            if not _values_equivalent(previous.get('presence'), item['presence']):
                state['presence'] = item['presence']
                engine._reproject(key[1], {'what': 'presence', 'value': item['presence']})
                if item['presence'] is None:
                    self._del_observation(self._observation_id(key, 'presence'))
                else:
                    self._observe_presence(key, item['presence'])

    def _observation_id(self, key, component='element', cap_id=None):
        required_id = component + ':' + ''.join(f'{_byte_len(v)}:{v}' for v in (
            [key[0], key[1], cap_id] if cap_id is not None else [key[0], key[1]]))
        instance_id = self.instance.id
        return f'observation:{_byte_len(instance_id)}:{instance_id}{_byte_len(required_id)}:{required_id}'

    def _set_observation(self, item):
        self.client.sendEvent(self.client.buildSetEvent(item, itemType='CompEngineObservedStateRow'))

    def _del_observation(self, item_id):
        self.client.sendEvent(self.client.buildDelEvent({'id': item_id}, itemType='CompEngineObservedStateRow'))

    def _observe_element(self, key, phase, error, element_value):
        item = {
            'id': self._observation_id(key),
            'instanceId': self.instance.id,
            'engineId': key[0],
            'element': {'compElementId': key[1]},
            'value': {'kind': 'element', 'phase': phase, 'error': error},
        }
        if element_value is not None:
            item['elementValue'] = dict(element_value)
        self._set_observation(item)

    def _observe_cap(self, key, cap_id, value):
        self._set_observation({
            'id': self._observation_id(key, 'cap', cap_id), 'instanceId': self.instance.id,
            'engineId': key[0], 'element': {'compElementId': key[1]},
            'value': {'kind': 'cap', 'capId': cap_id, 'value': value, 'error': None},
        })

    def _observe_presence(self, key, weight):
        if weight is None:
            return
        self._set_observation({
            'id': self._observation_id(key, 'presence'), 'instanceId': self.instance.id,
            'engineId': key[0], 'element': {'compElementId': key[1]},
            'value': {'kind': 'presence', 'weight': weight, 'error': None},
        })

    def _observe_components(self, key, item):
        for cap_id, value in item['caps'].items():
            self._observe_cap(key, cap_id, value)
        self._observe_presence(key, item['presence'])

    def _delete_components(self, key, item):
        for cap_id in item['caps']:
            self._del_observation(self._observation_id(key, 'cap', cap_id))
        if item['presence'] is not None:
            self._del_observation(self._observation_id(key, 'presence'))

    def deliver_trigger(self, command):
        if self.view is None or not self.view.ready:
            raise ValueError('Required comp-engine state is not ready')
        if command.get('instanceId') != self.instance.id:
            raise ValueError('Trigger belongs to another instance')
        event_id = command.get('eventId')
        if not isinstance(event_id, str) or not event_id:
            raise ValueError('Trigger is missing eventId')
        if event_id in self.recent_events:
            return None
        element_id = (command.get('element') or {}).get('compElementId')
        key = (command.get('engineId'), element_id)
        item = self.desired.get(key)
        engine = self.engines.get(key[0])
        trigger_id = command.get('triggerId')
        if item is None or engine is None or trigger_id not in item['value'].get('triggers', []):
            raise ValueError('Trigger is not declared on an applied element')
        slot = engine._slots.get(element_id)
        if slot is None:
            raise ValueError('Trigger element is not applied')
        handler = engine.args.kind_registry.handlers.get(item['value'].get('kind'))
        if handler is None:
            raise ValueError('No handler for trigger element kind')
        handler.on_button_pressed({'compElementId': element_id}, trigger_id, command.get('payload'))
        self.recent_events.append(event_id)
        if len(self.recent_events) > 1024:
            del self.recent_events[:-1024]


def _required_controller():
    controller = getattr(td, '_rship_required_comp_engine', None)
    if controller is None:
        controller = RequiredCompEngineController()
        td._rship_required_comp_engine = controller
    else:
        controller.__class__ = RequiredCompEngineController
        for name, default in (
            ('client', None), ('instance', None), ('engines', {}), ('view', None),
            ('desired', {}), ('recent_events', []),
        ):
            if not hasattr(controller, name):
                setattr(controller, name, default)
    return controller


def configure_required_state(client, instance, engines):
    controller = _required_controller()
    controller.replace_engines(client, instance, engines)
    view = client.watchViewMap(
        key='required-comp-engine-state',
        viewId='RequiredCompEngineState',
        viewItemType='RequiredCompEngineStateRow',
        params={'instanceId': instance.id},
        onChange=controller.view_changed,
    )
    client.setCommandHandler('DeliverCompEngineTrigger', controller.deliver_trigger)
    return view


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
