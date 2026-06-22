# Rship-TouchDesigner

The TouchDesigner executor for [Rocketship](https://rship.io). It connects to a
Rocketship server and exposes parts of your TouchDesigner project as rship
**targets**, with **actions** (things rship can do), **emitters** (values rship can
read), and **properties** (read + write values that reconcile).

There are two ways to expose things — use either or both:

| | [Tag-based targets](./docs/tag-based-targets.md) | [Python API](./docs/python-api.md) |
|---|---|---|
| Code required | None | Python |
| Exposes | A component's custom **parameters** | **Anything** — methods, Python state, computed values |
| Best for | Artists exposing existing controls | Exposing a custom extension's control surface |
| How | Tag a COMP / Notch TOP `rship` | `op.RSHIP.Api` from your extension |

## Setup

1. Drag the `rship.tox` into your network. Place it at the **root** — it recursively
   scans its directory and all subdirectories for targets.
2. On the `.tox`'s parameter page, set the Rocketship server **Address** and **Port**
   (default `5155`).
3. **Save the project.**
4. Verify the TouchDesigner instance appears in the rship UI and activate it.

## Exposing things

### Option A — tag-based (no code)

Tag a Base COMP (or Notch TOP) `rship` and save. Its custom parameters become rship
properties automatically. Full guide: **[docs/tag-based-targets.md](./docs/tag-based-targets.md)**.

### Option B — Python API (custom hooks)

From your own extension, register targets/actions/properties/emitters in Python.
Schemas are derived from your function signatures.

```python
class MyExt:
    def __init__(self, ownerComp):
        self.rship = op.RSHIP.Api
        t = self.rship.target(ownerComp, "My Effect")
        t.action("Trigger", self.Trigger)
        t.property("Level", get=self.GetLevel, set=self.SetLevel)

    def Trigger(self): ...
    def GetLevel(self) -> float: return self._level
    def SetLevel(self, value: float):
        self._level = value
        return self.rship.Applied(value)
```

Full guide: **[docs/python-api.md](./docs/python-api.md)**. Runnable examples:
[`py/example_ext.py`](./py/example_ext.py) (imperative) and
[`py/example_ext_declarative.py`](./py/example_ext_declarative.py) (decorator/base class).
Each is wired onto an example base COMP in the demo project.

## Connection

The executor maintains the server connection automatically: it acquires its machine id
and server URL from the local Rship Link (falling back to the hostname / the manually
entered Address), keeps the socket alive, and reconnects with backoff if it drops. The
`.tox`'s parameter page shows live connection status and sync stats (local/remote
target/action/emitter counts).

## Notes

- **Parameter identity is by name.** Renaming a tagged parameter (or omitting an
  explicit `short_id` in the Python API) breaks the binding and creates a new target.
  Prefer changing labels; pin a `short_id` when you need stable identity.
- Removed targets are not garbage-collected on the server; entities from an offline
  executor simply show offline.

## Repository layout

- `py/RshipExt.py` — main extension (connection lifecycle, scan, send/seed/reconcile).
- `py/mod/` — modules: `rship.py` (Python API), `exec.py`/`myko.py` (wire protocol),
  `connection.py` (connection state machine), `op_target.py` + `*_target.py`/`par_shape.py`
  (tag-based target model).
- `py/example_ext*.py` — Python API examples.
- `docs/` — the two workflow guides.
