import json
import tempfile
import unittest
from datetime import date

from codex_flipper_monitor.model import UsageDay, UsageSnapshot
from codex_flipper_monitor.service import MonitorService
from codex_flipper_monitor.state import Activity
from codex_flipper_monitor.transport import TransportDelivery


class FakeTransport:
    def __init__(self) -> None:
        self.available = True
        self.payloads = []

    def usb_available(self) -> bool:
        return self.available

    def send(self, payload: str) -> TransportDelivery:
        self.payloads.append(payload)
        if self.available:
            return TransportDelivery("usb", "/dev/cu.flipper")
        return TransportDelivery("ble", "TEST1")

    def close(self) -> None:
        pass


class MissingSideThread:
    def read_thread(self, _session_id: str):
        raise RuntimeError("thread not loaded: temporary-side-thread")


class ServiceTransportTransitionTests(unittest.TestCase):
    def test_prepare_runtime_does_not_restore_stale_working_state(self) -> None:
        with tempfile.TemporaryDirectory() as runtime_dir:
            with open("%s/state.json" % runtime_dir, "w", encoding="utf-8") as handle:
                json.dump({"status": "working", "activeThreads": 2}, handle)
            service = MonitorService(
                "/usr/bin/true", runtime_dir, sink=FakeTransport()
            )
            service._prepare_runtime()
            self.assertEqual(len(service.state.active_turns), 0)
            self.assertEqual(service.state.activity.value, "I")

    def test_prepare_runtime_restores_completed_task_history(self) -> None:
        with tempfile.TemporaryDirectory() as runtime_dir:
            with open("%s/state.json" % runtime_dir, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "completionSequence": 17,
                        "tasks": [
                            {
                                "number": 4,
                                "label": "QDIG",
                                "status": "done",
                                "startedAt": 100,
                                "updatedAt": 120,
                                "tokens": {"total": 500, "last": 50},
                            },
                            {
                                "number": 5,
                                "label": "STALE",
                                "status": "working",
                                "startedAt": 130,
                                "updatedAt": 140,
                                "tokens": None,
                            },
                            {
                                "number": 6,
                                "label": "NO_NAME",
                                "status": "done",
                                "startedAt": 150,
                                "updatedAt": 160,
                                "tokens": None,
                            },
                        ]
                    },
                    handle,
                )
            service = MonitorService(
                "/usr/bin/true", runtime_dir, sink=FakeTransport()
            )
            service._prepare_runtime()
            tasks = service.state.recent_tasks()
            self.assertEqual(len(tasks), 1)
            self.assertEqual(tasks[0].label, "QDIG")
            self.assertEqual(tasks[0].activity, Activity.DONE)
            self.assertEqual(tasks[0].token_usage.total_tokens, 500)
            self.assertEqual(service.state.completion_sequence, 17)

    def test_unloaded_thread_is_identified_as_side(self) -> None:
        with tempfile.TemporaryDirectory() as runtime_dir:
            service = MonitorService(
                "/usr/bin/true", runtime_dir, sink=FakeTransport()
            )
            service.codex = MissingSideThread()
            label, transcript_path, is_side = service._resolve_task_metadata(
                "temporary-side-thread"
            )
            self.assertEqual(label, "SIDE")
            self.assertIsNone(transcript_path)
            self.assertTrue(is_side)

    def test_publish_persists_private_task_identity_locally(self) -> None:
        with tempfile.TemporaryDirectory() as runtime_dir:
            service = MonitorService(
                "/usr/bin/true", runtime_dir, sink=FakeTransport()
            )
            service._prepare_runtime()
            service.state.handle_hook(
                "start",
                "turn-1",
                session_id="session-1",
                transcript_path=None,
                label="TASK",
                timestamp=100,
            )
            service._publish()
            with open("%s/state.json" % runtime_dir, encoding="utf-8") as handle:
                stored = json.load(handle)
            self.assertEqual(stored["tasks"][0]["sessionId"], "session-1")
            self.assertEqual(stored["tasks"][0]["turnId"], "turn-1")
            self.assertEqual(stored["completionSequence"], 0)

    def test_usb_changes_immediately_republish_cached_state(self) -> None:
        with tempfile.TemporaryDirectory() as runtime_dir:
            sink = FakeTransport()
            service = MonitorService("/usr/bin/true", runtime_dir, sink=sink)
            service._prepare_runtime()

            service._check_usb_transition()
            self.assertEqual(sink.payloads, [])

            sink.available = False
            service._check_usb_transition()
            self.assertEqual(len(sink.payloads), 2)
            self.assertIn("codexmon v=2", sink.payloads[0])
            self.assertIn("codextasks v=1 n=0", sink.payloads[1])

            service._check_usb_transition()
            self.assertEqual(len(sink.payloads), 2)

            sink.available = True
            service._check_usb_transition()
            self.assertEqual(len(sink.payloads), 4)

    def test_publish_sends_state_then_usage(self) -> None:
        with tempfile.TemporaryDirectory() as runtime_dir:
            sink = FakeTransport()
            service = MonitorService("/usr/bin/true", runtime_dir, sink=sink)
            service._prepare_runtime()
            service.state.usage = UsageSnapshot(
                lifetime_tokens=100,
                peak_daily_tokens=50,
                longest_running_turn_sec=10,
                current_streak_days=2,
                longest_streak_days=3,
                daily=(UsageDay(date(2026, 8, 7), 25_000_000),),
                fetched_at=200,
            )
            service._publish()
            self.assertEqual(len(sink.payloads), 3)
            self.assertTrue(sink.payloads[0].startswith("codexmon v=2"))
            self.assertTrue(sink.payloads[1].startswith("codexuse v=1"))
            self.assertTrue(sink.payloads[2].startswith("codextasks v=1"))


if __name__ == "__main__":
    unittest.main()
