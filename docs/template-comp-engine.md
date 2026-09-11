# Author a comp engine from template BASEs

Use template kinds when each RShip comp element must become a BASE in a TouchDesigner network. The comp engine copies one template BASE per assigned element and connects those copies with native TouchDesigner wires.

Every comp engine must be a BASE. Every registered kind must have a template BASE inside that engine, and its generated instances must stay inside the engine too. Registration rejects layouts that violate these rules.

## Create a template BASE

Create a `baseCOMP` for each kind. Build the operator network inside the BASE, then expose its data connections with the normal In and Out operators.

Add a custom page named `Rship Kind`. Add these parameters to the page:

- `Kindid`: A stable, nonempty string. RShip treats this value as opaque.
- `Displayname`: The label shown to an author. If this parameter is empty, the BASE name is used.
- `Instanceability`: Either `instanceable` or `singleton`. The default is `instanceable`.
- `Instanceordering`: Either `unordered` or `ordered`. The default is `unordered`.
- `Maxinstances`: A positive integer, or `0` for no limit.

The reflector excludes the `Rship Kind` page from the cap schema. On every other custom page, the reflector maps Constant-mode value parameters to caps and Pulse or Momentary parameters to triggers. It skips expression, export, and bind parameters because RShip cannot reconcile them by writing a value.

To discover the BASE with `register_tagged()`, add the `rship-comp-kind` tag.

## Declare connector semantics

The reflector reads the BASE's left and right operator connectors. TouchDesigner supplies each connector's index, description, and operator family. RShip also needs a stable port ID and the logical channel accepted by each input.

For explicit port metadata, add a Table DAT named `rship_kind_ports` inside the template. Use this header:

```text
direction	id	index	displayName	schema	semantic	accepts	channel	fanIn	ordering	requiredMin
```

Add one row for each external connector. An input row uses `accepts`, `channel`, `ordering`, and `requiredMin`. An output row uses `schema` and `semantic`.

```text
in	image	0	Image			video.source	image	false	unordered	1
out	image	0	Image	Texture	texture			false	unordered	
```

Separate multiple accepted kind IDs with commas. The generic BASE materializer supports one source per input, so `fanIn` must be false.

If the table is absent, the reflector uses the connector description or the In or Out operator name as the port ID. It maps TOP outputs to `Texture` and CHOP outputs to `Signal`. Other output families need an explicit table row with `schema` and `semantic`.

## Register template kinds

Register the templates contained by the engine BASE:

```python
ce = op.RSHIP.CompEngine

registry = (
	ce.KindRegistryBuilder()
	.register_children(me.op('kinds'))
	.build()
)

engine = ce.comp_engine(me, ce.CompEngineArgs(
	short_id='visual-engine',
	display_name='Visual Engine',
	kind_registry=registry,
	host_target=op.RSHIP.Api.target(me, 'Visual Engine'),
	replica_parent=me.op('instances'),
))
```

`register_children()` reads direct child BASEs. `register_tagged()` reads tagged descendant BASEs. `register_base()` registers one BASE. `register_all()` accepts an explicit iterable of BASEs and `BaseKindSpec` values.

All discovery paths compile to `BaseKindSpec` and then use the existing `KindDef` wire format. A duplicate `Kindid` stops registration. Python declarations still need an internal template BASE. A code-only handler cannot bypass this requirement.

For code-owned metadata, build a spec directly:

```python
spec = ce.BaseKindSpec.reflect(
	me.op('kinds/noise'),
	kind_id='video.noise',
	ports=[
		{'direction': 'out', 'id': 'image', 'index': 0,
		 'schema': 'Texture', 'semantic': 'texture'},
	],
)

registry = ce.KindRegistryBuilder().register_base(spec).build()
```

## Runtime ownership

Set `replica_parent` to a BASE that the comp engine owns. If you omit it, the engine copies instances under `ownerComp`.

The runtime stores the full `compElementId` on each managed copy. The local operator name contains a safe kind slug and a hash, but the runtime never reads identity from that name. Required-state row IDs and element IDs remain opaque.

On a structural update, the runtime creates all required copies before it connects wires. A cap update writes only the matching parameter on the existing copy. Removing an element disconnects its managed inputs, unregisters its output endpoints, and destroys its managed copy.

The saved demo lives at `/rship_source/comp_engine_demo`. Its `kinds` BASE contains `source` and `layer`, and its `instances` BASE contains generated copies. Call `op('/rship_source/comp_engine_demo').ext.DemoExt.Preview()` to create a local preview with source value 2 and layer gain 3. The layer outputs 6 through a native CHOP wire. RShip assignments replace this preview.

The previous sequence examples are preserved under `/rship_source/legacy_comp_examples` with their extensions disabled. They are no longer registered engines.

Native wires require compatible connectors and a shared TouchDesigner network. The demo puts both generated BASEs under `instances`.
