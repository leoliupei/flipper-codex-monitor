import argparse
import json
import os
import selectors
import signal
import socket
import time
from typing import Any, Dict, Optional, Set, Tuple

from .app_server import CodexAppServer
from .model import TokenUsageSnapshot, parse_rate_limits, parse_usage
from .protocol import encode_cli_command, encode_task_commands, encode_usage_command
from .state import Activity, MonitorState, TaskSnapshot
from .task_label import thread_label
from .transcript import TranscriptTokenReader, safe_codex_transcript_path
from .ble_sink import FlipperBleSink
from .transport import DualTransportSink, TransportDelivery


class MonitorService:
    def __init__(
        self,
        codex_bin: str,
        runtime_dir: str,
        quota_interval: float = 60.0,
        ble_helper: Optional[str] = None,
        ble_name: Optional[str] = None,
        sink: Optional[DualTransportSink] = None,
    ) -> None:
        self.runtime_dir = runtime_dir
        self.socket_path = os.path.join(runtime_dir, "reporter.sock")
        self.state_path = os.path.join(runtime_dir, "state.json")
        self.quota_interval = max(15.0, float(quota_interval))
        self.codex = CodexAppServer(codex_bin)
        ble = (
            FlipperBleSink(ble_helper, ble_name)
            if ble_helper is not None and ble_name is not None
            else None
        )
        self.sink = sink or DualTransportSink(ble=ble)
        self.state = MonitorState()
        self._socket: Optional[socket.socket] = None
        self._running = True
        self._next_quota_at = 0.0
        self._last_error: Optional[str] = None
        self._last_usb_available: Optional[bool] = None
        self._quota_healthy = False
        self._usage_healthy = False
        self._task_readers: Dict[str, TranscriptTokenReader] = {}
        self._pending_task_metadata: Set[str] = set()
        self._next_task_poll_at = 0.0
        self._next_task_metadata_at = 0.0

    def run(self) -> None:
        self._prepare_runtime()
        self._open_socket()
        self._install_signal_handlers()
        self._start_app_server()
        selector = selectors.DefaultSelector()
        assert self._socket is not None
        selector.register(self._socket, selectors.EVENT_READ)
        try:
            while self._running:
                now = time.monotonic()
                self._check_usb_transition()
                if now >= self._next_quota_at:
                    self._refresh_quota()
                self._drain_notifications()
                if now >= self._next_task_metadata_at:
                    self._next_task_metadata_at = now + 2.0
                    if self._refresh_task_metadata():
                        self._publish()
                if now >= self._next_task_poll_at:
                    self._next_task_poll_at = now + 0.5
                    task_changed = self._poll_task_usage()
                    if task_changed:
                        self._publish()
                if self.state.expire_stale_side_tasks():
                    self._publish()
                if self.state.advance(now):
                    self._publish()
                for key, _ in selector.select(timeout=0.5):
                    if key.fileobj is self._socket:
                        self._receive_hook()
        finally:
            selector.close()
            self.codex.stop()
            self.sink.close()
            if self._socket is not None:
                self._socket.close()
            try:
                os.unlink(self.socket_path)
            except FileNotFoundError:
                pass

    def _prepare_runtime(self) -> None:
        os.makedirs(self.runtime_dir, mode=0o700, exist_ok=True)
        os.chmod(self.runtime_dir, 0o700)
        self._restore_task_history()

    @staticmethod
    def _stored_nonnegative(value: object) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            return 0
        return max(0, value)

    def _restore_task_history(self) -> None:
        try:
            with open(self.state_path, "r", encoding="utf-8") as handle:
                stored = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return
        if isinstance(stored, dict):
            self.state.completion_sequence = min(
                0x7FFFFFFF,
                self._stored_nonnegative(stored.get("completionSequence")),
            )
        raw_tasks = stored.get("tasks") if isinstance(stored, dict) else None
        if not isinstance(raw_tasks, list):
            return

        for index, raw in enumerate(raw_tasks):
            if not isinstance(raw, dict):
                continue
            number = self._stored_nonnegative(raw.get("number"))
            started_at = self._stored_nonnegative(raw.get("startedAt"))
            updated_at = self._stored_nonnegative(raw.get("updatedAt"))
            if number < 1 or number > 99 or started_at == 0 or updated_at == 0:
                continue
            label = thread_label(raw.get("label"))
            session_id = raw.get("sessionId")
            turn_id = raw.get("turnId")
            transcript_path = safe_codex_transcript_path(raw.get("transcriptPath"))
            has_identity = (
                isinstance(session_id, str)
                and bool(session_id)
                and isinstance(turn_id, str)
                and bool(turn_id)
            )
            if not has_identity:
                if raw.get("status") == "working":
                    continue
                session_id = "restored-%d-%d-%d" % (number, started_at, index)
                turn_id = session_id

            if (
                raw.get("label") in ("NO_NAME", "SIDE")
                and transcript_path is None
                and not isinstance(raw.get("tokens"), dict)
            ):
                continue

            activity = Activity.DONE
            if raw.get("status") == "working" and transcript_path is not None:
                activity = Activity.WORKING

            token_usage = None
            tokens = raw.get("tokens")
            if isinstance(tokens, dict):
                raw_window = self._stored_nonnegative(tokens.get("modelContextWindow"))
                token_usage = TokenUsageSnapshot(
                    total_tokens=self._stored_nonnegative(tokens.get("total")),
                    last_tokens=self._stored_nonnegative(tokens.get("last")),
                    last_input_tokens=self._stored_nonnegative(tokens.get("lastInput")),
                    input_tokens=self._stored_nonnegative(tokens.get("input")),
                    cached_input_tokens=self._stored_nonnegative(tokens.get("cachedInput")),
                    cache_write_input_tokens=self._stored_nonnegative(
                        tokens.get("cacheWriteInput")
                    ),
                    output_tokens=self._stored_nonnegative(tokens.get("output")),
                    reasoning_output_tokens=self._stored_nonnegative(
                        tokens.get("reasoningOutput")
                    ),
                    model_context_window=raw_window or None,
                )

            task = TaskSnapshot(
                number=number,
                label=label,
                session_id=session_id,
                turn_id=turn_id,
                transcript_path=transcript_path,
                activity=activity,
                started_at=started_at,
                updated_at=updated_at,
                token_usage=token_usage,
                is_side=bool(raw.get("isSide")),
            )
            self.state.tasks[session_id] = task
            if activity is Activity.WORKING:
                self.state.active_turns.add(turn_id)
                self._task_readers[session_id] = TranscriptTokenReader(transcript_path)
                if label == "NO_NAME":
                    self._pending_task_metadata.add(session_id)

        self.state._trim_task_history()
        if self.state.active_turns:
            self.state.activity = Activity.WORKING

    def _open_socket(self) -> None:
        try:
            os.unlink(self.socket_path)
        except FileNotFoundError:
            pass
        receiver = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        receiver.bind(self.socket_path)
        os.chmod(self.socket_path, 0o600)
        receiver.setblocking(False)
        self._socket = receiver

    def _install_signal_handlers(self) -> None:
        def stop(_signum: int, _frame: object) -> None:
            self._running = False

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)

    def _start_app_server(self) -> None:
        try:
            self.codex.start()
            self._last_error = None
        except Exception as exc:
            self._last_error = "app-server: %s" % exc
            self._quota_healthy = False
            self._usage_healthy = False
            self._next_quota_at = time.monotonic() + self.quota_interval
            self._publish()

    def _refresh_quota(self) -> None:
        self._next_quota_at = time.monotonic() + self.quota_interval
        errors = []
        try:
            if not self.codex.is_running():
                self.codex.start()
            result = self.codex.read_rate_limits()
            self.state.quota = parse_rate_limits(result, int(time.time()))
            self._quota_healthy = True
        except Exception as exc:
            self._quota_healthy = False
            errors.append("quota: %s" % exc)
        try:
            if not self.codex.is_running():
                self.codex.start()
            result = self.codex.read_usage()
            self.state.usage = parse_usage(result, int(time.time()))
            self._usage_healthy = True
        except Exception as exc:
            self._usage_healthy = False
            errors.append("usage: %s" % exc)
        self._last_error = "; ".join(errors) if errors else None
        self._publish()

    def _drain_notifications(self) -> None:
        should_refresh = False
        while True:
            message = self.codex.next_notification()
            if message is None:
                break
            if message.get("method") == "account/rateLimits/updated":
                should_refresh = True
        if should_refresh:
            self._refresh_quota()

    def _receive_hook(self) -> None:
        assert self._socket is not None
        try:
            raw = self._socket.recv(4096)
            payload = json.loads(raw.decode("utf-8"))
        except (BlockingIOError, UnicodeDecodeError, json.JSONDecodeError):
            return
        if not isinstance(payload, dict):
            return
        event = payload.get("event")
        turn_id = payload.get("turnId")
        session_id = payload.get("sessionId")
        transcript_path = safe_codex_transcript_path(payload.get("transcriptPath"))
        if event not in ("start", "stop") or not isinstance(turn_id, str):
            return
        if not isinstance(session_id, str) or not session_id:
            session_id = turn_id
        if event == "stop":
            self._poll_task_usage(session_id)
        label = None
        is_side: Optional[bool] = None
        if event == "start":
            label, discovered_path, is_side = self._resolve_task_metadata(session_id)
            if transcript_path is None:
                transcript_path = discovered_path
            if transcript_path is not None:
                is_side = False
        self.state.handle_hook(
            event,
            turn_id,
            session_id=session_id,
            transcript_path=transcript_path,
            label=label,
            is_side=is_side,
        )
        if event == "start" and transcript_path is not None:
            self._task_readers[session_id] = TranscriptTokenReader(transcript_path)
            self._poll_task_usage(session_id)
            if label == "NO_NAME":
                self._pending_task_metadata.add(session_id)
        elif event == "start":
            self._pending_task_metadata.add(session_id)
        elif event == "stop":
            self._task_readers.pop(session_id, None)
            self._pending_task_metadata.discard(session_id)
        self._publish()

    def _poll_task_usage(self, only_session: Optional[str] = None) -> bool:
        changed = False
        session_ids = (
            (only_session,)
            if only_session is not None
            else tuple(self._task_readers.keys())
        )
        timestamp = int(time.time())
        for session_id in session_ids:
            reader = self._task_readers.get(session_id)
            if reader is None:
                continue
            task = self.state.task_for_session(session_id)
            if task is None:
                self._task_readers.pop(session_id, None)
                continue
            usage = reader.poll()
            if usage is not None:
                changed = self.state.update_task_usage(
                    session_id, usage, timestamp=timestamp
                ) or changed
            if task.turn_id in reader.take_terminal_turn_ids():
                self.state.handle_hook(
                    "stop",
                    task.turn_id,
                    session_id=session_id,
                    transcript_path=str(reader.path),
                    timestamp=timestamp,
                )
                self._task_readers.pop(session_id, None)
                self._pending_task_metadata.discard(session_id)
                changed = True
        return changed

    def _resolve_task_metadata(
        self, session_id: str
    ) -> Tuple[str, Optional[str], bool]:
        thread_name: object = None
        transcript_path: Optional[str] = None
        is_side = False
        try:
            result = self.codex.read_thread(session_id)
            thread = result.get("thread")
            if isinstance(thread, dict):
                thread_name = thread.get("name")
                transcript_path = safe_codex_transcript_path(thread.get("path"))
        except Exception as exc:
            is_side = "thread not loaded:" in str(exc)
        return (
            "SIDE" if is_side else thread_label(thread_name),
            transcript_path,
            is_side,
        )

    def _refresh_task_metadata(self) -> bool:
        changed = False
        for session_id in tuple(self._pending_task_metadata):
            task = self.state.task_for_session(session_id)
            if task is None or task.activity.value != "W":
                self._pending_task_metadata.discard(session_id)
                continue
            label, transcript_path, is_side = self._resolve_task_metadata(session_id)
            if label != "NO_NAME" and label != task.label:
                task.label = label
                changed = True
            if task.is_side != is_side:
                task.is_side = is_side
                changed = True
            if transcript_path is not None and session_id not in self._task_readers:
                task.transcript_path = transcript_path
                self._task_readers[session_id] = TranscriptTokenReader(transcript_path)
                changed = self._poll_task_usage(session_id) or changed
            if label != "NO_NAME" and session_id in self._task_readers:
                self._pending_task_metadata.discard(session_id)
        return changed

    def _check_usb_transition(self) -> None:
        available = self.sink.usb_available()
        if self._last_usb_available is None:
            self._last_usb_available = available
            return
        if available == self._last_usb_available:
            return
        self._last_usb_available = available
        self._publish()

    def _publish(self) -> None:
        health_flags = (1 if self._quota_healthy else 0) | (
            2 if self._usage_healthy else 0
        )
        commands = [encode_cli_command(self.state, health_flags)]
        if self.state.usage is not None:
            commands.append(encode_usage_command(self.state.usage))
        commands.extend(encode_task_commands(self.state))
        delivery: Optional[TransportDelivery] = None
        for command in commands:
            try:
                delivery = self.sink.send(command)
                if self._last_error and self._last_error.startswith("transport:"):
                    self._last_error = None
            except OSError as exc:
                self._last_error = "transport: %s" % exc
                break
        self._write_state(delivery)

    def _write_state(self, delivery: Optional[TransportDelivery]) -> None:
        quota = self.state.quota
        window = quota.headline_window if quota is not None else None
        data: Dict[str, Any] = {
            "status": self.state.activity.name.lower(),
            "activeThreads": len(self.state.active_turns),
            "transport": delivery.mode if delivery is not None else None,
            "usbPort": (
                delivery.endpoint
                if delivery is not None and delivery.mode == "usb"
                else None
            ),
            "bleDevice": (
                delivery.endpoint
                if delivery is not None and delivery.mode == "ble"
                else None
            ),
            "error": self._last_error,
            "stateChangedAt": self.state.state_changed_at,
            "lastCompletedAt": self.state.last_completed_at,
            "completionSequence": self.state.completion_sequence,
            "health": {
                "quota": self._quota_healthy,
                "usage": self._usage_healthy,
            },
            "quota": None,
            "usage": None,
            "tasks": [],
        }
        if quota is not None and window is not None:
            data["quota"] = {
                "planType": quota.plan_type,
                "remainingPercent": window.remaining_percent,
                "windowDurationMins": window.duration_minutes,
                "resetsAt": window.resets_at,
                "resetCreditsAvailable": quota.reset_credits_available,
                "fetchedAt": quota.fetched_at,
            }
        usage = self.state.usage
        if usage is not None:
            data["usage"] = {
                "lifetimeTokens": usage.lifetime_tokens,
                "peakDailyTokens": usage.peak_daily_tokens,
                "longestRunningTurnSec": usage.longest_running_turn_sec,
                "currentStreakDays": usage.current_streak_days,
                "longestStreakDays": usage.longest_streak_days,
                "fetchedAt": usage.fetched_at,
                "dailyBucketCount": len(usage.daily),
                "latestBucketDate": (
                    usage.daily[-1].start_date.isoformat() if usage.daily else None
                ),
            }
        tasks = []
        for task in self.state.recent_tasks():
            token_usage = task.token_usage
            tasks.append(
                {
                    "number": task.number,
                    "label": task.label,
                    "sessionId": task.session_id,
                    "turnId": task.turn_id,
                    "transcriptPath": task.transcript_path,
                    "status": task.activity.name.lower(),
                    "startedAt": task.started_at,
                    "updatedAt": task.updated_at,
                    "isSide": task.is_side,
                    "tokens": (
                        {
                            "total": token_usage.total_tokens,
                            "last": token_usage.last_tokens,
                            "lastInput": token_usage.last_input_tokens,
                            "input": token_usage.input_tokens,
                            "cachedInput": token_usage.cached_input_tokens,
                            "cacheWriteInput": token_usage.cache_write_input_tokens,
                            "output": token_usage.output_tokens,
                            "reasoningOutput": token_usage.reasoning_output_tokens,
                            "modelContextWindow": token_usage.model_context_window,
                        }
                        if token_usage is not None
                        else None
                    ),
                }
            )
        data["tasks"] = tasks
        temporary = self.state_path + ".tmp"
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.chmod(temporary, 0o600)
        os.replace(temporary, self.state_path)


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--codex-bin", required=True)
    parser.add_argument(
        "--runtime-dir",
        default=os.path.expanduser("~/Library/Application Support/CodexFlipperMonitor"),
    )
    parser.add_argument("--quota-interval", type=float, default=60.0)
    parser.add_argument("--ble-helper")
    parser.add_argument("--ble-name")
    args = parser.parse_args(argv)
    if bool(args.ble_helper) != bool(args.ble_name):
        parser.error("--ble-helper and --ble-name must be provided together")
    MonitorService(
        args.codex_bin,
        args.runtime_dir,
        args.quota_interval,
        ble_helper=args.ble_helper,
        ble_name=args.ble_name,
    ).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
