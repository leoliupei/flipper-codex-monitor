import json
import os
import socket
import sys
from typing import Any, Dict, Optional


MAX_INPUT_BYTES = 1024 * 1024


def default_socket_path() -> str:
    runtime = os.environ.get(
        "CODEX_FLIPPER_RUNTIME",
        os.path.expanduser("~/Library/Application Support/CodexFlipperMonitor"),
    )
    return os.path.join(runtime, "reporter.sock")


def sanitize_event(payload: Dict[str, Any]) -> Optional[Dict[str, str]]:
    name = payload.get("hook_event_name")
    turn_id = payload.get("turn_id")
    if name == "UserPromptSubmit":
        event = "start"
    elif name == "Stop":
        event = "stop"
    else:
        return None
    if not isinstance(turn_id, str) or not turn_id or len(turn_id) > 256:
        return None
    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not session_id or len(session_id) > 256:
        session_id = turn_id
    result = {"event": event, "turnId": turn_id, "sessionId": session_id}
    transcript_path = payload.get("transcript_path")
    if (
        isinstance(transcript_path, str)
        and transcript_path
        and len(transcript_path) <= 4096
    ):
        result["transcriptPath"] = transcript_path
    return result


def deliver(event: Dict[str, str], socket_path: Optional[str] = None) -> None:
    data = json.dumps(event, separators=(",", ":")).encode("utf-8")
    target = socket_path or default_socket_path()
    client = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    try:
        client.sendto(data, target)
    finally:
        client.close()


def main() -> int:
    raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
    if len(raw) > MAX_INPUT_BYTES:
        print("{}")
        return 0
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        print("{}")
        return 0
    event = sanitize_event(payload) if isinstance(payload, dict) else None
    if event is not None:
        try:
            deliver(event)
        except OSError:
            pass
    print("{}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
