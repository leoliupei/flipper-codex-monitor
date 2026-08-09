import unittest
from datetime import date, datetime, time, timezone

from codex_flipper_monitor.model import (
    QuotaSnapshot,
    QuotaWindow,
    TokenUsageSnapshot,
    UsageDay,
    UsageSnapshot,
)
from codex_flipper_monitor.protocol import (
    encode_cli_command,
    encode_task_commands,
    encode_usage_command,
)
from codex_flipper_monitor.state import Activity, MonitorState


class MonitorStateTests(unittest.TestCase):
    def test_working_done_idle_lifecycle(self) -> None:
        state = MonitorState()
        state.handle_hook("start", "turn-a", now=0, timestamp=100)
        state.handle_hook("start", "turn-b", now=1, timestamp=101)
        self.assertEqual(state.activity, Activity.WORKING)
        self.assertEqual(len(state.active_turns), 2)
        self.assertEqual(state.state_changed_at, 100)
        state.handle_hook("stop", "turn-a", now=2, timestamp=102)
        self.assertEqual(state.activity, Activity.WORKING)
        self.assertEqual(state.completion_sequence, 1)
        self.assertEqual(state.last_completed_at, 102)
        state.handle_hook("stop", "turn-b", now=3, timestamp=103)
        self.assertEqual(state.activity, Activity.DONE)
        self.assertEqual(state.completion_sequence, 2)
        self.assertEqual(state.last_completed_at, 103)
        self.assertFalse(state.advance(now=12.9))
        self.assertTrue(state.advance(now=13, timestamp=113))
        self.assertEqual(state.activity, Activity.IDLE)
        self.assertEqual(state.state_changed_at, 113)

    def test_protocol_contains_only_allowlisted_fields(self) -> None:
        state = MonitorState(
            quota=QuotaSnapshot(
                plan_type="pro",
                windows=(QuotaWindow(10080, 5, 1786160715),),
                reset_credits_available=1,
                fetched_at=100,
            )
        )
        state.handle_hook("start", "private-turn-id", now=0, timestamp=50)
        command = encode_cli_command(state, health_flags=3)
        self.assertEqual(
            command.split(" z=", 1)[0],
            "codexmon v=2 q=5 d=10080 r=1786160715 h=11 m=45 c=1 s=W n=1 p=P "
            "a=50 l=0 f=0 t=100",
        )
        self.assertRegex(command, r" z=-?\d+ e=3\r$")
        self.assertNotIn("private-turn-id", command)

    def test_usage_protocol_is_fixed_width_private_and_ble_safe(self) -> None:
        usage = UsageSnapshot(
            lifetime_tokens=23_587_528_907,
            peak_daily_tokens=1_032_483_805,
            longest_running_turn_sec=45_960,
            current_streak_days=55,
            longest_streak_days=55,
            daily=(
                UsageDay(date(2026, 8, 5), 45_431_777),
                UsageDay(date(2026, 8, 7), 243_235_914),
            ),
            fetched_at=200,
        )
        command = encode_usage_command(usage)
        self.assertTrue(command.startswith("codexuse v=1 u=23587528907"))
        self.assertIn(" f=200 ", command)
        latest_timestamp = int(
            datetime.combine(date(2026, 8, 7), time.min, tzinfo=timezone.utc).timestamp()
        )
        self.assertIn(" e=%d " % latest_timestamp, command)
        encoded = command.split(" z=", 1)[1].rstrip("\r")
        self.assertEqual(len(encoded), 90)
        self.assertLessEqual(len(command.encode("ascii")), 191)

    def test_tasks_are_grouped_by_session_and_protocol_is_private(self) -> None:
        state = MonitorState()
        state.handle_hook(
            "start",
            "private-turn-a",
            session_id="private-session-a",
            transcript_path="/private/transcript-a.jsonl",
            label="FLIPPER",
            now=0,
            timestamp=100,
        )
        state.update_task_usage(
            "private-session-a",
            TokenUsageSnapshot(
                total_tokens=843_973,
                last_tokens=14_320,
                last_input_tokens=13_900,
                input_tokens=520_432,
                cached_input_tokens=388_096,
                cache_write_input_tokens=0,
                output_tokens=8_820,
                reasoning_output_tokens=1_625,
                model_context_window=258_400,
            ),
            timestamp=105,
        )
        state.handle_hook(
            "start",
            "private-turn-b",
            session_id="private-session-a",
            now=1,
            timestamp=110,
        )
        self.assertEqual(len(state.tasks), 1)
        self.assertEqual(state.recent_tasks()[0].number, 1)

        commands = encode_task_commands(state)
        self.assertEqual(commands[0], "codextasks v=1 n=1\r")
        self.assertTrue(
            commands[1].startswith(
                "codextask v=1 k=0 d=1 b=FLIPPER s=W e=1 x=0 "
            )
        )
        self.assertLessEqual(len(commands[1].encode("ascii")), 191)
        combined = "".join(commands)
        self.assertNotIn("private-session", combined)
        self.assertNotIn("private-turn", combined)
        self.assertNotIn("transcript", combined)

    def test_completed_tasks_remain_and_sort_by_recent_activity(self) -> None:
        state = MonitorState()
        state.handle_hook("start", "turn-a", timestamp=100, now=0)
        state.handle_hook("start", "turn-b", timestamp=105, now=1)
        state.handle_hook("stop", "turn-b", timestamp=110, now=2)
        state.advance(now=600, timestamp=700)
        self.assertEqual(
            [task.turn_id for task in state.recent_tasks()],
            ["turn-b", "turn-a"],
        )

    def test_completed_task_history_keeps_latest_sixteen(self) -> None:
        state = MonitorState()
        for index in range(17):
            turn_id = "turn-%d" % index
            state.handle_hook("start", turn_id, timestamp=100 + index * 2, now=index)
            state.handle_hook(
                "stop", turn_id, timestamp=101 + index * 2, now=index + 0.5
            )
        tasks = state.recent_tasks()
        self.assertEqual(len(tasks), 16)
        self.assertEqual(tasks[0].turn_id, "turn-16")
        self.assertNotIn("turn-0", [task.turn_id for task in tasks])

    def test_side_task_is_not_retained_after_stop(self) -> None:
        state = MonitorState()
        state.handle_hook(
            "start",
            "side-turn",
            session_id="side-session",
            label="SIDE",
            is_side=True,
            timestamp=100,
            now=0,
        )
        task = state.recent_tasks()[0]
        self.assertEqual(task.label, "SIDE")
        self.assertTrue(task.is_side)
        self.assertIn(" x=1 ", encode_task_commands(state)[1])

        state.handle_hook(
            "stop",
            "side-turn",
            session_id="side-session",
            timestamp=110,
            now=1,
        )
        self.assertEqual(state.recent_tasks(), [])
        self.assertEqual(state.activity, Activity.DONE)
        self.assertEqual(state.completion_sequence, 1)

    def test_duplicate_stop_does_not_repeat_completion(self) -> None:
        state = MonitorState()
        state.handle_hook("start", "turn-a", timestamp=100, now=0)
        state.handle_hook("stop", "turn-a", timestamp=110, now=1)
        state.handle_hook("stop", "turn-a", timestamp=120, now=2)
        self.assertEqual(state.completion_sequence, 1)
        self.assertEqual(state.last_completed_at, 110)

    def test_unobservable_side_task_expires_without_affecting_real_work(self) -> None:
        state = MonitorState()
        state.handle_hook(
            "start",
            "real-turn",
            session_id="real-session",
            label="REAL",
            timestamp=100,
            now=0,
        )
        state.handle_hook(
            "start",
            "side-turn",
            session_id="side-session",
            label="SIDE",
            is_side=True,
            timestamp=101,
            now=1,
        )

        self.assertFalse(state.expire_stale_side_tasks(timestamp=130))
        self.assertTrue(state.expire_stale_side_tasks(timestamp=131))
        self.assertEqual([task.label for task in state.recent_tasks()], ["REAL"])
        self.assertEqual(state.active_turns, {"real-turn"})
        self.assertEqual(state.activity, Activity.WORKING)

    def test_unobservable_side_task_expires_to_idle(self) -> None:
        state = MonitorState()
        state.handle_hook(
            "start",
            "side-turn",
            session_id="side-session",
            label="SIDE",
            is_side=True,
            timestamp=100,
            now=0,
        )

        self.assertTrue(state.expire_stale_side_tasks(timestamp=130))
        self.assertEqual(state.recent_tasks(), [])
        self.assertEqual(state.active_turns, set())
        self.assertEqual(state.activity, Activity.IDLE)


if __name__ == "__main__":
    unittest.main()
