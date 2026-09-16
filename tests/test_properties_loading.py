import json
from collections import deque
import types
import unittest
from unittest.mock import patch

import test_rship_ext as fixtures
import par_group_target
import page_target


RSHIP = fixtures.RSHIP
EXEC = fixtures.EXEC


class FakePar:
    def __init__(self, value):
        self.value = value
        self.pulses = 0

    def eval(self):
        return self.value

    def pulse(self):
        self.pulses += 1


class FakePars(dict):
    def __setitem__(self, key, value):
        if key in self:
            self[key].value = value
        else:
            super().__setitem__(key, FakePar(value))


class PropertyLoadingTests(unittest.TestCase):
    def setUp(self):
        self.client = EXEC.ExecClient()
        self.client.log = lambda message: None
        self.frames = []
        self.client.setSend(lambda text: self.frames.append(json.loads(text)))
        log = types.SimpleNamespace(RS_LOG=fixtures.FakeLog())
        self.patches = [
            patch.object(RSHIP, "CLIENT", self.client),
            patch.object(RSHIP, "op", log, create=True),
            patch.object(par_group_target, "op", log, create=True),
            patch.object(par_group_target, "CLIENT", self.client),
        ]
        for patcher in self.patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def make_group_target(self, style="Float", values=None, name="Weight", allow=True):
        values = values if values is not None else {name: 0.25}
        pars = FakePars()
        for key, value in values.items():
            pars[key] = value
        group = types.SimpleNamespace(name=name, style=style, sequence=None, size=1,
                                      label="Display " + name, menuNames=[["0", "7"]],
                                      menuLabels=[["First", "Seventh"]])
        owner = types.SimpleNamespace(path="/target", par=pars, tags=set(),
                                      customPages=[types.SimpleNamespace(parGroups=[group])])
        instance = EXEC.Instance("machine:service", "service", "service", "touchdesigner",
                                 EXEC.InstanceStatus.Starting, "machine", "#123456")
        return par_group_target.ParGroupTarget("operator:Custom", "operator", owner,
                                               group, instance, allowProperties=allow)

    def make_extension(self, target=None):
        target = target or self.make_group_target()
        extension = RSHIP.RshipExt.__new__(RSHIP.RshipExt)
        extension.instance = target.instance
        extension._machineId = "machine"
        extension.makeServiceId = lambda: "service"
        extension.websocketOp = types.SimpleNamespace(sendText=self.client.send)
        extension.wsConnected = True
        extension.state = RSHIP.RshipState.CONNECTED
        extension._connectionGeneration = 1
        extension._deferredCommands = deque()
        extension._deferredBytes = 0
        extension._drainRun = None
        extension._retryAt = 0.0
        extension._retryDelay = 1.0
        extension._pendingPulses = {}
        extension._pendingExplicitPulses = []
        extension._pulseFlushScheduled = False
        extension.sentTargetStatuses = {}
        extension.emitterIndex = {}
        extension.emitterHandlers = {}
        extension.allTouchTargets = {}
        extension.opTargets = {"operator": fixtures.FakeOpTarget(target)}
        extension.cookTargetList = lambda: None
        extension.buildTargets = lambda: None
        extension.updateStatsPage = lambda **kwargs: None
        extension.updateExecInfo = lambda: None
        extension._scheduleTick = lambda: None
        self.client.instanceId = extension.instance.id
        return extension, target

    def events(self):
        return [event for frame in self.frames for event in
                (frame["data"] if frame["event"] == "ws:m:event-batch" else
                 [frame["data"]] if frame["event"] == "ws:m:event" else [])]

    def command(self, commandId, payload):
        return json.dumps({"event": "ws:m:command", "data": {
            "commandId": commandId, "command": payload}})

    def action(self, value, tx="shared", instance="machine:service", target="operator:Weight"):
        return self.command("ExecTargetAction", {
            "tx": tx, "instanceId": instance,
            "action": {"id": "operator:Weight:set", "targetId": target},
            "data": {"value": value}})

    def resend(self, emitter="operator:Weight:updated", instance="machine:service"):
        return self.command("ResendEmitterValue", {
            "tx": "resend", "instanceId": instance, "emitterId": emitter})

    def test_real_wire_metadata_and_current_seed_precede_available(self):
        extension, target = self.make_extension()
        extension.refreshProjectData()
        self.assertEqual(extension.state, RSHIP.RshipState.ACTIVE)
        events = self.events()
        actions = {e["item"]["id"]: e["item"] for e in events if e["itemType"] == "Action"}
        self.assertEqual(actions["operator:Weight:set"]["writesTo"],
                         {"emitterId": "operator:Weight:updated", "role": "canonical"})
        self.assertNotIn("writesTo", actions["operator:Weight:resend"])
        self.assertEqual([e["item"]["status"] for e in events if e["itemType"] == "Instance"],
                         ["Starting", "Available"])
        pulse_index = next(i for i, e in enumerate(events) if e["itemType"] == "Pulse")
        online_index = next(i for i, e in enumerate(events) if e["itemType"] == "TargetStatus")
        available_index = next(i for i, e in enumerate(events) if e["itemType"] == "Instance" and e["item"]["status"] == "Available")
        self.assertLess(pulse_index, online_index)
        self.assertLess(online_index, available_index)
        self.assertEqual(events[pulse_index]["item"]["data"], {"value": 0.25})
        self.assertEqual(set(self.client.emitterValueProviders), {"operator:Weight:updated"})
        self.assertTrue(all("handler" not in e["item"] for e in events))

    def test_readback_uses_actual_scalar_menu_toggle_and_vector_parameters(self):
        cases = [
            ("Float", "Weight", {"Weight": 1.0}, {"value": 0.75}, {"value": 0.75}),
            ("Menu", "Selectednode", {"Selectednode": "0"}, {"value": "7"}, {"value": "7"}),
            ("Toggle", "Bypass", {"Bypass": False}, {"value": True}, {"value": True}),
            ("XYZ", "Position", {"Positionx": 1, "Positiony": 2, "Positionz": 3},
             {"x": 4, "y": 5, "z": 6}, {"x": 4, "y": 5, "z": 6}),
        ]
        for style, name, initial, desired, expected in cases:
            with self.subTest(style=style):
                target = self.make_group_target(style, initial, name)
                extension, target = self.make_extension(target)
                extension.refreshProjectData()
                extension.OnRshipReceiveText(self.command("ExecTargetAction", {
                    "tx": "set", "instanceId": "machine:service",
                    "action": {"id": target.id + ":set", "targetId": target.id}, "data": desired}))
                self.frames.clear()
                extension.OnRshipReceiveText(self.resend(target.id + ":updated"))
                pulses = [event for event in self.events() if event["itemType"] == "Pulse"]
                self.assertEqual(pulses[0]["item"]["data"], expected)
                self.assertEqual(self.frames[-1]["event"], "ws:m:command-response")
                if style == "Menu":
                    self.assertEqual(target.parShape.buildSchemaProperties()["value"]["oneOf"],
                                     [{"const": "0", "title": "First"}, {"const": "7", "title": "Seventh"}])
        target.ownerComp.par["Positionx"] = 19
        self.frames.clear()
        extension.OnRshipReceiveText(self.resend(target.id + ":updated"))
        self.assertEqual(self.events()[0]["item"]["data"], {"x": 19, "y": 5, "z": 6})

    def test_early_commands_preserve_order_and_shared_transactions(self):
        extension, target = self.make_extension()
        extension.OnRshipReceiveText(self.action(0.5))
        extension.OnRshipReceiveText(self.resend())
        extension.OnRshipReceiveText(self.action(0.75))
        self.assertEqual(target.ownerComp.par["Weight"].eval(), 0.25)
        extension.refreshProjectData()
        pulses = [e["item"]["data"] for e in self.events() if e["itemType"] == "Pulse"]
        self.assertEqual(pulses, [{"value": 0.25}, {"value": 0.5}, {"value": 0.5}, {"value": 0.75}])
        self.assertEqual(target.ownerComp.par["Weight"].eval(), 0.75)
        self.assertEqual([f["data"]["tx"] for f in self.frames if f["event"] == "ws:m:command-response"],
                         ["shared", "resend", "shared"])
        self.assertEqual(extension._deferredBytes, 0)

    def test_server_dispatch_during_definition_send_waits_until_registration_finishes(self):
        extension, target = self.make_extension()
        ordinary_send = extension.websocketOp.sendText
        observed = []
        def send(text):
            ordinary_send(text)
            if len(self.frames) == 2:
                extension.OnRshipReceiveText(self.action(0.9))
                observed.append(target.ownerComp.par["Weight"].eval())
        extension.websocketOp.sendText = send
        extension.refreshProjectData()
        self.assertEqual(observed, [0.25])
        self.assertEqual(target.ownerComp.par["Weight"].eval(), 0.9)
        self.assertEqual(extension.state, RSHIP.RshipState.ACTIVE)

    def test_protocol_response_is_processed_while_loading(self):
        extension, _ = self.make_extension()
        calls = []
        self.client.queryHandlers["query"] = lambda response: calls.append(response.tx)
        extension.OnRshipReceiveText(json.dumps({"event": "ws:m:query-response", "data": {"tx": "query", "upserts": []}}))
        self.assertEqual(calls, ["query"])
        self.assertEqual(len(extension._deferredCommands), 0)

    def test_loading_queue_limit_returns_error_without_losing_accepted_action(self):
        extension, target = self.make_extension()
        extension.MAX_DEFERRED_COMMANDS = 1
        extension.OnRshipReceiveText(self.action(0.5))
        extension.OnRshipReceiveText(self.action(0.9))
        self.assertEqual(self.frames[-1]["event"], "ws:m:command-error")
        extension.refreshProjectData()
        self.assertEqual(target.ownerComp.par["Weight"].eval(), 0.5)
        extension.state = RSHIP.RshipState.CONNECTED
        extension.MAX_DEFERRED_BYTES = 1
        extension.OnRshipReceiveText(self.action(0.7))
        self.assertEqual(self.frames[-1]["event"], "ws:m:command-error")
        self.assertEqual(len(extension._deferredCommands), 0)

    def test_disconnect_discards_deferred_work_and_pulses_then_reseeds_current_value(self):
        extension, target = self.make_extension()
        extension.OnRshipReceiveText(self.action(0.9))
        extension._pendingPulses["old"] = object()
        extension._pendingExplicitPulses.append(object())
        extension.OnRshipDisconnect()
        self.assertEqual(list(extension._deferredCommands), [])
        self.assertEqual(extension._pendingPulses, {})
        self.assertEqual(extension._pendingExplicitPulses, [])
        self.assertEqual(self.client.emitterValueProviders, {})
        target.ownerComp.par["Weight"] = 0.8
        extension.OnRshipConnect()
        self.assertEqual(target.ownerComp.par["Weight"].eval(), 0.8)
        self.assertEqual([e["item"]["data"] for e in self.events() if e["itemType"] == "Pulse"], [{"value": 0.8}])

    def test_failed_scan_retries_on_tick_with_unchanged_configuration(self):
        extension, target = self.make_extension()
        attempts = []
        def build():
            attempts.append(True)
            if len(attempts) == 1:
                raise ValueError("not loaded")
        extension.buildTargets = build
        extension.OnRshipReceiveText(self.action(0.6))
        with patch.object(RSHIP.time, "monotonic", return_value=100):
            extension.refreshProjectData()
            self.assertEqual(extension.state, RSHIP.RshipState.CONNECTED)
            self.assertEqual(extension._retryAt, 101)
            extension.OnTickInterval()
            self.assertEqual(len(attempts), 1)
        with patch.object(RSHIP.time, "monotonic", return_value=101):
            extension.OnTickInterval()
        self.assertEqual(extension.state, RSHIP.RshipState.ACTIVE)
        self.assertEqual(target.ownerComp.par["Weight"].eval(), 0.6)

    def test_failed_send_never_becomes_active_and_retry_republishes_definitions(self):
        extension, _ = self.make_extension()
        ordinary_send = extension.websocketOp.sendText
        def fail_seed(text):
            frame = json.loads(text)
            if frame["event"] == "ws:m:event" and frame["data"]["itemType"] == "Pulse":
                raise OSError("socket failed")
            ordinary_send(text)
        extension.websocketOp.sendText = fail_seed
        extension.refreshProjectData()
        self.assertEqual(extension.state, RSHIP.RshipState.CONNECTED)
        self.assertFalse(any(e["itemType"] == "Instance" and e["item"]["status"] == "Available" for e in self.events()))
        self.assertEqual(extension.sentTargetStatuses, {})
        self.frames.clear()
        extension.websocketOp.sendText = ordinary_send
        extension.refreshProjectData()
        self.assertEqual(extension.state, RSHIP.RshipState.ACTIVE)
        self.assertTrue(any(e["itemType"] == "Action" for e in self.events()))

    def test_disconnect_during_registration_cannot_publish_available(self):
        extension, _ = self.make_extension()
        ordinary_send = extension.websocketOp.sendText
        def disconnect(text):
            ordinary_send(text)
            extension.OnRshipDisconnect()
        extension.websocketOp.sendText = disconnect
        extension.refreshProjectData()
        self.assertEqual(extension.state, RSHIP.RshipState.READY)
        self.assertFalse(any(e["itemType"] == "Instance" and e["item"]["status"] == "Available" for e in self.events()))

    def test_ensure_ready_creates_missing_or_mismatched_instance_in_connected_state(self):
        extension, _ = self.make_extension()
        extension.instance = None
        self.assertTrue(extension._ensureReady())
        self.assertEqual(extension.instance.id, "machine:service")
        extension.makeServiceId = lambda: "new-service"
        self.assertTrue(extension._ensureReady())
        self.assertEqual(extension.instance.id, "machine:new-service")
        self.assertEqual(self.client.instanceId, "machine:new-service")

    def test_wrong_instance_or_target_cannot_change_parameters_or_resend(self):
        extension, target = self.make_extension()
        extension.refreshProjectData()
        self.frames.clear()
        extension.OnRshipReceiveText(self.action(0.9, instance="other"))
        extension.OnRshipReceiveText(self.action(0.9, target="other"))
        extension.OnRshipReceiveText(self.resend(instance="other"))
        extension.OnRshipReceiveText(self.resend(emitter="unknown"))
        self.assertEqual(target.ownerComp.par["Weight"].eval(), 0.25)
        self.assertEqual([f["event"] for f in self.frames], ["ws:m:command-error"] * 4)

    def test_compact_batch_continues_after_unknown_action_and_reports_error(self):
        extension, target = self.make_extension()
        extension.refreshProjectData()
        self.frames.clear()
        extension.OnRshipReceiveText(self.command("CompactBatchTargetAction", {"tx": "batch", "groups": [
            {"actionId": "unknown", "payloads": [{}], "assignments": [{"instanceId": "machine:service", "targetId": target.id, "payloadIndex": 0}]},
            {"actionId": target.id + ":set", "payloads": [{"value": 0.8}], "assignments": [{"instanceId": "machine:service", "targetId": target.id, "payloadIndex": 0}]},
        ]}))
        self.assertEqual(target.ownerComp.par["Weight"].eval(), 0.8)
        self.assertEqual([f["event"] for f in self.frames], ["ws:m:event", "ws:m:command-error"])
        self.assertEqual(self.frames[-1]["data"]["commandId"], "CompactBatchTargetAction")

    def test_pulse_actions_stay_unpaired_and_do_not_seed_fake_events(self):
        for style in ("Pulse", "Momentary"):
            with self.subTest(style=style):
                target = self.make_group_target(style, {"Emit": None}, "Emit")
                extension, target = self.make_extension(target)
                self.frames.clear()
                extension.refreshProjectData(sendEmitterValues=True)
                actions = [e["item"] for e in self.events() if e["itemType"] == "Action"]
                self.assertEqual({a["id"] for a in actions}, {"operator:Emit:set", "operator:Emit:resend"})
                self.assertTrue(all("writesTo" not in a for a in actions))
                self.assertFalse(any(e["itemType"] == "Pulse" for e in self.events()))
                self.assertEqual(self.client.emitterValueProviders, {})
                tick = {"id": "68b4ab1a-f242-4b9c-8363-252dc1042898", "prev": None, "next": None}
                message = self.command("ExecTargetAction", {"tx": "same", "action": {"id": target.id + ":set", "targetId": target.id}, "data": {"value": tick}})
                extension.OnRshipReceiveText(message)
                extension.OnRshipReceiveText(message)
                self.assertEqual(target.ownerComp.par["Emit"].pulses, 1)
                schema = actions[0]["schema"]["properties"]["value"]
                self.assertEqual(schema["format"], "exec-tick")

    def test_active_refresh_publishes_starting_before_a_failing_scan(self):
        extension, _ = self.make_extension()
        extension.refreshProjectData()
        self.frames.clear()
        def fail_scan():
            self.assertEqual(self.events()[0]["item"]["status"], "Starting")
            raise ValueError("loading")
        extension.buildTargets = fail_scan
        extension.refreshProjectData()
        self.assertEqual(extension.state, RSHIP.RshipState.CONNECTED)
        self.assertTrue(all(e["item"]["status"] == "Starting" for e in self.events()))

    def test_first_valid_text_recovers_a_missed_connect_callback(self):
        extension, target = self.make_extension()
        extension.wsConnected = False
        extension.state = RSHIP.RshipState.READY
        extension.OnRshipReceiveText(self.action(0.65))
        self.assertEqual(extension.state, RSHIP.RshipState.ACTIVE)
        self.assertEqual(target.ownerComp.par["Weight"].eval(), 0.65)

    def test_property_set_reports_normalized_and_unchanged_values_without_parexec(self):
        extension, target = self.make_extension()
        extension.refreshProjectData()
        original_set = target.parShape.setData
        target.parShape.setData = lambda data: original_set({"value": min(1.0, data["value"])})
        self.frames.clear()
        extension.OnRshipReceiveText(self.action(1.5))
        extension.OnRshipReceiveText(self.action(1.5))
        self.assertEqual([e["item"]["data"] for e in self.events() if e["itemType"] == "Pulse"],
                         [{"value": 1.0}, {"value": 1.0}])
        self.assertEqual(target.ownerComp.par["Weight"].eval(), 1.0)

    def test_deferred_drain_yields_between_frames_and_new_commands_keep_fifo_order(self):
        extension, target = self.make_extension()
        extension.DRAIN_COMMAND_LIMIT = 2
        scheduled = []
        def schedule(*args, **kwargs):
            scheduled.append((args, kwargs))
            return types.SimpleNamespace(kill=lambda: None)
        for value in (1, 2, 3):
            extension.OnRshipReceiveText(self.action(value))
        with patch.object(RSHIP, "run", schedule, create=True):
            extension.refreshProjectData()
            self.assertEqual(target.ownerComp.par["Weight"].eval(), 2)
            self.assertEqual(scheduled[0][1], {"delayFrames": 1})
            extension.OnRshipReceiveText(self.action(4))
            self.assertEqual(target.ownerComp.par["Weight"].eval(), 2)
            extension._drainCommands()
        self.assertEqual(target.ownerComp.par["Weight"].eval(), 4)
        self.assertEqual([e["item"]["data"] for e in self.events() if e["itemType"] == "Pulse"],
                         [{"value": 0.25}, {"value": 1}, {"value": 2}, {"value": 3}, {"value": 4}])

    def test_persistent_failure_has_capped_retry_delay(self):
        extension, _ = self.make_extension()
        extension.buildTargets = lambda: (_ for _ in ()).throw(ValueError("loading"))
        for _ in range(10):
            extension.refreshProjectData()
        self.assertEqual(extension._retryDelay, 30.0)
        self.assertEqual(extension.state, RSHIP.RshipState.CONNECTED)


    def test_operator_opt_out_disables_pairing_but_custom_sequences_do_not(self):
        target = self.make_group_target()
        owner = target.ownerComp
        self.assertTrue(par_group_target.supportsProperties(owner))
        owner.tags.add("rship-no-properties")
        self.assertFalse(par_group_target.supportsProperties(owner))
        owner.tags.clear()
        owner.customPages.append(types.SimpleNamespace(parGroups=[types.SimpleNamespace(style="Float", sequence=object())]))
        self.assertTrue(par_group_target.supportsProperties(owner))
        owner.tags.add("rship-no-properties")
        page = page_target.PageTarget.__new__(page_target.PageTarget)
        page.ownerComp = owner
        page.page = types.SimpleNamespace(name="Custom", parGroups=[target.parGroup])
        page.parentId = "operator"
        page.instance = target.instance
        page.parGroupTargets = {}
        page.parGroupTargetsByName = {}
        page.sequenceTargets = {}
        page.sequenceTargetsByName = {}
        page.buildParGroupTargets()
        actions = page.parGroupTargets[target.id].getActions()
        self.assertTrue(all(not hasattr(action, "writesTo") for action in actions))


if __name__ == "__main__":
    unittest.main()
