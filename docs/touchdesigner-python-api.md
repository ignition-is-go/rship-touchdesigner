# TouchDesigner Python API — Deep Dive

Reference for the rship-touchdesigner executor work. Anchored to TouchDesigner
**099.2025.32900** (introspected live). Emphasis on the subsystems this project leans on:
the execution model, parameters/expressions/**binding**, cooking, and the gotchas that have
actually bitten us (module epochs, extension re-init, the connection state machine).

> Casing/legacy note: ignore old Tscript parameter "modes" like `init`/`expr`/`anim`. Modern
> Python uses the `ParMode` enum (`CONSTANT`/`EXPRESSION`/`EXPORT`/`BIND`). Custom parameters
> created in code **are** saved in the `.toe` (they're part of the COMP); operator *storage*
> (`store`/`fetch`) is a separate persistence mechanism.

---

## 1. Where Python runs (the execution model)

Four distinct execution contexts, each with the standard globals (`me`, `op`, `ops`,
`parent`, `iop`, `ipar`, `root`, `project`, `app`, `ui`, `absTime`, `monitors`, `mod`, `var`,
`td`, `tdu`):

1. **Parameter expressions** — a Python string on a parameter (`ParMode.EXPRESSION`).
   Evaluated by the cook system in the owning op's context. `me` = the owning op; `me.curPar`
   = the parameter being evaluated. **Must be side-effect free** (re-evaluated often).
2. **DAT scripts** — code in a Text/Script DAT. Either imported as a module (`.module`) or
   executed (`.run()`).
3. **Extensions** — a Python class bound to a COMP's `Extension N` parameter, instantiated
   once (`__init__(self, ownerComp)`), persists across cooks until re-init. This is the
   primary pattern in this repo (`RshipExt`, `SeqEngineExt`, the demo extensions).
4. **Callback DATs** — Execute / Parameter Execute / CHOP Execute / DAT Execute / Panel
   Execute / OP Execute, each with fixed callback names (below).

### DAT modules and the "epoch" problem (critical for this repo)
- A Text DAT exposes `.module` — a Python module wrapping its code, **(re)created on cook /
  recompile**. `op('X').module.ClassName(me)` instantiates a class from it.
- TD **duplicates** these modules across compile/reinit epochs. A plain module-global
  `SINGLETON = Foo()` therefore yields *multiple* instances — inbound handlers registered on
  one and outbound providers on another silently diverge. **This is the root of several bugs
  we fixed.**
- **Fix (the pattern we use):** anchor singletons on the process-global `td` module:
  ```python
  def _shared():
      c = getattr(td, '_rship_client', None)
      if c is None:
          c = ExecClient(); td._rship_client = c
      return c
  CLIENT = _shared()          # exec.py; also td._rship_state, td._rship_engines, td._rship_outputs
  ```
- `import X` only resolves for DATs inside the same component hierarchy. To expose a module
  project-wide we hang it off the extension: `op.RSHIP.Api` (rship), `op.RSHIP.CompEngine`.

### Callback DAT signatures (the ones that matter)
| DAT | Callbacks |
|-----|-----------|
| Execute | `onStart`, `onCreate`, `onFrameStart(frame)`, `onFrameEnd(frame)`, `onPlayStateChange`, `onExit` |
| Parameter Execute | `onValueChange(par, prev)`, `onPulse(par)`, `onValuesChanged(changes)` |
| CHOP Execute | `onValueChange(channel, sampleIndex, val, prev)`, `onOffToOn`, `onOnToOff`, `whileOn`, `whileOff` |
| DAT Execute | `onTableChange(dat)`, `onRowChange`, `onColChange`, `onCellChange`, `onSizeChange` |
| Panel Execute | `onOffToOn`, `onValueChange`, … (per panel value) |
| OP Execute | `onPreCook`, `onPostCook`, `onDestroy`, `onFlagChange`, … |

### Extensions: persistence + re-init
- Instance persists across frames/parameter-changes. **Re-init destroys it** (`__init__` runs
  again, state lost). Triggers: file load, `Extension N` reassignment, `op.par.reinitextensions
  .pulse()` / `comp.initializeExtensions()`, DAT recompile.
- **Lesson learned this project:** reiniting `RshipExt` drops the websocket (`_socketOpen`
  resets; `onConnect` must re-fire) and engine ids fall to the `td:` serviceId fallback until a
  connected refresh re-injects the instance. To hot-reload a module without that churn, refresh
  the accessor in place instead of reiniting:
  `ext.CompEngine = comp.op('local/modules/comp_engine').module`.

### Running code later / safely off-thread
- `td.run(scriptOrCallable, *args, delayFrames=, delayMilliSeconds=, endFrame=, fromOP=,
  group=, wallTime=)` → a `Run` object (`.kill()` to cancel). `td.runs` lists active runs.
- **Threading:** touch ops only on the cook/main thread. From a background thread, marshal work
  back with `td.run(..., fromOP=me)`. (Our websocket/exec-info I/O is done by TD's own
  WebSocket/Web Client/Timer DATs, with callbacks fed into Python — we never block.)

---

## 2. Operators, families, addressing

Everything is an `OP` (subclasses: `COMP`, `TOP`, `CHOP`, `SOP`, `DAT`, `MAT`, `POP`).

| Family | Purpose | Python data |
|--------|---------|-------------|
| TOP | GPU 2D textures | `.sample()`, `.numpyArray()`, `.save()` |
| CHOP | time-series channels | `op[chan]`, `.chans()`, `.numSamples`, exports/references |
| SOP | 3D geometry | `.points`, `.prims` |
| DAT | text/tables/Python | `[r,c]`, `.cell`, `.rows()`, `.module`, `.text` |
| MAT | materials/shaders | via `.par` |
| POP | particles | particle attrs |
| COMP | containers | `.children`, `.op`, `.ext`, `.seq`, `iop`/`ipar` |

**Addressing:** `op('/abs/path')`, `op('relativeChild')`, `op('a','b*')` (first match),
`parent()` / `parent(n)` / `parent.Shortcut`, `iop.name` (internal-op shortcut), `me`, `root`.
`op.Shortcut` raises if missing; `op('Shortcut')` returns None.

**Create / destroy / introspect:**
`comp.create(typeOrString, name)`, `comp.copy(src, name=)`, `op.destroy()` (then `.valid` is
False — **re-fetch, never reuse a destroyed ref**), `comp.findChildren(type=, tags=, parName=,
depth=)`, `.tags`, `.color`, `.nodeX/Y`, `.path/.id/.name/.digits`.

**Storage:** `op.store(key, val)` / `op.fetch(key, default, search=True)` / `op.unstore` —
persistent dict on an op (survives cooks; `.toe`-saved). `search=True` walks up parents.

---

## 3. Parameters — `Par`, `ParGroup`, `Page`, `Sequence`

### Par — the workhorse
- **Value vs eval:** `par.val` = the *constant-mode* value; `par.eval()` = the *current working
  value regardless of mode* (always use `eval()` to read). `par.expr` = the expression string.
- **Mode-setting side effects:** assigning `par.val = x` forces `CONSTANT`; assigning
  `par.expr = "..."` forces `EXPRESSION`. (So you rarely set `.mode` by hand.)
- **Eval variants:** `evalExpression()` (expr only — returns the raw Python return, e.g. a path
  string rather than an OP), `evalExport()`, `evalNorm()`, `evalOPs()`, `evalFile()→tdu.FileInfo`.
- **Menus:** `menuNames` / `menuLabels` (settable on custom), `menuIndex`, `menuSource` (an
  expression yielding a dynamic menu).
- **Misc:** `pulse(value=1, frames=0, seconds=0)`, `reset()`, `copy(otherPar)`, `destroy()`
  (custom/sequence only — *invalidates existing Par objects; re-fetch*), `isSamePar(other)`
  (**use this, not `==`**, which compares values), flags `isFloat/isInt/isMenu/isOP/...`,
  `style` ('Float','RGBA','Menu',…), `owner`, `parGroup`, `sequence`, `sequenceBlock`.

### ParGroup
A line of related Pars (e.g. `t` = tx,ty,tz; an RGBA). `.eval()` returns a **tuple**; `.val`/
`.expr`/`.mode` are tuples. Members addressed by suffix (`Sequence0float2r/g/b/a`).

### Page — creating custom parameters
`comp.appendCustomPage(name)` → `Page`. Then `page.appendFloat/Int/XY/XYZ/RGBA/Menu/Str/
Toggle/Pulse/OP/TOP/CHOP/DAT/...(name, label=, order=, replace=True)` → each returns a
**ParGroup**. Custom pars are saved in the `.toe`.

### Sequence / SequenceBlock — and the creation gotcha we hit
- `comp.seq.Name` → `Sequence`: `.numBlocks` (settable — grows/shrinks blocks),
  `.blocks`, `.blockPars` / `.blockParGroups` (templates), `.insertBlock/destroyBlock/
  reorderBlocks/sortBlocks`. Block i's par follows the name pattern `"<Seq><i><field>"` (e.g.
  `Sequence0float3`).
- **Gotcha (verified):** `page.appendSequence(name)` returns a **ParGroup**, and there is **no
  page-API way to add block FIELD pars** — `appendFloat` after it creates a standalone par, not
  a block field. Block fields are defined in the UI / `.toe`. *Workaround we used:* build the
  demo on a copy of a base that already has a real sequence, then drive/reflect it.

---

## 4. Expressions & binding — handing frame-rate updates to TD

This is the section that matters for the comp-engine wire-routing. The four `ParMode`s:

| Mode | Source | Set from Python | Clear | Re-evals |
|------|--------|-----------------|-------|----------|
| **CONSTANT** | `par.val` | `par.val = x` | (default) | only on write |
| **EXPRESSION** | `par.expr` (Python str) | `par.expr = "..."` (auto-mode) | `par.mode = ParMode.CONSTANT` | **every cook/frame** the op cooks |
| **EXPORT** | a CHOP channel / DAT cell pushes the value | (UI / op internals; `exportOP`/`exportSource` are read-only) | `par.mode = ParMode.CONSTANT` | **every frame** the source cooks (native C++ push) |
| **BIND** | another object's value (`par.bindExpr`) | `par.bindExpr = "op('x').par.Y"`, then `par.mode = ParMode.BIND` | `par.mode = ParMode.CONSTANT` | every cook; `bindMaster`/`bindReferences`/`bindRange` |

**To make a parameter live-update every frame from TD itself** (no Python in the per-frame
loop) — three options, cheapest first:

1. **CHOP Export** — a CHOP channel pushes into the par natively (C++). Most efficient for many
   frame-rate params from one CHOP; does **not** create a cook-dependency on the par expression.
   Set via the export mechanism, not a clean Python one-liner.
2. **CHOP-reference expression** — `par.expr = "op('lfo1')['chan1']"`. TD evaluates the
   reference each cook; creates a cook dependency on the CHOP. Clean to set from Python, flexible
   (can do math), and the canonical way to "author a TD par expr."
3. **Python par.expr** — `par.expr = "(math.sin(absTime.seconds*2)*0.5+0.5)*0.7"`. TD runs the
   Python string each cook. Highest per-eval overhead, but fully general and trivially set/cleared
   from Python.

**Implication for our comp-mixer:** instead of Python re-projecting a wired par every tick, set
`par.expr` once (on topology/cap change) to a TD expression that references the producer's output
(a CHOP channel / op value) — then **TD's cook engine does the per-frame updates**. Python only
re-binds when the wiring or a baked coefficient changes. Setting `par.expr` auto-enters
EXPRESSION mode; clear with `par.mode = ParMode.CONSTANT`. (This is exactly the next build step.)

---

## 5. Cooking & dependencies

- An op **cooks** = re-evaluates inputs/params and produces output, propagating downstream.
- **Triggers:** an input cooked; an expression/export/bind the op reads changed; a forced
  `op.cook(force=True)`; `par.pulse()`. **Reading `par.eval()` inside an expression creates a
  dynamic dependency** on that source.
- **Does NOT cook:** writing `par.val = x` (constant) by itself; changing par metadata.
- Cook order is topologically sorted (inputs before outputs). Expression-mode params re-evaluate
  every frame the op cooks. This is how a `par.expr` referencing `absTime`/a CHOP animates "for
  free" once set.
- Inspect: `.cookedThisFrame`, `.cookFrame`, `.cpuCookTime`, `.totalCooks`, `.allowCooking`.

---

## 6. Data access (brief)

- **CHOP:** `op('c')[chanIndexOrName]` → `Channel`; `chan[i]` sample, `chan.eval()`,
  `chan.average/min/max`, `chan.numpyArray()`; CHOP-level `.numChans/.numSamples/.rate`,
  `op.numpyArray()` (2D). `Channel.vals` writable only in a Script CHOP.
- **DAT:** `op('t')[r,c]` → `Cell` (auto-coerces; use `.val` for the guaranteed string),
  `.row()/.col()/.rows()/.cols()`, `appendRow/appendCol/replaceRow/clear/setSize`, `.text`
  (tab/newline), `.csv`, `.jsonObject`.
- **TOP:** `.sample(x,y|u,v)` (expensive — GPU stall), `.numpyArray(delayed=True)`, `.save()`.

---

## 7. Timing

- `absTime` — global, monotonic, identical across nodes, unaffected by timeline pause:
  `.frame`, `.seconds`, `.step`, `.stepSeconds`. Use for deterministic per-frame values.
- `me.time` (Timeline) — local to parent COMP, respects play/rate: `.frame`, `.seconds`,
  `.rate`, `.play`.
- `project.cookRate` — target FPS.

---

## 8. `tdu` utilities (the useful ones)

`Vector` / `Position` / `Quaternion` / `Matrix` (4x4, column-major) / `Color(r,g,b,a)`;
`clamp(v,lo,hi)`, `remap(v,a,b,c,d)`, `rand(seed)` (deterministic — `rand(absTime.frame)` for
per-frame, `rand(me)` for per-op), `tryExcept(fn, fallback)`; `legalName/validName/validPath`,
`base/digits`, `expand('A[1-3]')`, `match(pattern,list)`, `split`; `expandPath/collapsePath`,
`FileInfo`; `TableMenu(dat)` / `ParMenu(names,labels)` for `par.menuSource`;
`Dependency(initial)` — a value wrapper that auto-dirties dependent expressions on change.

---

## 9. Gotchas that have actually bitten this project

1. **Module epochs** → use `td`-anchored singletons (§1). The single most important pattern here.
2. **Extension re-init drops state + churns the connection** → refresh accessors in place; only
   reinit when necessary, and recover the socket cleanly afterward.
3. **Never `_updateConfiguration(None, None)` to "force" identity** — its `rshipUrl=None` path
   falls back to the manual Address (no `/myko`) and clobbers the good exec-info URL.
4. **`isSamePar`, not `==`** for parameter identity; same for `isSameParGroup`.
5. **Destroyed ops/pars invalidate refs** — re-fetch after `destroy()`/`changeType()`.
6. **Sequence block fields can't be created via the page API** (§3) — reuse an existing sequence.
7. **Color/Vec on the wire send whole-number channels as Int** — coerce Int↔Float when comparing
   (we deep-coerce in `_values_equivalent`; the server's `equivalent()` got the matching fix).
8. **Expressions must be side-effect free** — they run many times per cook; put side effects in
   callbacks / `td.run`.

---

## 10. Relevance to rship-touchdesigner / comp-engine

- **Caps = Properties on the value plane** (SetCap action + cap readback emitter), driven by
  TD's parameter machinery. **committed_state/topology = the apply plane.**
- **Wire-routing / comp-mixer (next step):** a producer exposes its output as a TD-evaluable
  reference; the consumer's wired par binds via `par.expr` (EXPRESSION mode) so the **TD cook
  engine handles per-frame updates** instead of Python re-projecting every tick. Python re-binds
  the expression only on topology/cap change. See `comp_engine.OutputExpr` / `ctx.bind_output`
  (in progress) and `SequenceReflector(..., wired={...})`.
- **The `td`-singleton pattern** underpins the cross-engine output registry (`td._rship_outputs`)
  and the engine registry (`td._rship_engines`), so cross-engine resolve works across module
  epochs in one process.
