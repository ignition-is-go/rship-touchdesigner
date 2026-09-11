import builtins
import importlib
import json
import sys
import types
import unittest
from pathlib import Path


MOD_DIR = Path(__file__).parents[1] / 'py' / 'mod'
if str(MOD_DIR) not in sys.path:
    sys.path.insert(0, str(MOD_DIR))
td_stub = sys.modules.setdefault('td', types.ModuleType('td'))
td_stub.OP = type('OP', (), {})
td_stub.ParGroup = type('ParGroup', (), {})
sys.modules.setdefault('tdu', types.SimpleNamespace(Dependency=lambda value: value))
builtins.OP = td_stub.OP
builtins.ParGroup = td_stub.ParGroup
builtins.ParMode = types.SimpleNamespace(CONSTANT='constant', EXPRESSION='expression')

COMP = importlib.import_module('comp_engine')
EXEC = importlib.import_module('exec')


class Log:
    def Debug(self, *args): pass
    Info = Debug
    Warning = Debug
    Error = Debug


class Handler:
    def __init__(self): self.triggers = []
    def on_button_pressed(self, instance, trigger_id, payload):
        self.triggers.append((instance, trigger_id, payload))


class Engine:
    id = 'engine'
    def __init__(self):
        self.handler = Handler()
        self.args = types.SimpleNamespace(
            kind_registry=types.SimpleNamespace(handlers={'demo': self.handler}))
        self._slots = {}
        self.renders = []
        self.values = []

    def _render(self, assignment, transaction_id):
        self.renders.append(assignment)
        self._slots = {}
        for slot in assignment['slotStates']:
            element_id = slot['boundInstance']['compElementId']
            self._slots[element_id] = {
                'slot': slot,
                'state': {'bag': {v['capId']: v['value'] for v in slot['capValues']},
                          'presence': slot.get('presence')},
            }

    def _reproject(self, element_id, change):
        self.values.append((element_id, change))


def row(kind, key_extra, value_extra):
    key = {'rowKind': kind, 'engineId': 'engine',
           'element': {'compElementId': 'node'}}
    key.update(key_extra)
    value = {'rowKind': kind}
    value.update(value_extra)
    return {'id': COMP._required_key_id(key), 'key': key, 'value': value}


class RequiredCompStateTests(unittest.TestCase):
    def setUp(self):
        COMP.op = types.SimpleNamespace(RS_LOG=Log())
        self.frames = []
        self.client = EXEC.ExecClient()
        self.client.log = lambda message: None
        self.client.setSend(lambda text: self.frames.append(json.loads(text)))
        self.instance = types.SimpleNamespace(id='render-09:RshipTox')
        self.engine = Engine()
        self.controller = COMP.RequiredCompEngineController()
        self.controller.replace_engines(self.client, self.instance, [self.engine])

    def apply(self, rows, reset=True, upserts=()):
        view = types.SimpleNamespace(ready=True, rows={r['id']: r for r in rows})
        change = types.SimpleNamespace(reset=reset, upsertedIds=frozenset(upserts))
        self.controller.view_changed(view, change)
        return view

    def rows(self, cap_value=42):
        return [
            row('element', {}, {'kind': 'demo', 'wireInputs': [], 'orderIndex': None,
                                'caps': ['level'], 'triggers': ['reset'], 'singleton': False}),
            row('cap', {'capId': 'level'}, {'value': cap_value}),
            row('presence', {}, {'weight': 1}),
        ]

    def test_ids_count_utf8_bytes(self):
        key = {'rowKind': 'element', 'engineId': 'é',
               'element': {'compElementId': '火'}}
        self.assertEqual(COMP._required_key_id(key), 'element:2:é3:火')

    def test_output_id_preserves_compatibility_segment_without_instance_tag(self):
        self.assertEqual(
            COMP._output_emitter_id('service:engine', {'compElementId': 'node'}, 'color'),
            'service:engine:output:node::color',
        )

    def test_cap_delta_does_not_structurally_render(self):
        self.apply(self.rows(42))
        self.apply(self.rows(43), reset=False)

        self.assertEqual(len(self.engine.renders), 1)
        self.assertEqual(self.engine.values[-1][1],
                         {'what': 'cap', 'cap_id': 'level', 'value': 43})

    def test_ready_observation_copies_exact_element_value(self):
        rows = self.rows()
        self.apply(rows)
        events = [frame['data'] for frame in self.frames if frame['event'] == 'ws:m:event']
        ready = next(event['item'] for event in events
                     if event['item'].get('value', {}).get('phase') == 'ready')
        self.assertEqual(ready['elementValue'], rows[0]['value'])
        self.assertNotIn('clientId', ready)

    def test_trigger_is_deduplicated(self):
        view = self.apply(self.rows())
        self.controller.view = view
        command = {'instanceId': self.instance.id, 'engineId': 'engine',
                   'element': {'compElementId': 'node'}, 'triggerId': 'reset',
                   'eventId': 'event', 'payload': 9}
        self.controller.deliver_trigger(command)
        self.controller.deliver_trigger(command)
        self.assertEqual(len(self.engine.handler.triggers), 1)


if __name__ == '__main__':
    unittest.main()
