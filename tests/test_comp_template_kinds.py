import builtins
import importlib
import sys
import types
import unittest
from pathlib import Path


MOD_DIR = Path(__file__).parents[1] / 'py' / 'mod'
if str(MOD_DIR) not in sys.path:
    sys.path.insert(0, str(MOD_DIR))
td_stub = sys.modules.setdefault('td', types.ModuleType('td'))
td_stub.OP = getattr(td_stub, 'OP', type('OP', (), {}))
td_stub.ParGroup = getattr(td_stub, 'ParGroup', type('ParGroup', (), {}))
sys.modules.setdefault('tdu', types.SimpleNamespace(Dependency=lambda value: value))
builtins.OP = td_stub.OP
builtins.ParGroup = td_stub.ParGroup
builtins.ParMode = types.SimpleNamespace(CONSTANT='constant', EXPRESSION='expression')

COMP = importlib.import_module('comp_engine')


class FakePar:
    def __init__(self, value, default=None):
        self.val = value
        self.default = value if default is None else default
        self.mode = builtins.ParMode.CONSTANT
        self.pulses = 0

    def eval(self):
        return self.val

    def pulse(self):
        self.pulses += 1


class FakeParGroup(list):
    def __init__(self, name, style, value=0, label=None):
        super().__init__([FakePar(value)])
        self.name = name
        self.style = style
        self.label = label or name
        self.sequence = None


class FakePage:
    def __init__(self, name, groups):
        self.name = name
        self.parGroups = groups


class FakeEndpoint:
    def __init__(self, name, family):
        self.name = name
        self.family = family


class FakeConnector:
    def __init__(self, direction, index, name, family):
        self.index = index
        self.description = name
        self.inOP = FakeEndpoint(name, family) if direction == 'in' else None
        self.outOP = FakeEndpoint(name, family) if direction == 'out' else None
        self.connected_to = None
        self.disconnects = 0

    def connect(self, target):
        self.connected_to = target

    def disconnect(self):
        self.connected_to = None
        self.disconnects += 1


class FakePars:
    def __init__(self, values):
        self.values = values

    def __getitem__(self, name):
        return self.values.get(name)

    def __getattr__(self, name):
        return self.values.get(name)


class FakeBase:
    OPType = 'baseCOMP'
    valid = True

    def __init__(self, path, kind_id=None, inputs=(), outputs=(), controls=()):
        self.path = path
        self.name = path.rsplit('/', 1)[-1]
        metadata = []
        if kind_id is not None:
            metadata.append(FakeParGroup('Kindid', 'Str', kind_id))
        self.customPages = [FakePage(COMP.RSHIP_KIND_PAGE, metadata),
                            FakePage('Controls', list(controls))]
        self.par = FakePars({pg.name: pg[0] for page in self.customPages for pg in page.parGroups})
        self.inputConnectors = [FakeConnector('in', i, name, family)
                                for i, (name, family) in enumerate(inputs)]
        self.outputConnectors = [FakeConnector('out', i, name, family)
                                 for i, (name, family) in enumerate(outputs)]
        self.tags = set()
        self.storage = {}
        self.children = []
        self.destroyed = False

    def op(self, name):
        return None

    def findChildren(self, tags):
        tag = tags[0]
        return [child for child in self.children if tag in child.tags]

    def store(self, key, value):
        self.storage[key] = value

    def destroy(self):
        self.destroyed = True
        self.valid = False

    def clone_for(self, path):
        controls = [FakeParGroup(pg.name, pg.style, pg[0].eval(), pg.label)
                    for pg in self.customPages[1].parGroups]
        return FakeBase(
            path,
            inputs=[(c.description, c.inOP.family) for c in self.inputConnectors],
            outputs=[(c.description, c.outOP.family) for c in self.outputConnectors],
            controls=controls,
        )


class FakeParent(FakeBase):
    def __init__(self, path='/runtime'):
        super().__init__(path)
        self.copies = []

    def copy(self, template, name):
        replica = template.clone_for(self.path + '/' + name)
        self.copies.append(replica)
        return replica


def port(direction, port_id, index, **extra):
    row = {'direction': direction, 'id': port_id, 'index': index}
    row.update(extra)
    return row


class TemplateKindTests(unittest.TestCase):
    def setUp(self):
        td_stub.baseCOMP = FakeBase
        if hasattr(COMP.td, '_rship_native_output_ports'):
            COMP.td._rship_native_output_ports.clear()

    def test_engine_requires_base_and_contained_templates(self):
        owner = FakeBase('/engine')
        inside = FakeBase('/engine/kinds/source', kind_id='source')
        outside = FakeBase('/elsewhere/source', kind_id='source')
        registry = COMP.KindRegistryBuilder().register_base(inside).build()
        args = COMP.CompEngineArgs('engine', 'Engine', registry,
                                   replica_parent=FakeBase('/engine/instances'))
        COMP._validate_engine_layout(owner, args)
        with self.assertRaisesRegex(ValueError, 'must be a BASE'):
            COMP._validate_engine_layout(types.SimpleNamespace(OPType='containerCOMP'), args)
        args.kind_registry = COMP.KindRegistryBuilder().register_base(outside).build()
        with self.assertRaisesRegex(ValueError, 'must live inside'):
            COMP._validate_engine_layout(owner, args)
        args.kind_registry = registry
        args.replica_parent = FakeBase('/elsewhere')
        with self.assertRaisesRegex(ValueError, 'replica_parent'):
            COMP._validate_engine_layout(owner, args)
        args.replica_parent = None
        args.kind_registry = COMP.KindRegistryBuilder().register(
            COMP.KindDefBuilder('code', 'Code', 'CompElementClipPayload').build()).build()
        with self.assertRaisesRegex(ValueError, 'every comp-engine kind'):
            COMP._validate_engine_layout(owner, args)

    def test_self_describing_base_reflects_controls_and_native_ports(self):
        template = FakeBase(
            '/templates/filter', kind_id='video.filter',
            inputs=[('image', 'TOP')], outputs=[('image', 'TOP')],
            controls=[FakeParGroup('Gain', 'Float', 0.5), FakeParGroup('Reset', 'Pulse')],
        )
        spec = COMP.BaseKindSpec.reflect(template, ports=[
            port('in', 'image', 0, channel='image', accepts='video.source', requiredMin='1'),
            port('out', 'image', 0, schema='Texture', semantic='texture'),
        ])

        wire = spec.kind.to_wire()
        self.assertEqual(wire['id'], 'video.filter')
        self.assertEqual([cap['cap']['id'] for cap in wire['capSchema']], ['Gain'])
        self.assertEqual([trigger['id'] for trigger in wire['triggerSchema']], ['Reset'])
        self.assertEqual(wire['inputs'][0]['accepts'], {
            'level': 'element', 'kinds': ['video.source'], 'channel': 'image'})
        self.assertEqual(wire['outputChannels'][0]['schemaRef'], COMP.schema('Texture'))

    def test_registry_composes_children_tags_and_code_kinds(self):
        root = FakeBase('/templates')
        child = FakeBase('/templates/a', kind_id='a')
        tagged = FakeBase('/templates/b', kind_id='b')
        tagged.tags.add(COMP.RSHIP_KIND_TAG)
        root.children = [tagged, child]
        code_kind = COMP.KindDefBuilder('code', 'Code', 'CompElementClipPayload').build()

        registry = (COMP.KindRegistryBuilder()
                    .register_children(root)
                    .register_with_handler(code_kind, object())
                    .build())
        self.assertEqual(set(registry.kinds), {'a', 'b', 'code'})
        self.assertEqual(set(registry.templates), {'a', 'b'})
        self.assertEqual(COMP.tagged_kind_bases(root), (tagged,))

    def test_materializer_copies_by_opaque_id_updates_cap_and_wires(self):
        source = FakeBase('/templates/source', kind_id='source', outputs=[('signal', 'CHOP')])
        sink = FakeBase('/templates/sink', kind_id='sink', inputs=[('signal', 'CHOP')],
                        controls=[FakeParGroup('Gain', 'Float', 1.0)])
        source_spec = COMP.BaseKindSpec.reflect(source, ports=[
            port('out', 'signal', 0, schema='Signal', semantic='signal')])
        sink_spec = COMP.BaseKindSpec.reflect(sink, ports=[
            port('in', 'signal', 0, channel='signal', accepts='source')])
        registry = (COMP.KindRegistryBuilder().register_base(source_spec)
                    .register_base(sink_spec).build())
        parent = FakeParent()
        templates = {source.path: source, sink.path: sink}
        old_op = getattr(COMP, 'op', None)
        COMP.op = lambda path: templates.get(path)
        try:
            engine = types.SimpleNamespace(
                id='engine', key='/owner:engine', ownerComp=FakeBase('/'),
                args=types.SimpleNamespace(kind_registry=registry, replica_parent=parent),
                _slots={
                    'source::opaque': {
                        'slot': {'kind': 'source', 'boundInstance': {'compElementId': 'source::opaque'},
                                 'wireInputValues': []},
                        'state': {'bag': {}, 'presence': 1.0},
                    },
                    'sink:also:opaque': {
                        'slot': {'kind': 'sink', 'boundInstance': {'compElementId': 'sink:also:opaque'},
                                 'wireInputValues': [{
                                     'pinId': 'signal',
                                     'source': {'sourceEngineId': 'engine',
                                                'sourceInstance': {'compElementId': 'source::opaque'},
                                                'outputChannelId': 'signal'},
                                 }]},
                        'state': {'bag': {'Gain': 0.25}, 'presence': 1.0},
                    },
                },
            )
            materializer = COMP.BaseReplicaMaterializer(engine)
            materializer.reconcile()

            source_replica = materializer.replicas['source::opaque']['op']
            sink_replica = materializer.replicas['sink:also:opaque']['op']
            self.assertIs(source_replica.outputConnectors[0].connected_to,
                          sink_replica.inputConnectors[0])
            self.assertEqual(_group(sink_replica, 'Gain')[0].eval(), 0.25)
            self.assertEqual(sink_replica.storage['rship_comp_element_id'], 'sink:also:opaque')

            materializer.apply_value('sink:also:opaque', {
                'what': 'cap', 'cap_id': 'Gain', 'value': 0.75})
            self.assertEqual(_group(sink_replica, 'Gain')[0].eval(), 0.75)

            engine._slots = {}
            materializer.reconcile()
            self.assertTrue(source_replica.destroyed)
            self.assertTrue(sink_replica.destroyed)
        finally:
            if old_op is None:
                delattr(COMP, 'op')
            else:
                COMP.op = old_op


def _group(comp, name):
    return next(pg for page in comp.customPages for pg in page.parGroups if pg.name == name)


if __name__ == '__main__':
    unittest.main()
