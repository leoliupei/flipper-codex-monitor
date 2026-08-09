import json
import os
from pathlib import Path
from typing import Any, Dict, Optional, Set

from .model import TokenUsageSnapshot


INITIAL_TAIL_BYTES = 2 * 1024 * 1024


def _nonnegative_int(value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        return 0
    return max(0, value)


def parse_token_count_record(record: Dict[str, Any]) -> Optional[TokenUsageSnapshot]:
    if record.get("type") != "event_msg":
        return None
    payload = record.get("payload")
    if not isinstance(payload, dict) or payload.get("type") != "token_count":
        return None
    info = payload.get("info")
    if not isinstance(info, dict):
        return None
    total = info.get("total_token_usage")
    last = info.get("last_token_usage")
    if not isinstance(total, dict) or not isinstance(last, dict):
        return None

    raw_window = info.get("model_context_window")
    context_window = _nonnegative_int(raw_window) or None
    return TokenUsageSnapshot(
        total_tokens=_nonnegative_int(total.get("total_tokens")),
        last_tokens=_nonnegative_int(last.get("total_tokens")),
        last_input_tokens=_nonnegative_int(last.get("input_tokens")),
        input_tokens=_nonnegative_int(total.get("input_tokens")),
        cached_input_tokens=_nonnegative_int(total.get("cached_input_tokens")),
        cache_write_input_tokens=_nonnegative_int(
            total.get("cache_write_input_tokens")
        ),
        output_tokens=_nonnegative_int(total.get("output_tokens")),
        reasoning_output_tokens=_nonnegative_int(
            total.get("reasoning_output_tokens")
        ),
        model_context_window=context_window,
    )


def parse_terminal_turn_record(record: Dict[str, Any]) -> Optional[str]:
    if record.get("type") != "event_msg":
        return None
    payload = record.get("payload")
    if not isinstance(payload, dict):
        return None
    if payload.get("type") not in ("task_complete", "turn_aborted"):
        return None
    turn_id = payload.get("turn_id")
    return turn_id if isinstance(turn_id, str) and turn_id else None


class TranscriptTokenReader:
    """Fail-soft reader for the current Codex rollout JSONL representation."""

    def __init__(self, path: str, initial_tail_bytes: int = INITIAL_TAIL_BYTES) -> None:
        self.path = Path(path)
        self.initial_tail_bytes = max(4096, int(initial_tail_bytes))
        self.offset: Optional[int] = None
        self._terminal_turn_ids: Set[str] = set()

    def take_terminal_turn_ids(self) -> Set[str]:
        result = self._terminal_turn_ids
        self._terminal_turn_ids = set()
        return result

    def poll(self) -> Optional[TokenUsageSnapshot]:
        try:
            size = self.path.stat().st_size
        except OSError:
            return None

        initial_read = self.offset is None
        if initial_read:
            start = max(0, size - self.initial_tail_bytes)
        elif size < self.offset:
            start = 0
        else:
            start = self.offset

        try:
            with self.path.open("rb") as handle:
                handle.seek(start)
                data = handle.read()
        except OSError:
            return None
        if not data:
            self.offset = size
            return None

        if initial_read and start > 0:
            first_newline = data.find(b"\n")
            if first_newline < 0:
                self.offset = size
                return None
            start += first_newline + 1
            data = data[first_newline + 1 :]

        last_newline = data.rfind(b"\n")
        if last_newline < 0:
            self.offset = start
            return None
        complete = data[:last_newline]
        self.offset = start + last_newline + 1

        latest: Optional[TokenUsageSnapshot] = None
        for raw_line in complete.splitlines():
            try:
                record = json.loads(raw_line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if not isinstance(record, dict):
                continue
            parsed = parse_token_count_record(record)
            if parsed is not None:
                latest = parsed
            terminal_turn_id = parse_terminal_turn_record(record)
            if terminal_turn_id is not None:
                self._terminal_turn_ids.add(terminal_turn_id)
        return latest


def safe_codex_transcript_path(raw_path: object) -> Optional[str]:
    if not isinstance(raw_path, str) or not raw_path or len(raw_path) > 4096:
        return None
    try:
        candidate = Path(raw_path).expanduser().resolve()
    except OSError:
        return None
    roots = (
        Path(os.path.expanduser("~/.codex/sessions")).resolve(),
        Path(os.path.expanduser("~/.codex/archived_sessions")).resolve(),
    )
    if not any(candidate == root or root in candidate.parents for root in roots):
        return None
    return str(candidate)
