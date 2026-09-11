import builtins
import importlib
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
MOD_DIR = ROOT / "py" / "mod"
if str(MOD_DIR) not in sys.path:
    sys.path.insert(0, str(MOD_DIR))

td_stub = sys.modules.setdefault("td", types.ModuleType("td"))
td_stub.OP = type("OP", (), {})
td_stub.ParGroup = type("ParGroup", (), {})
builtins.ParMode = types.SimpleNamespace(CONSTANT="constant")

par_shape = importlib.import_module("par_shape")


class FakePar:
    def __init__(self, value=None):
        self.value = value
        self.pulses = 0

    def eval(self):
        return self.value

    def pulse(self):
        self.pulses += 1


class FakePars(dict):
    def __setitem__(self, key, value):
        if key in self and not isinstance(value, FakePar):
            dict.__getitem__(self, key).value = value
            return
        dict.__setitem__(self, key, value)


class FakeSequence:
    def __init__(self, owner, members, count=1, maximum=3):
        self.owner = owner
        self.name = "Generator"
        self.members = members
        self.maxBlocks = maximum
        self.blocks = []
        self.resize_calls = []
        self.numBlocks = count
        self.resize_calls.clear()

    def group(self, index, name, style, default):
        group = types.SimpleNamespace(
            name=f"Generator{index}{name}",
            style=style,
            size=1,
            subLabel=[],
            sequence=self,
            sequenceIndex=index,
        )
        if group.name not in self.owner.par:
            self.owner.par[group.name] = FakePar(default)
        return group

    @property
    def numBlocks(self):
        return len(self.blocks)

    @numBlocks.setter
    def numBlocks(self, count):
        self.resize_calls.append(count)
        self.blocks = [
            [self.group(index, *member) for member in self.members]
            for index in range(count)
        ]


def make_shape(state_only=False, count=1, maximum=3):
    owner = types.SimpleNamespace(path="/sequence", par=FakePars())
    members = [
        ("Value", "Float", 0.25),
        ("Emit", "Pulse", None),
    ]
    sequence = FakeSequence(owner, members, count=count, maximum=maximum)
    header = types.SimpleNamespace(name="Generator", style="Sequence", sequence=sequence)
    templates = [sequence.group(0, *member) for member in members]
    kwargs = {"sequenceParGroups": [header, *templates]}
    if state_only:
        kwargs["stateOnly"] = True
    shape = par_shape.SequenceParShape(owner, header, **kwargs)
    return shape, sequence


class SequenceStateTests(unittest.TestCase):
    def test_invalid_later_block_does_not_resize(self):
        shape, sequence = make_shape(count=1)

        with self.assertRaisesRegex(ValueError, "block 1"):
            shape.setData([{"Value": 1.0}, []])

        self.assertEqual(sequence.numBlocks, 1)
        self.assertEqual(sequence.resize_calls, [])

    def test_state_schema_and_readback_exclude_triggers(self):
        shape, _ = make_shape(state_only=True)

        schema = shape.buildSchemaProperties()
        data = shape.buildData()

        self.assertEqual(set(schema["items"]["properties"]), {"Value"})
        self.assertEqual(data, [{"Value": 0.25}])

    def test_state_count_is_validated_before_resize(self):
        shape, sequence = make_shape(state_only=True, count=1, maximum=2)

        for payload in ([], [{"Value": 1}, {"Value": 2}, {"Value": 3}]):
            with self.assertRaises(ValueError):
                shape.setData(payload)

        self.assertEqual(sequence.numBlocks, 1)
        self.assertEqual(sequence.resize_calls, [])


if __name__ == "__main__":
    unittest.main()
