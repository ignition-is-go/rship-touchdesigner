import importlib.util
import builtins
from pathlib import Path
import sys
import types
import unittest


ROOT = Path(__file__).parents[1]
MOD_DIR = ROOT / "py" / "mod"
if str(MOD_DIR) not in sys.path:
    sys.path.insert(0, str(MOD_DIR))

td_stub = types.ModuleType("td")
td_stub.OP = type("OP", (), {})
td_stub.ParGroup = type("ParGroup", (), {})
sys.modules.setdefault("td", td_stub)
builtins.OP = td_stub.OP
builtins.ParGroup = td_stub.ParGroup


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


SEQUENCE_TARGET = load_module(
    "sequence_target_under_test",
    MOD_DIR / "sequence_target.py",
)


class SequenceTargetIdTests(unittest.TestCase):
    def make_target(self, page_name, sequence_name):
        target = SEQUENCE_TARGET.SequenceTarget.__new__(SEQUENCE_TARGET.SequenceTarget)
        target.opTargetId = "op-id"
        target.parentId = f"op-id:{page_name}"
        target.sequence = types.SimpleNamespace(name=sequence_name)
        return target

    def test_namespaces_sequence_when_legacy_id_collides_with_page(self):
        target = self.make_target("Sampler", "Sampler")

        self.assertEqual(target.id, "op-id:Sequence:Sampler")

    def test_preserves_legacy_sequence_id_without_page_collision(self):
        target = self.make_target("Generators", "Generator")

        self.assertEqual(target.id, "op-id:Generator")


if __name__ == "__main__":
    unittest.main()
