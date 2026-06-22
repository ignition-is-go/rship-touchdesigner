"""
Example extension: expose a custom component's control surface to rship via the
Python API.

How to use this pattern on your own Base COMP:
  Extension 1          = op('./DemoExt').module.DemoExt(me)
  Promote Extension 1  = On
On initialization the extension registers an rship target (no `rship` tag needed)
with two actions, two properties, and a push emitter. The API module is reached via
op.RSHIP.Api, so this works from any component in the project (a bare `import rship`
only resolves for DATs that live inside the rship .tox itself).

See py/mod/rship.py for the full API surface. Schemas are derived from your method
signatures; property setters return a WriteOutcome (Applied / Deferred / Rejected).
"""


class DemoExt:
    def __init__(self, ownerComp):
        self.ownerComp = ownerComp
        self.rship = op.RSHIP.Api          # target/action/property/emitter/WriteOutcome
        self._level = 0.0
        self._enabled = False

        t = self.rship.target(ownerComp, "Python Demo")

        # Action with no input (null schema).
        t.action("Trigger", self.Trigger)
        # Action whose input schema is reflected from the signature: {r, g, b: number}.
        t.action("Set Color", self.SetColor)

        # Properties: a getter + a setter that returns a WriteOutcome. The framework
        # pairs the read emitter with the canonical writer and pulses the readback on
        # Applied, so the server reconciles.
        t.property("Level", get=self.GetLevel, set=self.SetLevel)
        t.property("Enabled", get=self.GetEnabled, set=self.SetEnabled)

        # Push-only emitter (read-only signal). Call self.Beat.pulse(value) when it
        # changes, e.g. from a CHOP Execute DAT on a beat.
        self.Beat = t.emitter("Beat", type="number")

    # --- actions ---
    def Trigger(self):
        op.RS_LOG.Info("[DemoExt]: Trigger fired")

    def SetColor(self, r: float, g: float, b: float):
        self.ownerComp.color = (r, g, b)
        op.RS_LOG.Info(f"[DemoExt]: Set Color -> ({r:.3f}, {g:.3f}, {b:.3f})")

    # --- Level property (float) ---
    def GetLevel(self) -> float:
        return self._level

    def SetLevel(self, value: float):
        self._level = value
        op.RS_LOG.Info(f"[DemoExt]: Set Level -> {value}")
        return self.rship.Applied(value)

    # --- Enabled property (bool) ---
    def GetEnabled(self) -> bool:
        return self._enabled

    def SetEnabled(self, value: bool):
        self._enabled = value
        op.RS_LOG.Info(f"[DemoExt]: Set Enabled -> {value}")
        return self.rship.Applied(value)

    # --- example emitter publish ---
    def PulseBeat(self, bpm: float):
        self.Beat.pulse(bpm)
        op.RS_LOG.Info(f"[DemoExt]: Pulsed Beat -> {bpm}")
