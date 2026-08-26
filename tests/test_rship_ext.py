import importlib.util
from pathlib import Path
import sys
import types
import unittest


ROOT = Path(__file__).parents[1]
MOD_DIR = ROOT / "py" / "mod"
if str(MOD_DIR) not in sys.path:
    sys.path.insert(0, str(MOD_DIR))


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


if "exec" not in sys.modules:
    EXEC = load_module("exec", MOD_DIR / "exec.py")
else:
    EXEC = sys.modules["exec"]

td_functions = types.ModuleType("TDFunctions")
td_functions.createProperty = lambda *args, **kwargs: None
sys.modules.setdefault("TDFunctions", td_functions)

op_target = types.ModuleType("op_target")
op_target.OPTarget = type("OPTarget", (), {})
sys.modules.setdefault("op_target", op_target)

target = types.ModuleType("target")
target.TouchTarget = type("TouchTarget", (), {})
sys.modules.setdefault("target", target)

RSHIP = load_module("rship_ext_under_test", ROOT / "py" / "RshipExt.py")


class FakeLog:
    def Debug(self, *args):
        pass

    def Info(self, *args):
        pass

    def Warning(self, *args):
        pass

    def Error(self, *args):
        pass


class FakeClient:
    def __init__(self):
        self.actions = {}
        self.handlers = {}
        self.batches = []

    def setSend(self, send):
        self.send = send

    def buildSetEvent(self, item, itemType=None):
        return types.SimpleNamespace(item=item, itemType=itemType)

    def buildTargetStatusEvent(self, targetId, instanceId, status):
        return types.SimpleNamespace(targetId=targetId, instanceId=instanceId, status=status)

    def saveHandler(self, actionId, handler):
        self.handlers[actionId] = handler

    def sendEventBatch(self, events):
        self.batches.append(list(events))


class FakeTouchTarget:
    def __init__(self, action, emitter):
        self.id = "target"
        self._action = action
        self._emitter = emitter

    def getTarget(self):
        return EXEC.Target(
            id=self.id,
            name="Target",
            parentTargets=[],
            serviceId="service",
            category="Test",
        )

    def getActions(self):
        return [self._action]

    def getEmitters(self):
        return [self._emitter]


class FakeOpTarget:
    def __init__(self, child):
        self.child = child

    def collectChildren(self):
        return [self.child]

    def getStreamInfo(self):
        return None


class RshipExtRetentionTests(unittest.TestCase):
    def setUp(self):
        self.original_client = RSHIP.CLIENT
        self.original_op = getattr(RSHIP, "op", None)
        self.original_run = getattr(RSHIP, "run", None)
        self.client = FakeClient()
        RSHIP.CLIENT = self.client
        RSHIP.op = types.SimpleNamespace(RS_LOG=FakeLog())

    def tearDown(self):
        RSHIP.CLIENT = self.original_client
        if self.original_op is None:
            delattr(RSHIP, "op")
        else:
            RSHIP.op = self.original_op
        if self.original_run is None:
            if hasattr(RSHIP, "run"):
                delattr(RSHIP, "run")
        else:
            RSHIP.run = self.original_run

    def make_extension(self):
        extension = RSHIP.RshipExt.__new__(RSHIP.RshipExt)
        extension.instance = types.SimpleNamespace(id="machine:service", serviceId="service")
        extension.websocketOp = types.SimpleNamespace(sendText=lambda text: None)
        extension.emitterIndex = {}
        extension.emitterHandlers = {}
        extension.allTouchTargets = {}
        extension.sentTargetStatuses = {}
        extension._pendingPulses = {}
        extension._pendingExplicitPulses = []
        extension._pulseFlushScheduled = False
        extension.wsConnected = True
        extension.updateStatsPage = lambda **kwargs: None
        return extension

    def test_project_refresh_reads_each_emitter_once_and_prunes_stale_actions(self):
        extension = self.make_extension()
        handler_calls = []

        action = EXEC.Action(
            id="current-action",
            name="Current",
            targetId="target",
            serviceId="service",
            schema=None,
            handler=lambda action, data: None,
        )
        emitter = EXEC.Emitter(
            id="sequence-updated",
            name="Updated",
            targetId="target",
            serviceId="service",
            schema=None,
            changeKey="/target.Sequence",
            handler=lambda: handler_calls.append(True) or {"value": 1},
        )
        emitter.changeKeys = ["/target.Sequence", "/target.Member"]
        child = FakeTouchTarget(action, emitter)
        extension.opTargets = {"op": FakeOpTarget(child)}

        stale = types.SimpleNamespace(serviceId="service")
        other = types.SimpleNamespace(serviceId="other-service")
        self.client.actions = {"stale-action": stale, "other-action": other}
        self.client.handlers = {
            "stale-action": object(),
            "other-action": object(),
        }

        extension.sendProjectData(sendEmitterValues=True)

        self.assertEqual(len(handler_calls), 1)
        self.assertNotIn("stale-action", self.client.actions)
        self.assertNotIn("stale-action", self.client.handlers)
        self.assertIn("other-action", self.client.actions)
        self.assertIn("current-action", self.client.actions)

    def test_project_refresh_sends_online_statuses_after_all_definitions(self):
        extension = self.make_extension()

        action = EXEC.Action(
            id="current-action",
            name="Current",
            targetId="target",
            serviceId="service",
            schema=None,
            handler=lambda action, data: None,
        )
        emitter = EXEC.Emitter(
            id="target-updated",
            name="Updated",
            targetId="target",
            serviceId="service",
            schema=None,
            changeKey="/target.Value",
            handler=lambda: {"value": 1},
        )
        extension.opTargets = {"op": FakeOpTarget(FakeTouchTarget(action, emitter))}

        extension.sendProjectData()

        batch = self.client.batches[0]
        status_indexes = [index for index, event in enumerate(batch) if hasattr(event, "status")]
        definition_indexes = [index for index, event in enumerate(batch) if hasattr(event, "item")]
        self.assertTrue(status_indexes)
        self.assertLess(max(definition_indexes), min(status_indexes))

    def test_normal_updates_coalesce_but_explicit_generator_pulses_do_not(self):
        extension = self.make_extension()
        scheduled = []
        RSHIP.run = lambda *args, **kwargs: scheduled.append((args, kwargs))
        owner = types.SimpleNamespace(path="/generator")
        emitter = types.SimpleNamespace(id="generator-updated")
        extension.emitterIndex["/generator.Generator"] = emitter

        value = {"count": 0}

        def handler():
            value["count"] += 1
            return {"count": value["count"]}

        extension.emitterHandlers["/generator.Generator"] = handler

        extension.PulseEmitter(owner, "Generator")
        extension.PulseEmitter(owner, "Generator")
        extension.PulseEmitter(owner, "Generator", preserveDuplicate=True)
        extension.PulseEmitter(owner, "Generator", preserveDuplicate=True)

        self.assertEqual(len(extension._pendingPulses), 1)
        self.assertEqual(len(extension._pendingExplicitPulses), 2)
        self.assertEqual(len(scheduled), 1)

        extension._flushPulses()

        self.assertEqual(len(self.client.batches), 1)
        self.assertEqual(len(self.client.batches[0]), 3)
        self.assertEqual(extension._pendingPulses, {})
        self.assertEqual(extension._pendingExplicitPulses, [])


if __name__ == "__main__":
    unittest.main()
