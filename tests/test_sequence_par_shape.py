import importlib.util
from pathlib import Path
import sys
import types
import unittest
from uuid import UUID


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
    def test_shrink_preserves_ticks_before_removed_parameters_are_invalid(self):
        class Member:
            name = "Trigger"

            def __init__(self):
                self.valid = True

            @property
            def style(self):
                if not self.valid:
                    raise RuntimeError("Invalid Par object.")
                return "Pulse"

        class Sequence(FakeSequence):
            @FakeSequence.numBlocks.setter
            def numBlocks(self, value):
                for block in self.blocks[value:]:
                    for member in block:
                        member.valid = False
                self.blocks = self.blocks[:value]
                while len(self.blocks) < value:
                    self.blocks.append([Member()])
                self._num_blocks = value

        tick = {"id": "68b4ab1a-f242-4b9c-8363-252dc1042898", "prev": None, "next": None}
        sequence = Sequence(2, [[Member()], [Member()]])
        shape = PAR_SHAPE.SequenceParShape(None, FakeSequenceParGroup(sequence))
        other_shape = PAR_SHAPE.SequenceParShape(None, FakeSequenceParGroup(sequence))
        original_build_shape = PAR_SHAPE.buildShape

        def build_shape(owner, member):
            block_shape = FakeBlockShape(tick)
            block_shape.restoreTick = lambda value: setattr(block_shape, "current_value", value)
            return block_shape

        PAR_SHAPE.buildShape = build_shape
        try:
            shape.buildData()
            other_shape.buildData()
            shape.setData([{}])
            self.assertEqual(shape.buildData(), [{"Trigger": tick}])
            self.assertEqual(sequence.numBlocks, 1)
            other_shape.setData([{}, {}])
            self.assertEqual(other_shape.buildData(), [{"Trigger": tick}, {"Trigger": tick}])
        finally:
            PAR_SHAPE.buildShape = original_build_shape

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

    def test_repeated_exec_tick_is_forwarded_to_member_shape_for_id_filtering(self):
        member = FakeParGroup("Pulse", name="Trigger")
        sequence = FakeSequence(num_blocks=1, blocks=[[member]])
        sequence_group = FakeSequenceParGroup(sequence)
        shape = PAR_SHAPE.SequenceParShape(ownerComp=None, parGroup=sequence_group)
        block_shape = FakeBlockShape({"id": PAR_SHAPE.NIL_EXEC_TICK_ID, "prev": None, "next": None})
        original_build_shape = PAR_SHAPE.buildShape
        PAR_SHAPE.buildShape = lambda owner_comp, par_group: block_shape

        try:
            tick = {"id": "68b4ab1a-f242-4b9c-8363-252dc1042898", "prev": None, "next": None}
            shape.setData([{"Trigger": tick}])
            shape.setData([{"Trigger": tick}])
        finally:
            PAR_SHAPE.buildShape = original_build_shape

        self.assertEqual(
            block_shape.set_calls,
            [{"value": tick}, {"value": tick}],
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

    def test_generator_emit_and_clear_exec_ticks_are_forwarded_independently(self):
        emit = FakeParGroup("Pulse", name="Emit")
        clear = FakeParGroup("Pulse", name="Clear")
        block = CountingBlock([emit, clear])
        sequence = FakeSequence(num_blocks=1, blocks=[block])
        sequence_group = FakeSequenceParGroup(sequence)
        shape = PAR_SHAPE.SequenceParShape(ownerComp=None, parGroup=sequence_group)
        shapes = {
            "Emit": FakeBlockShape({"id": PAR_SHAPE.NIL_EXEC_TICK_ID, "prev": None, "next": None}),
            "Clear": FakeBlockShape({"id": PAR_SHAPE.NIL_EXEC_TICK_ID, "prev": None, "next": None}),
        }
        original_build_shape = PAR_SHAPE.buildShape
        PAR_SHAPE.buildShape = lambda owner_comp, par_group: shapes[par_group.name]

        try:
            emit = {"id": "00000000-0000-4000-8000-000000000001", "prev": None, "next": None}
            clear = {"id": "00000000-0000-4000-8000-000000000002", "prev": None, "next": None}
            shape.setData([{"Emit": emit}])
            shape.setData([{"Clear": clear}])
        finally:
            PAR_SHAPE.buildShape = original_build_shape

        self.assertEqual(
            shapes["Emit"].set_calls,
            [{"value": emit}],
        )
        self.assertEqual(
            shapes["Clear"].set_calls,
            [{"value": clear}],
        )
        self.assertEqual(block.iterations, 1)

    def test_exec_tick_schema_and_repeated_id_do_not_replay_pulse(self):
        member = FakeParGroup("Pulse", name="Trigger")
        sequence = FakeSequence(num_blocks=1, blocks=[[member]])
        shape = PAR_SHAPE.SequenceParShape(None, FakeSequenceParGroup(sequence), sequenceParGroups=[member])
        pulse = type("Pulse", (), {"pulses": 0, "pulse": lambda self: setattr(self, "pulses", self.pulses + 1)})()
        pulse_shape = PAR_SHAPE.PulseParShape(None, member)
        pulse_shape.ownerComp = type("Owner", (), {"par": {"Trigger": pulse}})()
        original_build_shape = PAR_SHAPE.buildShape
        PAR_SHAPE.buildShape = lambda owner_comp, par_group: pulse_shape
        tick = {"id": "68b4ab1a-f242-4b9c-8363-252dc1042898", "prev": None, "next": None}
        try:
            schema = shape.buildSchemaProperties()["items"]["properties"]["Trigger"]
            self.assertEqual(schema["format"], "exec-tick")
            shape.setData([{"Trigger": tick}])
            first = pulse_shape.buildData()
            shape.setData([{"Trigger": tick}])
        finally:
            PAR_SHAPE.buildShape = original_build_shape
        self.assertEqual(first["value"], tick)
        self.assertEqual(pulse.pulses, 1)

    def test_local_sequence_pulse_mints_uuid_and_retains_it(self):
        member = FakeParGroup("Pulse", name="Trigger")
        sequence = FakeSequence(num_blocks=1, blocks=[[member]])
        shape = PAR_SHAPE.SequenceParShape(None, FakeSequenceParGroup(sequence))
        shape.markLocalPulse("Trigger")
        first = shape.buildData()[0]["Trigger"]
        second = shape.buildData()[0]["Trigger"]
        self.assertNotEqual(first["id"], PAR_SHAPE.NIL_EXEC_TICK_ID)
        self.assertEqual(UUID(first["id"]).version, 4)
        self.assertEqual(second, first)

    def test_programmatic_pulse_callback_preserves_incoming_tick_id(self):
        member = FakeParGroup("Pulse", name="Trigger")
        pulse = type("Pulse", (), {"pulses": 0, "pulse": lambda self: setattr(self, "pulses", self.pulses + 1)})()
        owner = type("Owner", (), {"par": {"Trigger": pulse}})()
        shape = PAR_SHAPE.PulseParShape(owner, member)
        tick = {"id": "68b4ab1a-f242-4b9c-8363-252dc1042898", "prev": {"x": 1}, "next": {"x": 2}}

        shape.setData({"value": tick})
        shape.markLocalPulse(pulseToken=object())
        shape.setData({"value": tick})

        self.assertEqual(pulse.pulses, 1)
        self.assertEqual(shape.buildData()["value"], tick)

    def test_action_and_state_shapes_share_sequence_tick_identity(self):
        member = FakeParGroup("Pulse", name="Trigger")
        sequence = FakeSequence(num_blocks=1, blocks=[[member]])
        action_shape = PAR_SHAPE.SequenceParShape(None, FakeSequenceParGroup(sequence))
        state_shape = PAR_SHAPE.SequenceParShape(None, FakeSequenceParGroup(sequence))
        token = object()

        action_shape.markLocalPulse("Trigger", pulseToken=token)
        state_shape.markLocalPulse("Trigger", pulseToken=token)

        self.assertEqual(action_shape.buildData(), state_shape.buildData())

    def test_invalid_later_block_does_not_resize_sequence(self):
        sequence = FakeSequence(num_blocks=1, blocks=[[]])
        sequence_group = FakeSequenceParGroup(sequence)
        shape = PAR_SHAPE.SequenceParShape(ownerComp=None, parGroup=sequence_group)

        with self.assertRaisesRegex(ValueError, "Sequence block 1"):
            shape.setData([{}, "invalid"])

        self.assertEqual(sequence.num_blocks_assignments, 0)


if __name__ == "__main__":
    unittest.main()
