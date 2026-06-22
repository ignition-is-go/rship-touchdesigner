"""
Example extension (DECLARATIVE style): expose a component's control surface to
rship by subclassing rship.TargetExt and decorating methods.

This is sugar over the imperative API in example_ext.py — same result, less wiring.
Put it on a Base COMP exactly like the imperative example:
  Extension 1          = op('./DemoExtDecl').module.DemoExtDecl(me)
  Promote Extension 1  = On

Decorate methods with @rship.action / @rship.emitter / @rship.property. The base
class collects them and registers the target on init. Schemas come from the method
signatures; property setters return a WriteOutcome.

The API module is reached via op.RSHIP.Api (a bare `import rship` only resolves for
DATs inside the rship .tox itself).
"""

rship = op.RSHIP.Api


class DemoExtDecl(rship.TargetExt):
    rship_name = "Python Demo (Declarative)"

    def __init__(self, ownerComp):
        self._rate = 1.0
        self._running = False
        # super().__init__ creates the target and registers every decorated member.
        super().__init__(ownerComp)

    # --- actions ---
    @rship.action
    def Reset(self):
        self._rate = 1.0
        op.RS_LOG.Info("[DemoExtDecl]: Reset -> rate=1.0")

    @rship.action
    def SetWindow(self, lo: float, hi: float):
        self._window = (lo, hi)
        op.RS_LOG.Info(f"[DemoExtDecl]: Set Window -> ({lo}, {hi})")

    # --- properties: getter + @<name>.setter (returns a WriteOutcome) ---
    @rship.property
    def Rate(self) -> float:
        return self._rate

    @Rate.setter
    def Rate(self, value: float):
        self._rate = value
        op.RS_LOG.Info(f"[DemoExtDecl]: Set Rate -> {value}")
        return rship.Applied(value)

    @rship.property
    def Running(self) -> bool:
        return self._running

    @Running.setter
    def Running(self, value: bool):
        self._running = value
        op.RS_LOG.Info(f"[DemoExtDecl]: Set Running -> {value}")
        return rship.Applied(value)

    # --- read-only emitter value source ---
    @rship.emitter
    def Phase(self) -> float:
        # a value rship can read/seed on demand (e.g. current LFO phase)
        return (absTime.seconds * self._rate) % 1.0
