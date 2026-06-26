"""
Field-system comp-engine integration for the HRLV chandelier — mirrors Unreal's RshipField.

Lives as an extension on /3D_to_Volumetric_chandelier/lx_field_system. Declares 4 comp-engine
KINDS; the rship server solves placement / order / wiring and hands back an Assignment that we
render into the TD Effector / Generator / Transport sequences.

KINDS (model + exact wire values from FieldCompEngine.cpp, via clever-oryx/pulse-unreal;
verify comp-engine specifics with malcolm:rship). All share payload CompElementSelectionPayload;
every output channel is WellKnown String / semantic "signal":
  field            SINGLETON aggregate + the SINK (NO output channel — placement demand is rooted
                   at sinks). input `effectors` (fanIn, ordered, blend "field_sum", requiredMin 0).
                   No caps.
  field.effector   instanceable. caps = the Effector sequence's spatial params. inputs
                   `generators` (fanIn, ordered, blend "stack", requiredMin 1) + `transport`
                   (singleton, fanIn False). output "effector".
  field.generator  instanceable. caps = the Generator sequence; emit/clear are Pulse -> TRIGGERS.
                   leaf. output "generator".
  field.transport  instanceable. caps = {time, rate}. leaf. output "transport".
Topology generator -> effector -> field, transport -> effector. ORDER comes from the fan-in
ordering (no instance-level z-order).

PRESENCE -> two block pars on effectors+generators. enabled = the block is IN USE (a placed
instance backs it) — NOT presence-derived: a placed slot is enabled=1 even at weight 0. weight =
the presence value [0,1], which arrives on the value plane via the presence cap (SetPresence) and
STARTS AT 0 — we rely on the cap to drive it up to 1 (and fade it), so an unseeded slot holds
weight 0 rather than flashing to full. WIRE REFERENCES are written as STRING IDS (stable across
re-solves, unlike block indices): generator.effectorid = its effector's id, effector.transportid =
its transport's id, effector.fieldid = the single field's id; each block's `id` = its compElementId.
Sequences are sized to EXACTLY the placed count (floored at 1 — TD forbids 0 blocks) so vacated
blocks are CLEARED rather than left lingering; the lone residual block in the placed==0 case is
disabled (enabled=0, weight=0) so the field GLSL skips it.

Identity / presence-derived (enabled, weight) / topology-id (effectorid, fieldid, transportid) /
trigger fields are EXCLUDED from caps (below). Cap schemas reflect from the TD sequences via
par_schema (Float->Scalar, Int->Int, Toggle->Bool, Menu->EnumOf, XYZW-size-3->Vec3, Pulse->trigger).
"""

PAYLOAD = "CompElementSelectionPayload"

# block fields excluded from caps per sequence (identity | presence-derived | topology-wire | trigger).
# `enabled` and `weight` are NOT server caps — they derive from placement + the presence cap on render:
# weight = clamp(presence,0,1) (0 until the presence cap lifts it), enabled = in-use AND presence > 0.
_EXCLUDE = {
    "Effector":  {"id", "enabled", "weight", "fieldid", "transportid"},
    "Generator": {"id", "enabled", "weight", "effectorid"},      # emit/clear are Pulse -> triggers
    "Transport": {"id", "slot", "name", "fieldid", "enabled"},
}

# Menu caps reflect Unreal's EXACT EnumOf variant strings (FieldCompEngine.cpp, via clever-oryx),
# NOT the TD index menu names ('0'..'N') — so a single server cap drives both engines identically
# (a server blendOp is "max", never "3"). The TD menu LABEL order matches these 1:1, so render maps
# variant -> menuIndex (the variant's position). ★ Casing: all lowercase EXCEPT blendOp's `absMax`
# (camelCase) — reflect verbatim, do NOT lowercase the labels.
_WAVEFORM = ["auto", "constant", "sin", "cos", "triangle", "saw", "square", "linear", "simplex", "curl", "perlin"]
_ENUM = {
    "blendop":          ["add", "subtract", "min", "max", "multiply", "override", "absMax", "screen", "difference", "modulate"],
    "type":             ["oscillator", "traveling", "force"],
    "geometry":         ["radial", "planar"],
    "spatialwaveform":  _WAVEFORM,
    "temporalwaveform": _WAVEFORM,
    "pulsetrigger":     ["auto", "event"],
}


class FieldEngineExt:
    def __init__(self, ownerComp):
        self.ownerComp = ownerComp
        ce = op.RSHIP.CompEngine
        self.ce = ce
        self._log = op.RS_LOG          # cache the rship log op ONCE — avoids a per-render op lookup
        self._block_map = {}           # that draws a flickering field_test->rship reference line.
                                       # compElementId -> (sequence, block index), rebuilt each render
                                       # so a value-plane change can update JUST that block.

        def caps_and_triggers(seq_name):
            """Reflect a TD sequence's block-0 fields into (caps, triggers), skipping the
            excluded identity/presence/wire fields. Pulse fields -> triggers."""
            caps, triggers = [], []
            prefix = f"{seq_name}0"
            excl = _EXCLUDE.get(seq_name, set())
            for pg in ownerComp.customParGroups:
                if not pg.name.startswith(prefix):
                    continue
                field = pg.name[len(prefix):]
                if field in excl:
                    continue
                if ce.par_schema.is_trigger(pg):
                    triggers.append(ce.TriggerDef(id=field, display_name=(pg.label or field)))
                    continue
                # SKIP locally-animated pars: a par the executor can't write — any member NOT in
                # CONSTANT mode (expression/export/bind, e.g. Transport.time and Generator.
                # noisetranslation.y = absTime.seconds) — can NOT reconcile. Declaring it a cap
                # makes the server's desired-vs-actual diff never converge (the value ticks every
                # frame), so the source re-issues apply forever: the ~8/s, 11KB field-engine:apply
                # storm that saturates the WS handler (~245ms/parse) -> 3fps. It's a LOCAL
                # animation, not server-controlled desired-state, so it must not be a cap. (Mirrors
                # par_schema.write's ParMode-safety: if we can't write it, we can't reconcile it.)
                if not all(p.mode.name == "CONSTANT" for p in pg):
                    continue
                if field in _ENUM:
                    # override par_schema's EnumOf(menuNames=indices) with Unreal's name variants,
                    # and map the par's DEFAULT menu entry to its variant (menu order == _ENUM order)
                    variants = _ENUM[field]
                    try:
                        di = list(pg[0].menuNames).index(str(pg[0].default))
                    except ValueError:
                        di = 0
                    dflt = variants[di] if 0 <= di < len(variants) else variants[0]
                    caps.append(ce.custom_cap(field, ce.schema("EnumOf", variants=variants),
                                              default=dflt, label=(pg.label or field)))
                else:
                    caps.append(ce.cap_from_par_group(pg, cap_id=field))
            return caps, triggers

        def out(cid, disp):
            return ce.OutputChannelDef(cid, disp, ce.schema("String"), "signal")

        IO = ce.InputOrdering
        # --- field (singleton aggregate) — the SINK: NO output channel. Placement demand is
        # rooted at sinks (a kind with no output), so the field must be the sink for anything
        # to place; demand then pulls backward through the authored wires (effectors->field,
        # generators->effector, transport->effector). The rendered field result is consumed by
        # the TD render pipeline (GPU atlases), NOT a comp-engine wire — so no output here.
        # (Unreal keeps field's output only because a downstream sink — mullion selection —
        # consumes it; this standalone TD field has no such consumer. Verified w/ malcolm.)
        field_kind = (ce.KindDefBuilder("field", "Field", PAYLOAD)
                      .singleton()
                      .input(ce.InputDef(id="effectors", display_name="Effectors",
                                         accepts_kinds=["field.effector"], accepts_channel="effector",
                                         fan_in=True, ordering=IO.ORDERED, blend="field_sum",
                                         required_min=0, capacity=None))
                      .build())

        # --- field.effector ---
        eff_caps, eff_trigs = caps_and_triggers("Effector")
        eb = (ce.KindDefBuilder("field.effector", "Field Effector", PAYLOAD)
              .instanceability(ce.Instanceability.INSTANCEABLE)
              .caps(eff_caps)
              .input(ce.InputDef(id="generators", display_name="Generators",
                                 accepts_kinds=["field.generator"], accepts_channel="generator",
                                 fan_in=True, ordering=IO.ORDERED, blend="stack",
                                 required_min=1, capacity=None))
              .input(ce.InputDef(id="transport", display_name="Transport",
                                 accepts_kinds=["field.transport"], accepts_channel="transport",
                                 fan_in=False, ordering=IO.UNORDERED, blend="stack",
                                 required_min=None, capacity=None))
              .output_channel(out("effector", "Effector")))
        for t in eff_trigs:
            eb.trigger(t)
        effector_kind = eb.build()

        # --- field.generator ---
        gen_caps, gen_trigs = caps_and_triggers("Generator")
        gb = (ce.KindDefBuilder("field.generator", "Field Generator", PAYLOAD)
              .instanceability(ce.Instanceability.INSTANCEABLE)
              .caps(gen_caps)
              .output_channel(out("generator", "Generator")))
        for t in gen_trigs:
            gb.trigger(t)
        generator_kind = gb.build()

        # --- field.transport ---
        tr_caps, _ = caps_and_triggers("Transport")
        transport_kind = (ce.KindDefBuilder("field.transport", "Field Transport", PAYLOAD)
                          .instanceability(ce.Instanceability.INSTANCEABLE)
                          .caps(tr_caps)
                          .output_channel(out("transport", "Transport"))
                          .build())

        # --- handlers ---
        # `_render_all` is HOLISTIC: it walks the whole committed subgraph and writes all three
        # sequences, so it only needs to run ONCE per apply. But comp_engine projects EVERY kind on
        # a topology apply (each calling on_apply), so on_apply=_render_all would re-run the identical
        # full render 3-4x per apply — a big topology-frame STALL on large graphs. So on_apply routes
        # through _render_once, which dedups on the apply's generation (the first kind renders, the
        # rest no-op). Value-plane changes are handled per-instance by on_value (targeted single-block
        # update — never a full render); generators route emit/clear buttons to their rendered block.
        ext = self
        self._gen_block = {}            # generator compElementId -> Generator block index (triggers)
        self._last_render_gen = None    # generation of the last full render (per-apply dedup)

        # wants_tick=False: the render is fully determined by committed topology + the value plane
        # (raw wire topology, no dynamic producer outputs — the field emits none), so per-tick
        # re-projection would just rebuild the identical render. Skip it.
        class Render(ce.KindHandler):
            wants_tick = False
            def on_apply(self, ctx, batch):
                ext._render_once(ctx)
            def on_value(self, ctx, instance, kind_id, change):
                ext._update_value(ctx, instance, change)

        class GeneratorRender(ce.KindHandler):
            wants_tick = False
            def on_apply(self, ctx, batch):
                ext._render_once(ctx)
            def on_value(self, ctx, instance, kind_id, change):
                ext._update_value(ctx, instance, change)
            def on_button_pressed(self, instance, button_id, data):
                ext._fire_generator(instance, button_id)

        reg = (ce.KindRegistryBuilder()
               .register_with_handler(field_kind, Render())
               .register_with_handler(effector_kind, Render())
               .register_with_handler(generator_kind, GeneratorRender())
               .register_with_handler(transport_kind, Render())
               .build())

        host = op.RSHIP.Api.target(ownerComp, "Field System")
        self.engine = ce.comp_engine(ownerComp, ce.CompEngineArgs(
            short_id="field-engine", display_name="Field System",
            kind_registry=reg, host_target=host))

    # ---- render: solver assignment -> TD Effector/Generator/Transport sequences ----------------

    def _render_once(self, ctx):
        """Render the whole graph ONCE per apply. comp_engine projects every kind on a topology
        apply, each calling on_apply; since _render_all is holistic, running it per-kind is 3-4x
        redundant (the topology-frame stall). Dedup on the apply's generation: the first kind to
        fire renders, the rest no-op (same generation)."""
        gen = ctx.generation
        if gen == self._last_render_gen:
            return
        self._last_render_gen = gen
        self._render_all(ctx)

    def _render_all(self, ctx):
        """Walk the placed subgraph and write the three sequences. Idempotent: rebuilds entirely
        from the committed state, so it's safe to run from ANY kind's handler (which is what makes
        the value plane work — see the handler note). Topology comes from the raw wire_inputs
        (CrossEngineRef.sourceInstance.compElementId): the field's `effectors` fan-in gives effector
        order; each effector's `generators`/`transport` fan-in gives the generator->effector and
        effector->transport links. References are written as STRING IDS (stable across re-solves,
        unlike block indices): generator.effectorid = its effector's id, effector.transportid = its
        transport's id, effector.fieldid = the single field's id. enabled = in-use AND presence > 0;
        weight = clamp(presence,0,1), 0 until the presence cap (SetPresence) drives it up."""
        try:
            ps = self.ce.par_schema
            eng = ctx.engine
            field_batch = eng._batch_for_kind("field")
            eff_batch = eng._batch_for_kind("field.effector")
            gen_batch = eng._batch_for_kind("field.generator")
            tr_batch = eng._batch_for_kind("field.transport")
            field_ka = field_batch[0] if field_batch else None

            def cid(ka):
                return ka.instance.get("compElementId")

            def wired(ka, pin):
                """Producer compElementIds wired into `pin`, in server fan-in order."""
                out = []
                for e in (ka.wire_inputs if ka else []) or []:
                    if e.get("pinId") != pin:
                        continue
                    src = e.get("source") or {}
                    inst = src.get("sourceInstance") or {}
                    c = inst.get("compElementId")
                    if c is not None:
                        out.append(c)
                return out

            eff_by_id = {cid(k): k for k in eff_batch}
            gen_by_id = {cid(k): k for k in gen_batch}
            tr_by_id = {cid(k): k for k in tr_batch}

            # effector order = field's `effectors` fan-in (stable), + any stragglers
            eff_order = [c for c in wired(field_ka, "effectors") if c in eff_by_id]
            eff_order += [c for c in eff_by_id if c not in eff_order]
            tr_order = [cid(k) for k in tr_batch]

            # generators grouped under their effector (effector order; each effector's gen fan-in);
            # gen_eff maps a generator -> its effector's ID (the back-reference written on render).
            gen_order, gen_eff = [], {}
            for ec in eff_order:
                for gc in wired(eff_by_id[ec], "generators"):
                    if gc in gen_by_id and gc not in gen_eff:
                        gen_eff[gc] = ec
                        gen_order.append(gc)
            gen_order += [c for c in gen_by_id if c not in gen_eff]   # orphans (requiredMin:1 ⇒ rare)

            field_id = self._field_id()
            self._fill("Transport", tr_order, tr_by_id, ps, lambda i, c, ka: {"fieldid": field_id})
            self._fill("Effector", eff_order, eff_by_id, ps, lambda i, c, ka: {
                "fieldid": field_id,
                "transportid": next((t for t in wired(ka, "transport") if t in tr_by_id), ""),
            })
            self._gen_block = {c: j for j, c in enumerate(gen_order)}
            self._fill("Generator", gen_order, gen_by_id, ps,
                       lambda i, c, ka: {"effectorid": gen_eff.get(c, "")})
            # cache compElementId -> (sequence, block index) so a value-plane change (presence/cap)
            # updates JUST that block (see _update_value) instead of re-walking the whole topology.
            self._block_map = {}
            for sn, order in (("Transport", tr_order), ("Effector", eff_order), ("Generator", gen_order)):
                for i, c in enumerate(order):
                    self._block_map[c] = (sn, i)
            self._log.Info(f"[FieldEngine] rendered: {len(eff_order)} eff / {len(gen_order)} gen / {len(tr_order)} tr")
        except Exception as e:
            self._log.Error(f"[FieldEngine] render failed: {e}")

    def _update_value(self, ctx, instance, change):
        """Value-plane TARGETED update: write ONLY the changed instance's block — presence ->
        enabled+weight, cap -> the one cap par — via the cached _block_map from the last render.
        O(1): no topology walk, no full sequence rewrite, and the common presence path touches ONLY
        field_test-local pars (no per-frame field_test->rship op lookup / reference-line churn, and
        no render log). Falls back to a full render if the instance has no cached block yet (rare:
        a topology apply always renders first)."""
        loc = self._block_map.get(instance.get("compElementId"))
        if loc is None:
            return self._render_all(ctx)                 # not yet rendered -> full render (rare)
        seq_name, i = loc
        what = change.get("what")
        if what == "presence":
            w = change.get("value") or 0.0
            self._setpar(f"{seq_name}{i}enabled", 1 if w > 1e-4 else 0)
            self._setpar(f"{seq_name}{i}weight", max(0.0, min(1.0, w)))
        elif what == "cap":
            cap_id, val = change.get("cap_id"), change.get("value")
            if val is None:
                return
            pg = self.ownerComp.parGroup[f"{seq_name}{i}{cap_id}"]
            if pg is None:
                return
            if cap_id in _ENUM:                          # name variant -> TD menuIndex
                try:
                    pg[0].menuIndex = _ENUM[cap_id].index(val)
                except Exception:
                    pass
            else:
                self.ce.par_schema.write(pg, val)        # cached module fn; operates on a local par

    def _fill(self, seq_name, order, by_id, ps, extra_fn):
        """Write each block: identity + enabled (presence>1e-4) + weight (clamp(presence,0,1);
        no-op if the sequence has no weight par) + caps (par_schema-safe) + the topology id refs
        (extra_fn). The sequence GROWS to fit the placed instances but never shrinks; any block with
        no placed instance is disabled (enabled=0, weight=0) so the field GLSL skips it."""
        seq = getattr(self.ownerComp.seq, seq_name)
        placed = len(order)
        # Size the sequence to EXACTLY the placed count so vacated blocks are CLEARED, not left
        # lingering with stale ids/values. TD forbids 0 blocks, so floor at 1 — that single
        # residual block is disabled below when placed==0 (the only case the disable loop runs).
        want = max(1, placed)
        if seq.numBlocks != want:
            seq.numBlocks = want
        for i, c in enumerate(order):
            ka = by_id[c]
            # This block's slot is RESERVED for the placed instance (id is set so the GLSL can
            # address it). WEIGHT is the presence value, which arrives on the value plane via the
            # presence cap (SetPresence) and STARTS AT 0 — we rely on that cap to drive it up to 1
            # (and to fade it), so an unseeded slot (None: no cap yet) holds weight 0 rather than
            # flashing to full. ENABLED = the slot is in use AND presence > 0: a placed-but-not-yet
            # -present slot is reserved (id set) but stays enabled=0/weight=0 until the cap lifts it.
            weight = ka.presence or 0.0
            self._setpar(f"{seq_name}{i}id", c)
            self._setpar(f"{seq_name}{i}enabled", 1 if weight > 1e-4 else 0)
            self._setpar(f"{seq_name}{i}weight", max(0.0, min(1.0, weight)))
            for cap_id, val in (ka.caps or {}).items():
                if val is None:                             # null desired (cap unset server-side, e.g. a
                    continue                                # freshly-placed instance) -> leave the par as-is;
                                                            # writing None to a numeric par throws the cast.
                pg = self.ownerComp.parGroup[f"{seq_name}{i}{cap_id}"]
                if pg is None:
                    continue
                if cap_id in _ENUM:                         # name variant -> TD menuIndex
                    try:
                        pg[0].menuIndex = _ENUM[cap_id].index(val)
                    except Exception:
                        pass
                else:
                    ps.write(pg, val)
            for field, val in extra_fn(i, c, ka).items():
                self._setpar(f"{seq_name}{i}{field}", val)
        for i in range(placed, seq.numBlocks):              # unused blocks -> off (skipped by the GLSL)
            self._setpar(f"{seq_name}{i}enabled", 0)
            self._setpar(f"{seq_name}{i}weight", 0)

    def _setpar(self, name, val):
        p = self.ownerComp.par[name]
        if p is None:
            return
        try:
            p.val = val
        except Exception:
            try:
                p.menuIndex = int(val)
            except Exception:
                pass

    def _field_id(self):
        """The single hardcoded comp-engine field == the first TD Field block's id (default "0")."""
        seq = getattr(self.ownerComp.seq, "Field", None)
        blocks = list(getattr(seq, "blocks", []) or []) if seq is not None else []
        if blocks:
            try:
                return str(int(blocks[0].par.Id.eval()))
            except Exception:
                pass
        return "0"

    def _fire_generator(self, instance, button_id):
        j = self._gen_block.get(instance.get("compElementId"))
        if j is None:
            return
        p = self.ownerComp.par[f"Generator{j}{button_id}"]
        if p is not None:
            try:
                p.pulse()
            except Exception:
                pass

    def Republish(self):
        self.__init__(self.ownerComp)
