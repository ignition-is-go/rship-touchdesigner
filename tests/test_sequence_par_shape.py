import importlib.util
from pathlib import Path
import sys
import types
import unittest


TD_STUB = types.ModuleType("td")
TD_STUB.OP = type("OP", (), {})
TD_STUB.ParGroup = type("ParGroup", (), {})
sys.modules.setdefault("td", TD_STUB)

MODULE_PATH = Path(__file__).parents[1] / "py" / "mod" / "par_shape.py"
SPEC = importlib.util.spec_from_file_location("rship_par_shape", MODULE_PATH)
PAR_SHAPE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PAR_SHAPE)


class FakeParGroup:
    def __init__(self, style, size=1, name="Member"):
        self.style = style
        self.size = size
        self.name = name

    @property
    def menuNames(self):
        raise AssertionError("value wrapping must not evaluate menu metadata")


class FakeBlockShape:
    def __init__(self, current_value):
        self.current_value = current_value
        self.build_calls = 0
        self.set_calls = []

    def buildData(self):
        self.build_calls += 1
        return {"value": self.current_value}

    def setData(self, data):
        self.set_calls.append(data)
        if isinstance(data, dict) and list(data.keys()) == ["value"]:
            self.current_value = data["value"]
        else:
            self.current_value = data


class FakeSequence:
    def __init__(self, num_blocks, blocks, name="Sequence"):
        self.name = name
        self._num_blocks = num_blocks
        self.num_blocks_assignments = 0
        self.blocks = blocks

    @property
    def numBlocks(self):
        return self._num_blocks

    @numBlocks.setter
    def numBlocks(self, value):
        self.num_blocks_assignments += 1
        self._num_blocks = value


class FakeSequenceParGroup:
    def __init__(self, sequence):
        self.sequence = sequence


class RewrappingSequenceParGroup:
    """Mimic TD returning a fresh sequence proxy on each property access."""

    def __init__(self, num_blocks, blocks, name="Sequence"):
        self.num_blocks = num_blocks
        self.blocks = blocks
        self.name = name

    @property
    def sequence(self):
        return FakeSequence(self.num_blocks, self.blocks, self.name)


class CountingBlock:
    def __init__(self, members):
        self.members = members
        self.iterations = 0

    def __iter__(self):
        self.iterations += 1
        return iter(self.members)


class SequenceParShapeTests(unittest.TestCase):
    def test_menu_value_wrapping_does_not_read_menu_metadata(self):
        shape = PAR_SHAPE.SequenceParShape(ownerComp=None, parGroup=None)
        menu_group = FakeParGroup("Menu")

        self.assertEqual(
            shape._wrapSequenceMemberData(menu_group, "option-a"),
            {"value": "option-a"},
        )

    def test_supported_scalar_styles_keep_the_value_envelope(self):
        shape = PAR_SHAPE.SequenceParShape(ownerComp=None, parGroup=None)
        scalar_groups = [
            FakeParGroup("Float"),
            FakeParGroup("Int"),
            FakeParGroup("Str"),
            FakeParGroup("Toggle"),
            FakeParGroup("Pulse"),
            FakeParGroup("Momentary"),
            FakeParGroup("Menu"),
            FakeParGroup("StrMenu"),
            FakeParGroup("File"),
        ]

        for scalar_group in scalar_groups:
            with self.subTest(style=scalar_group.style):
                self.assertEqual(
                    shape._wrapSequenceMemberData(scalar_group, "test-value"),
                    {"value": "test-value"},
                )

    def test_vector_value_remains_an_object(self):
        shape = PAR_SHAPE.SequenceParShape(ownerComp=None, parGroup=None)
        vector_group = FakeParGroup("XYZ", size=3)
        value = {"x": 1, "y": 2, "z": 3}

        self.assertIs(shape._wrapSequenceMemberData(vector_group, value), value)

    def test_equal_sequence_length_does_not_reassign_num_blocks(self):
        sequence = FakeSequence(num_blocks=1, blocks=[[]])
        sequence_group = FakeSequenceParGroup(sequence)
        shape = PAR_SHAPE.SequenceParShape(ownerComp=None, parGroup=sequence_group)

        shape.setData([{}])

        self.assertEqual(sequence.num_blocks_assignments, 0)

    def test_unchanged_sequence_member_is_not_assigned(self):
        member = FakeParGroup("Str", name="Member")
        sequence = FakeSequence(num_blocks=1, blocks=[[member]])
        sequence_group = FakeSequenceParGroup(sequence)
        shape = PAR_SHAPE.SequenceParShape(ownerComp=None, parGroup=sequence_group)
        block_shape = FakeBlockShape("same")
        original_build_shape = PAR_SHAPE.buildShape
        PAR_SHAPE.buildShape = lambda owner_comp, par_group: block_shape

        try:
            shape.setData([{"Member": "same"}])
        finally:
            PAR_SHAPE.buildShape = original_build_shape

        self.assertEqual(block_shape.set_calls, [])

    def test_changed_sequence_member_is_assigned(self):
        member = FakeParGroup("Str", name="Member")
        sequence = FakeSequence(num_blocks=1, blocks=[[member]])
        sequence_group = FakeSequenceParGroup(sequence)
        shape = PAR_SHAPE.SequenceParShape(ownerComp=None, parGroup=sequence_group)
        block_shape = FakeBlockShape("before")
        original_build_shape = PAR_SHAPE.buildShape
        PAR_SHAPE.buildShape = lambda owner_comp, par_group: block_shape

        try:
            shape.setData([{"Member": "after"}])
        finally:
            PAR_SHAPE.buildShape = original_build_shape

        self.assertEqual(block_shape.set_calls, [{"value": "after"}])

    def test_repeated_set_rechecks_live_sequence_state(self):
        member = FakeParGroup("Str", name="Member")
        sequence = FakeSequence(num_blocks=1, blocks=[[member]])
        sequence_group = FakeSequenceParGroup(sequence)
        shape = PAR_SHAPE.SequenceParShape(ownerComp=None, parGroup=sequence_group)
        block_shape = FakeBlockShape("before")
        original_build_shape = PAR_SHAPE.buildShape
        PAR_SHAPE.buildShape = lambda owner_comp, par_group: block_shape

        try:
            shape.setData([{"Member": "after"}])
            shape.setData([{"Member": "after"}])
        finally:
            PAR_SHAPE.buildShape = original_build_shape

        self.assertEqual(block_shape.build_calls, 2)
        self.assertEqual(block_shape.set_calls, [{"value": "after"}])

    def test_external_sequence_change_is_corrected_by_repeated_payload(self):
        member = FakeParGroup("Str", name="Member")
        sequence = FakeSequence(num_blocks=1, blocks=[[member]])
        sequence_group = FakeSequenceParGroup(sequence)
        shape = PAR_SHAPE.SequenceParShape(ownerComp=None, parGroup=sequence_group)
        block_shape = FakeBlockShape("before")
        original_build_shape = PAR_SHAPE.buildShape
        PAR_SHAPE.buildShape = lambda owner_comp, par_group: block_shape

        try:
            shape.setData([{"Member": "desired"}])
            block_shape.current_value = "changed-externally"
            shape.setData([{"Member": "desired"}])
        finally:
            PAR_SHAPE.buildShape = original_build_shape

        self.assertEqual(
            block_shape.set_calls,
            [{"value": "desired"}, {"value": "desired"}],
        )

    def test_repeated_true_pulse_is_not_suppressed_by_cache(self):
        member = FakeParGroup("Pulse", name="Trigger")
        sequence = FakeSequence(num_blocks=1, blocks=[[member]])
        sequence_group = FakeSequenceParGroup(sequence)
        shape = PAR_SHAPE.SequenceParShape(ownerComp=None, parGroup=sequence_group)
        block_shape = FakeBlockShape(False)
        original_build_shape = PAR_SHAPE.buildShape
        PAR_SHAPE.buildShape = lambda owner_comp, par_group: block_shape

        try:
            shape.setData([{"Trigger": True}])
            shape.setData([{"Trigger": True}])
        finally:
            PAR_SHAPE.buildShape = original_build_shape

        self.assertEqual(
            block_shape.set_calls,
            [{"value": True}, {"value": True}],
        )

    def test_repeated_sets_do_not_reiterate_touchdesigner_block(self):
        member = FakeParGroup("Str", name="Member")
        block = CountingBlock([member])
        sequence = FakeSequence(num_blocks=1, blocks=[block])
        sequence_group = FakeSequenceParGroup(sequence)
        shape = PAR_SHAPE.SequenceParShape(ownerComp=None, parGroup=sequence_group)
        block_shape = FakeBlockShape("before")
        original_build_shape = PAR_SHAPE.buildShape
        PAR_SHAPE.buildShape = lambda owner_comp, par_group: block_shape

        try:
            shape.setData([{"Member": "after"}])
            shape.setData([{"Member": "after"}])
            shape.buildData()
        finally:
            PAR_SHAPE.buildShape = original_build_shape

        self.assertEqual(block.iterations, 1)

    def test_fresh_sequence_proxy_does_not_invalidate_block_cache(self):
        member = FakeParGroup("Str", name="Member")
        block = CountingBlock([member])
        sequence_group = RewrappingSequenceParGroup(1, [block])
        shape = PAR_SHAPE.SequenceParShape(ownerComp=None, parGroup=sequence_group)
        block_shape = FakeBlockShape("before")
        original_build_shape = PAR_SHAPE.buildShape
        PAR_SHAPE.buildShape = lambda owner_comp, par_group: block_shape

        try:
            shape.setData([{"Member": "after"}])
            shape.setData([{"Member": "after"}])
            shape.buildData()
        finally:
            PAR_SHAPE.buildShape = original_build_shape

        self.assertEqual(block.iterations, 1)

    def test_generator_emit_and_clear_pulses_are_never_coalesced(self):
        emit = FakeParGroup("Pulse", name="Emit")
        clear = FakeParGroup("Pulse", name="Clear")
        block = CountingBlock([emit, clear])
        sequence = FakeSequence(num_blocks=1, blocks=[block])
        sequence_group = FakeSequenceParGroup(sequence)
        shape = PAR_SHAPE.SequenceParShape(ownerComp=None, parGroup=sequence_group)
        shapes = {
            "Emit": FakeBlockShape(False),
            "Clear": FakeBlockShape(False),
        }
        original_build_shape = PAR_SHAPE.buildShape
        PAR_SHAPE.buildShape = lambda owner_comp, par_group: shapes[par_group.name]

        try:
            shape.setData([{"Emit": True, "Clear": False}])
            shape.setData([{"Emit": True, "Clear": False}])
            shape.setData([{"Emit": False, "Clear": True}])
            shape.setData([{"Emit": False, "Clear": True}])
        finally:
            PAR_SHAPE.buildShape = original_build_shape

        self.assertEqual(
            shapes["Emit"].set_calls,
            [{"value": True}, {"value": True}],
        )
        self.assertEqual(
            shapes["Clear"].set_calls,
            [{"value": True}, {"value": True}],
        )
        self.assertEqual(block.iterations, 1)

    def test_invalid_later_block_does_not_resize_sequence(self):
        sequence = FakeSequence(num_blocks=1, blocks=[[]])
        sequence_group = FakeSequenceParGroup(sequence)
        shape = PAR_SHAPE.SequenceParShape(ownerComp=None, parGroup=sequence_group)

        with self.assertRaisesRegex(ValueError, "Sequence block 1"):
            shape.setData([{}, "invalid"])

        self.assertEqual(sequence.num_blocks_assignments, 0)


if __name__ == "__main__":
    unittest.main()
