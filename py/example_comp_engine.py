"""
Example: a cross-op, cross-engine comp MIXER spanning two bases.

  /rship_source/sources  (SourcesExt) — PRODUCER engine. Kind "source" reflects the base's
      "Sequence" fields (float, str) as caps; each placed source renders into a block, and
      its "float" field is exposed as the source's "value" output channel.

  /rship_source/layers   (LayersExt)  — CONSUMER engine. Kind "layer" reflects the base's
      "Sequence" fields; "float" is WIRE-FED from a source's "value" output, "rgba" stays a
      draggable cap.

The operator wires source.value -> layer.float; the layer's float par binds (par.expr) to the
source's float par on the OTHER base — cross-op, cross-engine PAR-TO-PAR, tracked by TD's cook
graph (change a source's float, the layer follows, frame-rate handled by TD).

All the ceremony — reflect the sequence, build the kind (caps/inputs/outputs), register, host,
declare the engine, and the render/output-binding handler — lives in the framework helper
comp_engine.sequence_manager(). A producer/consumer extension is then just kind + name + the
wired/outputs distinction.

Setup per base (the DAT is file-synced to this file; pick the matching class):
  Extension 1 = op('./compengine').module.SourcesExt(me)     # on /rship_source/sources
  Extension 1 = op('./compengine').module.LayersExt(me)      # on /rship_source/layers
  Promote Extension 1 = On

APIs: op.RSHIP.Api (rship) + op.RSHIP.CompEngine (comp engine).
"""


class SourcesExt:
    """Producer: each source -> a Sequence block; its 'float' field is exposed as 'value'."""
    def __init__(self, ownerComp):
        self.ownerComp = ownerComp
        self.refl, self.engine = op.RSHIP.CompEngine.sequence_manager(
            ownerComp, kind="source", engine_name="Sources", outputs={"value": "float"})

    def Republish(self):
        self.__init__(self.ownerComp)


class LayersExt:
    """Consumer: 'float' is wire-fed from a source's 'value' output; other fields are caps."""
    def __init__(self, ownerComp):
        self.ownerComp = ownerComp
        ce = op.RSHIP.CompEngine
        self.refl, self.engine = ce.sequence_manager(
            ownerComp, kind="layer", engine_name="Layers",
            wired={"float": ce.WireInput(["source"], "value")})

    def Republish(self):
        self.__init__(self.ownerComp)
