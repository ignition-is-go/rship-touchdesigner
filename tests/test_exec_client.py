import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path


MOD_DIR = Path(__file__).parents[1] / "py" / "mod"
if str(MOD_DIR) not in sys.path:
    sys.path.insert(0, str(MOD_DIR))

td_stub = sys.modules.setdefault("td", types.ModuleType("td"))
td_stub.OP = type("OP", (), {})
td_stub.ParGroup = type("ParGroup", (), {})

SPEC = importlib.util.spec_from_file_location("rship_exec_under_test", MOD_DIR / "exec.py")
EXEC = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EXEC)


class ExecClientTests(unittest.TestCase):
    def setUp(self):
        self.client = EXEC.ExecClient()
        self.client.log = lambda message: None
        self.frames = []
        self.client.setSend(lambda text: self.frames.append(json.loads(text)))

    def add_action(self, action_id="action", target_id="target", calls=None):
        calls = calls if calls is not None else []
        action = EXEC.Action(
            id=action_id,
            name=action_id,
            targetId=target_id,
            serviceId="service",
            schema={},
            handler=lambda action, data: calls.append(data),
        )
        self.client.actions[action_id] = action
        self.client.saveHandler(action_id, action.handler)
        return calls

    def test_query_and_report_handlers_are_one_shot(self):
        calls = []
        self.client.queryHandlers["query"] = lambda response: calls.append(response.tx)
        self.client.reportHandlers["report"] = lambda response: calls.append(response.tx)

        self.client.parseQueryResponse({"tx": "query", "upserts": []})
        self.client.parseReportResponse({"tx": "report", "response": {}})

        self.assertEqual(calls, ["query", "report"])
        self.assertNotIn("query", self.client.queryHandlers)
        self.assertNotIn("report", self.client.reportHandlers)

    def test_command_cannot_address_another_instance_or_target(self):
        calls = self.add_action()
        self.client.instanceId = "instance"

        for instance_id, target_id in (("other", "target"), ("instance", "other")):
            self.client.handleIncomingExecTargetAction("ExecTargetAction", {
                "tx": f"{instance_id}:{target_id}",
                "instanceId": instance_id,
                "action": {"id": "action", "targetId": target_id},
                "data": 7,
            })

        self.assertEqual(calls, [])
        errors = [frame for frame in self.frames if frame["event"] == "ws:m:command-error"]
        self.assertEqual(len(errors), 2)

    def test_compact_batch_continues_after_a_bad_assignment(self):
        calls = self.add_action(action_id="valid")
        self.client.instanceId = "instance"

        self.client.handleCompactBatchTargetAction("CompactBatchTargetAction", {
            "tx": "batch",
            "createdAt": "now",
            "groups": [
                {
                    "actionId": "missing",
                    "payloads": [1],
                    "assignments": [{"instanceId": "instance", "targetId": "target", "payloadIndex": 0}],
                },
                {
                    "actionId": "valid",
                    "payloads": [2],
                    "assignments": [{"instanceId": "instance", "targetId": "target", "payloadIndex": 0}],
                },
            ],
        })

        self.assertEqual(calls, [2])
        self.assertEqual(self.frames[-1]["event"], "ws:m:command-error")

    def test_event_is_a_snapshot_of_the_source_item(self):
        action = EXEC.Action(
            id="action",
            name="before",
            targetId="target",
            serviceId="service",
            schema={},
            handler=lambda action, data: None,
        )

        event = self.client.buildSetEvent(action)
        action.name = "after"
        del action.handler

        self.assertEqual(event.item["name"], "before")
        self.assertIn("handler", event.item)

    def test_resend_rejects_wrong_instance_and_unknown_emitter(self):
        self.client.instanceId = "instance"

        self.client.handleResendEmitterValue({
            "tx": "wrong-instance",
            "instanceId": "other",
            "emitterId": "value",
        }, respond=True)
        self.client.handleResendEmitterValue({
            "tx": "unknown-emitter",
            "instanceId": "instance",
            "emitterId": "missing",
        }, respond=True)

        self.assertEqual(
            [frame["event"] for frame in self.frames],
            ["ws:m:command-error", "ws:m:command-error"],
        )


if __name__ == "__main__":
    unittest.main()
