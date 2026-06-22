# Python API

Expose **anything** to rship from your own Python — call a method, drive Python state,
compute a value on the fly. Use this when [tag-based targets](./tag-based-targets.md)
(which only expose parameters) aren't enough, e.g. to expose control of a custom
extension. The two approaches coexist.

The model mirrors the rship SDK: an **Instance** has **Targets**, and each target has
**Actions** (invokables), **Emitters** (readable values you publish), and **Properties**
(an emitter paired with a writer). You define them with plain Python functions —
**schemas are derived from your function signatures**.

## Accessing the API

```python
rship = op.RSHIP.Api
```

`op.RSHIP` is the rship `.tox`'s global op shortcut; `.Api` is the API module. Use this
from anywhere in your project. (A bare `import rship` only works for DATs that live
*inside* the rship `.tox` — TouchDesigner scopes module imports to the component
hierarchy — so prefer `op.RSHIP.Api` in your own components.)

## Quick start (imperative)

Put this on a Base COMP as `Extension 1 = op('./DemoExt').module.DemoExt(me)`,
`Promote Extension 1 = On`. See [`py/example_ext.py`](../py/example_ext.py).

```python
class DemoExt:
    def __init__(self, ownerComp):
        self.ownerComp = ownerComp
        self.rship = op.RSHIP.Api
        self._level = 0.0

        t = self.rship.target(ownerComp, "Demo Effect")
        t.action("Trigger", self.Trigger)                 # no input
        t.action("Set Color", self.SetColor)              # input reflected: {r,g,b}
        t.property("Level", get=self.GetLevel, set=self.SetLevel)
        self.Beat = t.emitter("Beat", type="number")      # push-only signal

    def Trigger(self):
        op.RS_LOG.Info("triggered")

    def SetColor(self, r: float, g: float, b: float):
        self.ownerComp.color = (r, g, b)

    def GetLevel(self) -> float:
        return self._level

    def SetLevel(self, value: float):
        self._level = value
        return self.rship.Applied(value)                  # framework pulses readback
```

## Quick start (declarative)

Subclass `rship.TargetExt` and decorate methods. Same result, less wiring. See
[`py/example_ext_declarative.py`](../py/example_ext_declarative.py).

```python
rship = op.RSHIP.Api

class DemoExtDecl(rship.TargetExt):
    rship_name = "Demo Effect"

    def __init__(self, ownerComp):
        self._rate = 1.0
        super().__init__(ownerComp)          # registers the decorated members

    @rship.action
    def Reset(self):
        self._rate = 1.0

    @rship.action
    def SetWindow(self, lo: float, hi: float): ...

    @rship.property
    def Rate(self) -> float:
        return self._rate
    @Rate.setter
    def Rate(self, value: float):
        self._rate = value
        return rship.Applied(value)

    @rship.emitter
    def Phase(self) -> float:                 # read-only value source
        return (absTime.seconds * self._rate) % 1.0
```

## API reference

### `rship.target(ownerComp, name, *, short_id=None, category="python") -> TargetProxy`
Create (or replace) a target. Re-creating with the same component + id replaces the
prior registration, so re-initializing your extension is clean.

### `TargetProxy.action(name, handler=None, *, short_id=None, schema=None, type=None)`
Register an invokable. Usable imperatively (`t.action("Go", self.go)`) or as a decorator
(`@t.action("Go")` / `@t.action`). The handler's input schema is reflected from its
signature (see [Schemas](#schemas)).

### `TargetProxy.property(name, *, get, set=None, short_id=None, type=None, schema=None) -> PropertyProxy`
A readable value (`get`) optionally paired with a writer (`set`). With a writer it's
read/write; `set=None` makes it read-only. The read schema comes from `get`'s return
annotation, the write schema from `set`'s parameter. On `Applied`, the framework pulses
the readback so the server reconciles. `.pulse(value)` publishes a value out-of-band
(for Deferred writes or external changes).

### `TargetProxy.emitter(name, *, get=None, short_id=None, type=None, schema=None) -> EmitterProxy`
A readable value with no writer. With `get=`, it's a value source rship can read/seed on
demand. Without, it's push-only — call `.pulse(value)` when it changes. Schema from
`get`'s return type, or `type=`/`schema=`.

### `WriteOutcome`
Every property setter must return one of:
- `rship.Applied(value=None)` — applied; the framework pulses `value` (or the getter's
  current value) back as the readback.
- `rship.Deferred` — accepted, value not known yet (e.g. awaiting hardware); pulse later
  via the property's `.pulse()`.
- `rship.Rejected(reason)` — refused; nothing is pulsed.

## Schemas

Schemas are derived from your function signature; you rarely write one by hand.

| Signature | Schema | Called as |
|---|---|---|
| `def f(self)` | _(none)_ | `f()` |
| `def f(self, v: float)` | `number` | `f(value)` |
| `def f(self, r: float, g: float, b: float)` | object `{r,g,b}` | `f(**data)` |
| `def f(self, p: MyDataclass)` | object from fields | `f(MyDataclass(**data))` |
| `def f(self, data)` _(unannotated)_ | object | `f(data)` (raw dict) |

Type mapping: `float→number`, `int→integer`, `str→string`, `bool→boolean`,
`list→array`, dataclass→object (recursed), `Optional[X]→X`. Convenience dataclasses
`rship.Color` (`{r,g,b,a}`), `rship.XYZ`, `rship.XY` are provided.

**Overrides** (skip reflection): pass `type=` with a token
(`"number"`, `"integer"`, `"string"`, `"bool"`/`"toggle"`, `"rgb"`, `"rgba"`, `"xy"`,
`"xyz"`) or `schema=` with a raw JSON-Schema dict. Required for `*args`/`**kwargs`
handlers.

> Define payload dataclasses at **module scope** so their type hints resolve.

## Identity

Ids follow the SDK convention and are derived for you:
- target → `{serviceId}:{short}`
- action / emitter → `{targetId}:{short}`

`short` defaults to a slug of the `name` (e.g. `"Set Color"` → `set-color`). **Renaming
changes identity** — pass an explicit `short_id=` to keep a stable id across renames.
`short`s must be unique within a target (and target `short`s unique within the service).

## Lifecycle

- Targets register when your extension initializes (typically in `__init__`).
- The executor publishes them on connect, and re-publishes within ~1s whenever the
  registry changes — so registering after connect works too.
- Property setters that return `Applied` auto-pulse the readback; for push emitters and
  Deferred writes, call `.pulse(value)` yourself when the value changes.

## Notes / gotchas

- Use `op.RSHIP.Api`, not a bare `import rship`, outside the `.tox`.
- The registry is process-global (anchored on TouchDesigner's `td` module), so it
  survives DAT recompiles and extension re-inits.
- Removed targets/actions are not garbage-collected server-side; an offline executor's
  entities simply show offline.
