import json
import sys
import unittest
from pathlib import Path


MOD_DIR = Path(__file__).parents[1] / "py" / "mod"
if str(MOD_DIR) not in sys.path:
    sys.path.insert(0, str(MOD_DIR))

from connection import RegistrationCoordinator


def command(command_id, tx):
    return json.dumps({
        "event": "ws:m:command",
        "data": {"commandId": command_id, "command": {"tx": tx}},
    })


class RegistrationCoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.now = 10.0
        self.errors = []
        self.coordinator = RegistrationCoordinator(
            clock=lambda: self.now,
            reject=lambda tx, command_id, message: self.errors.append((tx, command_id, message)),
            max_commands=2,
            max_bytes=10_000,
        )

    def test_sensitive_commands_queue_and_drain_in_fifo_order(self):
        self.coordinator.socket_opened()
        query = command("QuerySomething", "query")
        first = command("ExecTargetAction", "first")
        second = command("ResendEmitterValue", "second")

        self.assertFalse(self.coordinator.defer_if_loading(query))
        self.assertTrue(self.coordinator.defer_if_loading(first))
        self.assertTrue(self.coordinator.defer_if_loading(second))

        self.coordinator.registration_succeeded(self.coordinator.generation)
        dispatched = []
        self.coordinator.drain(dispatched.append, command_limit=1, time_limit=1.0)
        self.assertEqual(dispatched, [first])

        self.assertTrue(self.coordinator.defer_if_loading(command("ExecTargetAction", "third")))
        self.coordinator.drain(dispatched.append, command_limit=8, time_limit=1.0)
        self.assertEqual(dispatched, [first, second, command("ExecTargetAction", "third")])

    def test_disconnect_invalidates_generation_and_discards_work(self):
        generation = self.coordinator.socket_opened()
        self.coordinator.defer_if_loading(command("ExecTargetAction", "old"))

        self.coordinator.socket_closed()

        self.assertFalse(self.coordinator.is_current(generation))
        self.assertEqual(self.coordinator.queued_count, 0)
        self.assertFalse(self.coordinator.is_active)

    def test_queue_overflow_rejects_the_new_command(self):
        self.coordinator.socket_opened()
        self.coordinator.defer_if_loading(command("ExecTargetAction", "one"))
        self.coordinator.defer_if_loading(command("ExecTargetAction", "two"))

        self.assertTrue(self.coordinator.defer_if_loading(command("ExecTargetAction", "three")))

        self.assertEqual(self.coordinator.queued_count, 2)
        self.assertEqual(self.errors[0][:2], ("three", "ExecTargetAction"))

    def test_failed_registration_retries_with_a_cap(self):
        generation = self.coordinator.socket_opened()
        self.coordinator.registration_failed(generation)
        self.assertFalse(self.coordinator.retry_due())

        self.now += 1.0
        self.assertTrue(self.coordinator.retry_due())
        self.coordinator.registration_failed(generation)

        for _ in range(10):
            self.now += 60.0
            self.coordinator.registration_failed(generation)

        self.assertLessEqual(self.coordinator.retry_delay, 30.0)


if __name__ == "__main__":
    unittest.main()
