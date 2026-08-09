import json
import tempfile
import unittest
from pathlib import Path

from codex_flipper_monitor.transcript import (
    TranscriptTokenReader,
    parse_terminal_turn_record,
    parse_token_count_record,
)


def token_record(total: int, last: int) -> dict:
    return {
        "type": "event_msg",
        "payload": {
            "type": "token_count",
            "info": {
                "total_token_usage": {
                    "input_tokens": total - 20,
                    "cached_input_tokens": 10,
                    "cache_write_input_tokens": 3,
                    "output_tokens": 20,
                    "reasoning_output_tokens": 4,
                    "total_tokens": total,
                },
                "last_token_usage": {
                    "input_tokens": last - 2,
                    "cached_input_tokens": 1,
                    "cache_write_input_tokens": 0,
                    "output_tokens": 2,
                    "reasoning_output_tokens": 1,
                    "total_tokens": last,
                },
                "model_context_window": 258400,
            },
        },
    }


class TranscriptTokenReaderTests(unittest.TestCase):
    def test_parser_exposes_documented_token_breakdown(self) -> None:
        usage = parse_token_count_record(token_record(100, 12))
        self.assertIsNotNone(usage)
        assert usage is not None
        self.assertEqual(usage.total_tokens, 100)
        self.assertEqual(usage.last_tokens, 12)
        self.assertEqual(usage.last_input_tokens, 10)
        self.assertEqual(usage.cache_write_input_tokens, 3)
        self.assertEqual(usage.model_context_window, 258400)

    def test_reader_returns_only_new_complete_updates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rollout.jsonl"
            first = json.dumps(token_record(100, 12), separators=(",", ":"))
            second = json.dumps(token_record(250, 30), separators=(",", ":"))
            path.write_text(first + "\n", encoding="utf-8")
            reader = TranscriptTokenReader(str(path))
            self.assertEqual(reader.poll().total_tokens, 100)
            self.assertIsNone(reader.poll())
            with path.open("a", encoding="utf-8") as handle:
                handle.write(second)
            self.assertIsNone(reader.poll())
            with path.open("a", encoding="utf-8") as handle:
                handle.write("\n")
            self.assertEqual(reader.poll().total_tokens, 250)

    def test_reader_reports_manual_abort_and_completion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rollout.jsonl"
            path.write_text(
                json.dumps(
                    {
                        "type": "event_msg",
                        "payload": {
                            "type": "turn_aborted",
                            "turn_id": "turn-manual-stop",
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            reader = TranscriptTokenReader(str(path))
            self.assertIsNone(reader.poll())
            self.assertEqual(reader.take_terminal_turn_ids(), {"turn-manual-stop"})
            self.assertEqual(reader.take_terminal_turn_ids(), set())

    def test_terminal_parser_ignores_non_terminal_records(self) -> None:
        self.assertEqual(
            parse_terminal_turn_record(
                {
                    "type": "event_msg",
                    "payload": {"type": "task_complete", "turn_id": "turn-1"},
                }
            ),
            "turn-1",
        )
        self.assertIsNone(parse_terminal_turn_record(token_record(100, 12)))


if __name__ == "__main__":
    unittest.main()
