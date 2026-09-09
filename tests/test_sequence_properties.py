import types
import unittest
from unittest.mock import patch

from test_properties_loading import EXEC, RSHIP, FakePars
import test_properties_loading as property_fixtures
import sequence_target
import page_target
import test_rship_ext as fixtures


class FakeSequence:
    def __init__(self, owner, members, count):
        self.owner = owner
        self.name = "Generator"
        self.members = members
        self.blocks = []
        self.resize_calls = []
        self.numBlocks = count
        self.resize_calls.clear()

    def group(self, index, member, style):
        return types.SimpleNamespace(
            name=f"Generator{index}{member}", style=style, size=1,
            sequence=self, sequenceIndex=index, owner=self.owner,
            menuNames=[["0", "7"]], menuLabels=[["First", "Seventh"]],
        )

    @property
    def numBlocks(self):
        return len(self.blocks)

    @numBlocks.setter
    def numBlocks(self, count):
        self.resize_calls.append(count)
        self.blocks = [[self.group(index, member, style) for member, style, _ in self.members]
                       for index in range(count)]
        for block in self.blocks:
            for group, (_, _, default) in zip(block, self.members):
                if group.name not in self.owner.par:
                    self.owner.par[group.name] = default


class SequencePropertyTests(unittest.TestCase):
    setUp = property_fixtures.PropertyLoadingTests.setUp
    make_extension = property_fixtures.PropertyLoadingTests.make_extension
    events = property_fixtures.PropertyLoadingTests.events
    command = property_fixtures.PropertyLoadingTests.command
    resend = property_fixtures.PropertyLoadingTests.resend

    def make_sequence_target(self, count=1, members=None, tags=()):
        members = members or [("Value", "Float", 0.25), ("Selected", "Menu", "0"),
                              ("Enabled", "Toggle", False), ("Emit", "Pulse", None),
                              ("Clear", "Momentary", None)]
        owner = types.SimpleNamespace(path="/sequence", par=FakePars(), tags=set(tags), customPages=[])
        sequence = FakeSequence(owner, members, count)
        header = types.SimpleNamespace(name="Generator", style="Sequence", sequence=sequence)
        templates = [sequence.group(0, member, style) for member, style, _ in members]
        owner.customPages = [types.SimpleNamespace(parGroups=[header, *templates])]
        instance = EXEC.Instance("machine:service", "service", "service", "touchdesigner",
                                 EXEC.InstanceStatus.Starting, "machine", "#123456")
        with patch.object(sequence_target, "op", types.SimpleNamespace(RS_LOG=fixtures.FakeLog()), create=True):
            target = sequence_target.SequenceTarget("operator:Generators", "operator", owner,
                                                    header, instance, sequenceParGroups=[header, *templates])
        return target, sequence

    def start(self, **kwargs):
        target, sequence = self.make_sequence_target(**kwargs)
        extension, _ = self.make_extension(target)
        patcher = patch.object(sequence_target, "CLIENT", self.client)
        patcher.start()
        self.addCleanup(patcher.stop)
        extension.refreshProjectData()
        self.assertEqual(extension.state, RSHIP.RshipState.ACTIVE)
        return extension, target, sequence

    def set_sequence(self, extension, data, state=True):
        suffix = ":state_set" if state else ":set"
        extension.OnRshipReceiveText(self.command("ExecTargetAction", {
            "tx": "same", "instanceId": "machine:service",
            "action": {"id": "operator:Generator" + suffix, "targetId": "operator:Generator"},
            "data": data,
        }))

    def pulse_data(self, emitter):
        return [event["item"]["data"] for event in self.events()
                if event["itemType"] == "Pulse" and event["item"]["emitterId"] == emitter]

    def test_state_pair_preserves_legacy_schema_and_ids_but_excludes_events(self):
        _, _, _ = self.start()
        actions = {event["item"]["id"]: event["item"] for event in self.events() if event["itemType"] == "Action"}
        self.assertEqual(set(actions), {"operator:Generator:set", "operator:Generator:resend", "operator:Generator:state_set"})
        self.assertNotIn("writesTo", actions["operator:Generator:set"])
        self.assertNotIn("writesTo", actions["operator:Generator:resend"])
        state = actions["operator:Generator:state_set"]
        self.assertEqual(state["writesTo"], {"emitterId": "operator:Generator:state_updated", "role": "canonical"})
        self.assertEqual(state["schema"]["type"], "array")
        self.assertEqual(set(state["schema"]["items"]["properties"]), {"Value", "Selected", "Enabled"})
        self.assertEqual(set(actions["operator:Generator:set"]["schema"]["items"]["properties"]),
                         {"Value", "Selected", "Enabled", "Emit", "Clear"})
        self.assertEqual(self.pulse_data("operator:Generator:state_updated"),
                         [[{"Value": 0.25, "Selected": "0", "Enabled": False}]])
        self.assertEqual(set(self.client.emitterValueProviders), {"operator:Generator:state_updated"})

    def test_state_arrays_resize_and_assign_values_without_pulsing_injected_event_keys(self):
        extension, target, sequence = self.start()
        self.frames.clear()
        data = [{"Value": 0.8, "Selected": "7", "Enabled": True, "Emit": True, "Clear": True},
                {"Value": 0.3, "Selected": "0", "Enabled": False, "Emit": True}]
        self.set_sequence(extension, data)
        self.set_sequence(extension, data)
        self.assertEqual(sequence.numBlocks, 2)
        self.assertEqual(sequence.resize_calls, [2])
        self.assertEqual(target.ownerComp.par["Generator0Value"].eval(), 0.8)
        self.assertEqual(target.ownerComp.par["Generator0Selected"].eval(), "7")
        self.assertEqual(target.ownerComp.par["Generator0Enabled"].eval(), True)
        self.assertEqual(target.ownerComp.par["Generator1Value"].eval(), 0.3)
        for index in range(2):
            self.assertEqual(target.ownerComp.par[f"Generator{index}Emit"].pulses, 0)
            self.assertEqual(target.ownerComp.par[f"Generator{index}Clear"].pulses, 0)
        self.assertEqual(self.pulse_data("operator:Generator:state_updated"), [
            [{"Value": 0.8, "Selected": "7", "Enabled": True}, {"Value": 0.3, "Selected": "0", "Enabled": False}],
            [{"Value": 0.8, "Selected": "7", "Enabled": True}, {"Value": 0.3, "Selected": "0", "Enabled": False}],
        ])

    def test_current_readback_tracks_manual_values_and_manual_resize(self):
        extension, target, sequence = self.start()
        sequence.numBlocks = 2
        target.ownerComp.par["Generator0Value"] = 0.9
        target.ownerComp.par["Generator1Selected"] = "7"
        self.frames.clear()
        extension.OnRshipReceiveText(self.resend("operator:Generator:state_updated"))
        self.assertEqual(self.pulse_data("operator:Generator:state_updated"), [[
            {"Value": 0.9, "Selected": "0", "Enabled": False},
            {"Value": 0.25, "Selected": "7", "Enabled": False},
        ]])
        self.assertEqual(self.frames[-1]["event"], "ws:m:command-response")

    def test_empty_state_is_rejected_without_changing_blocks(self):
        extension, target, sequence = self.start(count=2)
        self.frames.clear()
        self.set_sequence(extension, [])
        self.assertEqual(sequence.numBlocks, 2)
        self.assertEqual(sequence.resize_calls, [])
        self.assertEqual(self.frames[-1]["event"], "ws:m:command-error")
        self.assertEqual(target.stateShape.buildSchemaProperties()["minItems"], 1)

    def test_state_respects_maximum_block_count_before_resizing(self):
        extension, target, sequence = self.start()
        sequence.maxBlocks = 2
        self.assertEqual(target.stateShape.buildSchemaProperties()["maxItems"], 2)
        self.frames.clear()
        self.set_sequence(extension, [{"Value": 0.2}] * 3)
        self.assertEqual(sequence.numBlocks, 1)
        self.assertEqual(sequence.resize_calls, [])
        self.assertEqual(self.frames[-1]["event"], "ws:m:command-error")

    def test_invalid_state_array_does_not_resize(self):
        extension, _, sequence = self.start()
        self.frames.clear()
        self.set_sequence(extension, [{"Value": 0.4}, "bad block"])
        self.assertEqual(sequence.numBlocks, 1)
        self.assertEqual(sequence.resize_calls, [])
        self.assertEqual(self.frames[-1]["event"], "ws:m:command-error")

    def test_legacy_set_still_fires_every_explicit_pulse(self):
        extension, target, _ = self.start()
        for _ in range(2):
            self.set_sequence(extension, [{"Value": 0.6, "Emit": True, "Clear": True}], state=False)
        self.assertEqual(target.ownerComp.par["Generator0Emit"].pulses, 2)
        self.assertEqual(target.ownerComp.par["Generator0Clear"].pulses, 2)
        self.assertEqual(target.ownerComp.par["Generator0Value"].eval(), 0.6)
        self.frames.clear()
        extension.OnRshipReceiveText(self.command("ExecTargetAction", {
            "tx": "legacy-resend", "action": {"id": "operator:Generator:resend", "targetId": "operator:Generator"}, "data": None,
        }))
        self.assertEqual(self.pulse_data("operator:Generator:updated"),
                         [[{"Value": 0.6, "Selected": "0", "Enabled": False, "Emit": None, "Clear": None}]])

    def test_shared_change_keys_publish_both_emitters_and_preserve_legacy_duplicate_events(self):
        extension, target, _ = self.start()
        self.frames.clear()
        with patch.object(RSHIP, "run", lambda *args, **kwargs: None, create=True):
            target.ownerComp.par["Generator0Value"] = 0.4
            extension.PulseEmitter(target.ownerComp, "Generator")
            extension._flushPulses()
            self.assertEqual(len(self.pulse_data("operator:Generator:updated")), 1)
            self.assertEqual(self.pulse_data("operator:Generator:state_updated"),
                             [[{"Value": 0.4, "Selected": "0", "Enabled": False}]])
            self.frames.clear()
            extension.PulseEmitter(target.ownerComp, "Generator", preserveDuplicate=True)
            extension.PulseEmitter(target.ownerComp, "Generator", preserveDuplicate=True)
            extension._flushPulses()
        self.assertEqual(len(self.pulse_data("operator:Generator:updated")), 2)
        self.assertEqual(len(self.pulse_data("operator:Generator:state_updated")), 1)

    def test_page_routes_block_members_only_to_sequence_targets(self):
        target, sequence = self.make_sequence_target()
        ordinary = types.SimpleNamespace(name="Weight", style="Float", sequence=None, size=1)
        target.ownerComp.par["Weight"] = 0.5
        page = page_target.PageTarget.__new__(page_target.PageTarget)
        page.ownerComp = target.ownerComp
        page.page = types.SimpleNamespace(name="Generators", parGroups=[target.parGroup, *sequence.blocks[0], ordinary])
        page.parentId = "operator"
        page.instance = target.instance
        page.parGroupTargets = {}
        page.parGroupTargetsByName = {}
        page.sequenceTargets = {}
        page.sequenceTargetsByName = {}
        with patch.object(sequence_target, "op", types.SimpleNamespace(RS_LOG=fixtures.FakeLog()), create=True):
            page.buildParGroupTargets()
        self.assertEqual(set(page.parGroupTargets), {"operator:Weight"})
        self.assertEqual(set(page.sequenceTargets), {"operator:Generator"})
        self.assertTrue(page.parGroupTargets["operator:Weight"].isProperty)
        self.assertTrue(page.sequenceTargets["operator:Generator"].isProperty)

    def test_sequence_without_separate_header_keeps_first_state_member(self):
        target, sequence = self.make_sequence_target()
        with patch.object(sequence_target, "op", types.SimpleNamespace(RS_LOG=fixtures.FakeLog()), create=True):
            direct_target = sequence_target.SequenceTarget(
                "operator:BuiltIn", "operator", target.ownerComp,
                sequence.blocks[0][0], target.instance, sequenceParGroups=sequence.blocks[0])
        state_action = next(action for action in direct_target.getActions() if action.id.endswith(":state_set"))
        self.assertEqual(set(state_action.schema["items"]["properties"]), {"Value", "Selected", "Enabled"})


    def test_tag_opt_out_and_event_only_sequences_do_not_create_state_pairs(self):
        for kwargs in ({"tags": {"rship-no-properties"}}, {"members": [("Emit", "Pulse", None), ("Clear", "Momentary", None)]}):
            with self.subTest(kwargs=kwargs):
                self.frames.clear()
                extension, _, _ = self.start(**kwargs)
                self.assertEqual(set(self.client.emitterValueProviders), set())
                actions = [e["item"] for e in self.events() if e["itemType"] == "Action"]
                self.assertEqual({a["id"] for a in actions}, {"operator:Generator:set", "operator:Generator:resend"})
                self.assertTrue(all("writesTo" not in action for action in actions))


if __name__ == "__main__":
    unittest.main()
