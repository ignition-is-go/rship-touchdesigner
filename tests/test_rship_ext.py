import builtins
import importlib
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


MOD_DIR = Path(__file__).parents[1] / "py" / "mod"
PY_DIR = MOD_DIR.parent
for path in (str(MOD_DIR), str(PY_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)

td_stub = sys.modules.setdefault("td", types.ModuleType("td"))
td_stub.OP = type("OP", (), {})
td_stub.ParGroup = type("ParGroup", (), {})
sys.modules.setdefault("tdu", types.SimpleNamespace(Dependency=lambda value: value))
sys.modules.setdefault("TDFunctions", types.SimpleNamespace(createProperty=lambda *args, **kwargs: None))
builtins.OP = td_stub.OP
builtins.ParGroup = td_stub.ParGroup
builtins.Page = type("Page", (), {})
builtins.ParMode = types.SimpleNamespace(CONSTANT="constant")

EXEC = importlib.import_module("exec")
RSHIP_EXT = importlib.import_module("RshipExt")
CONNECTION = importlib.import_module("connection")


class FakeLog:
    def Debug(self, *args):
        pass

    Info = Debug
    Warning = Debug
    Error = Debug


class FakeTarget:
    id = "target"
    streamSource = None

    def __init__(self, calls):
        self.calls = calls

    def collectChildren(self):
        return [self]

    def getTarget(self):
        return EXEC.Target("target", "Target", [], "service", "test")

    def getActions(self):
        return [EXEC.Action(
            "set", "Set", "target", "service", {},
            lambda action, data: self.calls.append(data),
            writesTo=EXEC.makeWriterRef("one"),
        )]

    def getEmitters(self):
        one = EXEC.Emitter("one", "One", "target", "service", {}, "/op.Value", lambda: 1)
        two = EXEC.Emitter("two", "Two", "target", "service", {}, "/op.Value", lambda: 2)
        return [one, two]

    def getStreamInfo(self):
        return None


def flatten(frames):
    events = []
    for frame in frames:
        if frame["event"] == "ws:m:event-batch":
            events.extend(frame["data"])
        elif frame["event"] == "ws:m:event":
            events.append(frame["data"])
    return events


class RshipExtRegistrationTests(unittest.TestCase):
    def setUp(self):
        self.frames = []
        self.client = EXEC.ExecClient()
        self.client.log = lambda message: None
        self.client.setSend(lambda text: self.frames.append(json.loads(text)))
        self.calls = []
        self.extension = RSHIP_EXT.RshipExt.__new__(RSHIP_EXT.RshipExt)
        self.extension.instance = EXEC.Instance(
            "machine:service", "service", "service", "touchdesigner",
            EXEC.InstanceStatus.Starting, "machine", "#000000",
        )
        self.extension.websocketOp = types.SimpleNamespace(sendText=self.client.send)
        self.extension.conn = types.SimpleNamespace(isConnected=True)
        self.extension.registration = CONNECTION.RegistrationCoordinator(
            reject=self.client.sendCommandError
        )
        self.generation = self.extension.registration.socket_opened()
        self.extension.opTargets = {"target": FakeTarget(self.calls)}
        self.extension.allTouchTargets = {}
        self.extension.emitterIndex = {}
        self.extension.emitterHandlers = {}
        self.extension._registeredActionIds = set()
        self.extension._registeredProviderIds = set()
        self.extension._publishedTargetIds = set()
        self.extension._pendingPulseEvents = {}
        self.extension._pendingExplicitPulses = []
        self.extension._pendingOfflineTargetIds = set()
        self.extension.sentTargetStatuses = {}
        self.extension.updateStatsPage = lambda **kwargs: None
        self.extension._ensureInstance = lambda: True
        self.extension.cookTargetList = lambda: None
        self.extension.buildTargets = lambda: None
        self.extension._drainRegistrationCommands = lambda: None
        self.extension._flushPendingPulses = lambda: None
        RSHIP_EXT.op = types.SimpleNamespace(RS_LOG=FakeLog())

    def test_definitions_and_seeds_precede_online_and_available(self):
        with patch.object(RSHIP_EXT, "CLIENT", self.client), \
             patch.object(RSHIP_EXT.comp_engine, "get_engines", return_value=[]), \
             patch.object(RSHIP_EXT.comp_engine, "prune_dead_engines", return_value=[]):
            self.extension.sendProjectData(self.generation)

        events = flatten(self.frames)
        item_types = [event["itemType"] for event in events]
        self.assertLess(item_types.index("Action"), item_types.index("Pulse"))
        self.assertLess(item_types.index("Emitter"), item_types.index("Pulse"))
        self.assertLess(item_types.index("Pulse"), item_types.index("TargetStatus"))
        self.assertEqual(item_types[-1], "Instance")
        self.assertEqual(events[-1]["item"]["status"], "Available")

    def test_one_change_key_pulses_every_emitter(self):
        with patch.object(RSHIP_EXT, "CLIENT", self.client), \
             patch.object(RSHIP_EXT.comp_engine, "get_engines", return_value=[]), \
             patch.object(RSHIP_EXT.comp_engine, "prune_dead_engines", return_value=[]):
            self.extension.sendProjectData(self.generation)
            self.extension.registration.registration_succeeded(self.generation)
            self.frames.clear()
            self.extension.PulseEmitter(types.SimpleNamespace(path="/op"), "Value")

        pulses = [event["item"]["emitterId"] for event in flatten(self.frames)]
        self.assertEqual(pulses, ["one", "two"])

    def test_attempt_starts_instance_before_registration(self):
        with patch.object(RSHIP_EXT, "CLIENT", self.client), \
             patch.object(RSHIP_EXT.comp_engine, "get_engines", return_value=[]), \
             patch.object(RSHIP_EXT.comp_engine, "prune_dead_engines", return_value=[]):
            self.extension._attemptRegistration()

        events = flatten(self.frames)
        self.assertEqual(events[0]["itemType"], "Instance")
        self.assertEqual(events[0]["item"]["status"], "Starting")
        self.assertEqual(events[-1]["item"]["status"], "Available")
        self.assertTrue(self.extension.registration.is_active)


if __name__ == "__main__":
    unittest.main()
