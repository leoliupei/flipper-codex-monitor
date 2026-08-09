import unittest

from codex_flipper_monitor.hook import sanitize_event


class HookPrivacyTests(unittest.TestCase):
    def test_start_drops_sensitive_fields(self) -> None:
        event = sanitize_event(
            {
                "hook_event_name": "UserPromptSubmit",
                "turn_id": "turn-1",
                "session_id": "session-1",
                "transcript_path": "/private/transcript.jsonl",
                "prompt": "secret prompt",
                "cwd": "/private/project",
                "last_assistant_message": "secret response",
            }
        )
        self.assertEqual(
            event,
            {
                "event": "start",
                "turnId": "turn-1",
                "sessionId": "session-1",
                "transcriptPath": "/private/transcript.jsonl",
            },
        )
        self.assertNotIn("cwd", event)

    def test_stop_is_minimal(self) -> None:
        event = sanitize_event(
            {
                "hook_event_name": "Stop",
                "turn_id": "turn-1",
                "transcript_path": "/private/transcript",
            }
        )
        self.assertEqual(
            event,
            {
                "event": "stop",
                "turnId": "turn-1",
                "sessionId": "turn-1",
                "transcriptPath": "/private/transcript",
            },
        )
        self.assertNotIn("prompt", event)
        self.assertNotIn("lastAssistantMessage", event)

    def test_unsupported_event_is_ignored(self) -> None:
        self.assertIsNone(sanitize_event({"hook_event_name": "PreToolUse"}))


if __name__ == "__main__":
    unittest.main()
