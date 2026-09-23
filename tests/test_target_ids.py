import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest


spec = importlib.util.spec_from_file_location('target_id_util', Path(__file__).parents[1] / 'py/mod/util.py')
util = importlib.util.module_from_spec(spec)
spec.loader.exec_module(util)


def owner(number, identity):
    return SimpleNamespace(id=number, storage={'rs_target_id': identity})


class TargetIdentityTests(unittest.TestCase):
    def test_registered_owner_keeps_identity_even_when_copy_is_scanned_first(self):
        original, copied = owner(20, 'existing'), owner(10, 'existing')
        changes = util.ensureUniqueTargetIds([copied, original], {'existing': SimpleNamespace(ownerComp=original)})
        self.assertEqual(original.storage['rs_target_id'], 'existing')
        self.assertNotEqual(copied.storage['rs_target_id'], 'existing')
        self.assertEqual(len(changes), 1)
        self.assertEqual(util.ensureUniqueTargetIds([copied, original], {}), [])

    def test_initial_scan_keeps_oldest_owner_and_repairs_multiple_copies(self):
        original, a, b = owner(1, 'existing'), owner(2, 'existing'), owner(3, 'existing')
        util.ensureUniqueTargetIds([b, a, original], {})
        self.assertEqual(original.storage['rs_target_id'], 'existing')
        self.assertEqual(len({o.storage['rs_target_id'] for o in [original, a, b]}), 3)

    def test_unique_and_unassigned_owners_are_unchanged(self):
        owners = [owner(1, 'one'), owner(2, 'two'), owner(3, None)]
        self.assertEqual(util.ensureUniqueTargetIds(owners, {}), [])
        self.assertEqual([o.storage['rs_target_id'] for o in owners], ['one', 'two', None])
