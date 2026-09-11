import importlib.util
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

SPEC = importlib.util.spec_from_file_location('native_view_exec', MOD_DIR / 'exec.py')
EXEC = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EXEC)


class NativeViewTests(unittest.TestCase):
    def setUp(self):
        self.frames = []
        self.changes = []
        self.client = EXEC.ExecClient()
        self.client.log = lambda message: None
        self.client.setSend(lambda text: self.frames.append(json.loads(text)))
        self.view = self.client.watchViewMap(
            'properties', 'ReconciledProperties', 'ReconciledProperty',
            {'instanceId': 'instance', 'targetIds': ['root']},
            lambda view, change: self.changes.append(change),
        )

    def response(self, sequence, upserts=(), deletes=()):
        self.client.parseViewResponse({
            'tx': self.view.tx, 'sequence': sequence,
            'upserts': [{'itemType': 'ReconciledProperty', 'item': item} for item in upserts],
            'deletes': list(deletes),
        })

    def test_subscription_envelope_and_reconnect_reuse_tx(self):
        self.client.resubscribeViews()
        self.client.disconnectViews()
        self.client.resubscribeViews()

        self.assertEqual(self.frames[0]['event'], 'ws:m:view')
        self.assertEqual(self.frames[0]['data']['viewId'], 'ReconciledProperties')
        self.assertEqual(self.frames[0]['data']['view']['targetIds'], ['root'])
        self.assertEqual(self.frames[0]['data']['view']['tx'], self.frames[1]['data']['view']['tx'])

    def test_reset_and_delta_are_atomic(self):
        self.response(0, [{'id': 'a'}, {'id': 'b'}])
        self.response(1, [{'id': 'b', 'value': 2}, {'id': 'c'}], ['a', 'b'])

        self.assertTrue(self.view.ready)
        self.assertEqual(dict(self.view.rows), {'b': {'id': 'b', 'value': 2}, 'c': {'id': 'c'}})
        self.assertEqual(len(self.changes), 2)

    def test_invalid_response_preserves_cache_and_marks_unready(self):
        self.response(0, [{'id': 'a'}])
        self.response(2, [{'id': 'b'}])

        self.assertEqual(dict(self.view.rows), {'a': {'id': 'a'}})
        self.assertFalse(self.view.ready)
        self.assertIn('Out-of-order', self.view.error)

    def test_hot_reload_replaces_callback_without_new_view(self):
        calls = []
        same = self.client.watchViewMap(
            'properties', 'ReconciledProperties', 'ReconciledProperty',
            {'instanceId': 'instance', 'targetIds': ['root']},
            lambda view, change: calls.append(change),
        )
        self.assertIs(same, self.view)
        self.response(0, [{'id': 'a'}])
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.changes, [])


if __name__ == '__main__':
    unittest.main()
