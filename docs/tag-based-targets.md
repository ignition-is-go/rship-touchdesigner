# Tag-based targets

The zero-code way to expose a component to rship: **tag it `rship`** and the executor
turns its custom parameters into rship targets automatically. Best for exposing the
parameters an artist already built on a COMP (or a Notch TOP), with no Python.

## How it works

On every project save (and on connect), the rship executor recursively scans its
network for operators tagged `rship`, and builds a target tree from each one:

```
COMP  (target)
 └─ Page            (target, one per custom parameter page)
     ├─ ParGroup    (Property: a value emitter + a "Set" writer)
     └─ Sequence    (Property: the whole sequence as an array)
```

- **Each parameter becomes a Property** — a readable value (emitter) paired with a
  `Set <par>` writer. rship can both read the live value and set it.
- **Pages and the COMP get a `Bulk Set`** action that writes many parameters at once.
- Values are published to rship as they change, and applied back when rship sets them.

> The rship `.tox` scans the directory it lives in and all subdirectories. Place it at
> the **root** of your network so the whole project is scanned (and to avoid clutter).

## Steps

1. Drag the rship `.tox` into your network (at the root).
2. On the `.tox`'s parameter page, set the Rocketship server **Address** and **Port**
   (default `5155`).
3. **Save the project.** Verify the TouchDesigner instance appears in the rship UI and
   activate it.
4. **Tag a Base COMP `rship`** (right-click → Customize Component → Tags, or
   `op('mycomp').tags.add('rship')`).
5. **Save the project.** The COMP and its parameters appear as targets in the rship UI.

## Exposing parameters

Custom parameters on a tagged COMP are what get exposed. To add one:

1. Open the **Component Editor** of the tagged COMP.
2. Click and drag the parameter to expose onto the Component Editor window. See the
   [Component Editor Dialog](https://derivative.ca/UserGuide/Component_Editor_Dialog)
   for binding/reference options.
3. **Save the project.** The parameter appears in rship as a Property.

Supported parameter styles include Float, Int, Toggle, Pulse/Momentary, Menu/StrMenu,
String, File, WH, XY, XYZ, XYZW, RGB(A), UV(W), and Sequences. Each is mapped to an
appropriate JSON schema automatically.

> **Identity is by parameter _name_.** Renaming a parameter's name breaks its rship
> binding and creates a new target. Prefer changing the **label** instead of the name.

## Notch TOPs

Notch TOPs are first-class:

1. Tag a Notch TOP `rship`.
2. Save the project.
3. The Notch TOP, its layers, and their parameters appear as targets.

## Streams (optional)

Tag an operator `rship_stream` (in addition to `rship`) to also publish a WebRTC video
stream of it to rship (TOPs stream directly; COMPs stream their `opviewer`).

## When to use the Python API instead

Tag-based targets only expose **parameters**. To expose arbitrary behavior — call a
method, drive Python state, compute a value on the fly — use the
[Python API](./python-api.md), which can sit alongside tagged targets.
