"""
Example: a comp engine that REFLECTS a TouchDesigner sequence block into comp-element caps.

The operator composes a dynamic, ordered set of "Block" elements in rship; this executor
materializes them as blocks of the COMP's "Sequence" parameter. The cap list is REFLECTED
from the sequence block's parameters (one cap per block field, typed from the TD par
style), so every field is a draggable cap on the element and on_apply writes each cap back
to that block's par.

All the reflection lives in the framework — comp_engine.SequenceReflector (a two-way
bridge: refl.caps() for the kind declaration, refl.render(batch) on apply). This extension
is just the thin wiring. Edit the block's fields in TD then call ext.Republish() to
re-reflect (the comp element definition updates to match).

(Planned: marking some block pars as WIRE-ROUTED inputs — filled by an upstream engine's
output instead of a cap — with the framework reflecting the rest. The inter-engine routing
model is being settled with the Unreal executor first.)

Put on a Base COMP that has a custom sequence parameter "Sequence":
  Extension 1         = op('./SeqEngineExt').module.SeqEngineExt(me)
  Promote Extension 1 = On

APIs: op.RSHIP.Api (rship) + op.RSHIP.CompEngine (comp engine).
"""

SEQUENCE_NAME = "Sequence"


class SeqEngineExt:
    def __init__(self, ownerComp):
        self.ownerComp = ownerComp
        self._ce = op.RSHIP.CompEngine
        self._rship = op.RSHIP.Api
        self._build()

    def _build(self):
        ce = self._ce
        host = self._rship.target(self.ownerComp, "Sequence Demo")
        self.refl = ce.SequenceReflector(self.ownerComp, SEQUENCE_NAME)

        ext = self
        class BlockHandler(ce.KindHandler):
            def on_apply(self, ctx, batch):
                ext.refl.render(batch)          # ordered placement -> sequence blocks

        kind = (ce.KindDefBuilder("seq.block", "Block", "CompElementClipPayload")
                .instanceability(ce.Instanceability.INSTANCEABLE)
                .instance_ordering(ce.InputOrdering.ORDERED)
                .caps(self.refl.caps())         # caps ARE the reflected block fields
                .build())
        reg = ce.KindRegistryBuilder().register_with_handler(kind, BlockHandler()).build()
        self.engine = ce.comp_engine(self.ownerComp, ce.CompEngineArgs(
            short_id="seq-engine", display_name="Sequence Engine",
            kind_registry=reg, host_target=host))

    def Republish(self):
        """Re-reflect the block fields and re-declare the engine — call after editing the
        block's parameters in TD so the comp element definition picks up the new caps."""
        self._build()
        op.RS_LOG.Info(f"[SeqEngineExt]: re-reflected block -> caps "
                       f"{[c.custom_id for c in self.refl.caps()]}")
