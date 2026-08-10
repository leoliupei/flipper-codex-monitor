import json
import queue
import subprocess
import threading
import time
from typing import Any, Dict, Optional

from . import __version__


class CodexProtocolError(RuntimeError):
    pass


class CodexAppServer:
    """Minimal JSONL client for the local Codex App Server."""

    def __init__(self, codex_bin: str, request_timeout: float = 30.0) -> None:
        self.codex_bin = codex_bin
        self.request_timeout = request_timeout
        self._process: Optional[subprocess.Popen] = None
        self._reader: Optional[threading.Thread] = None
        self._responses: Dict[int, Dict[str, Any]] = {}
        self._notifications: "queue.Queue[Dict[str, Any]]" = queue.Queue()
        self._condition = threading.Condition()
        self._write_lock = threading.Lock()
        self._next_id = 1
        self._reader_error: Optional[str] = None

    def start(self) -> None:
        self.stop()
        with self._condition:
            self._responses = {}
            self._reader_error = None
        self._notifications = queue.Queue()
        self._next_id = 1
        self._process = subprocess.Popen(
            [self.codex_bin, "app-server", "--stdio"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        self._reader = threading.Thread(
            target=self._read_stdout,
            name="codex-flipper-app-server",
            daemon=True,
        )
        self._reader.start()
        self._rpc(
            "initialize",
            {
                "clientInfo": {
                    "name": "flipper-codex-monitor",
                    "title": "Flipper Codex Monitor",
                    "version": __version__,
                },
                "capabilities": {
                    "experimentalApi": True,
                    "optOutNotificationMethods": [
                        "thread/started",
                        "thread/status/changed",
                    ],
                },
            },
        )
        self._send({"method": "initialized"})

    def stop(self) -> None:
        process = self._process
        reader = self._reader
        self._process = None
        self._reader = None
        if process is None:
            return
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        if reader and reader.is_alive() and reader is not threading.current_thread():
            reader.join(timeout=1)
        with self._condition:
            self._condition.notify_all()

    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def read_rate_limits(self) -> Dict[str, Any]:
        return self._rpc("account/rateLimits/read", None)

    def read_usage(self) -> Dict[str, Any]:
        return self._rpc("account/usage/read", None)

    def read_thread(self, thread_id: str) -> Dict[str, Any]:
        return self._rpc(
            "thread/read", {"threadId": thread_id, "includeTurns": False}
        )

    def next_notification(self) -> Optional[Dict[str, Any]]:
        try:
            return self._notifications.get_nowait()
        except queue.Empty:
            return None

    def _rpc(self, method: str, params: Any) -> Dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        self._send({"id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + self.request_timeout
        with self._condition:
            while request_id not in self._responses:
                if self._reader_error:
                    raise CodexProtocolError(self._reader_error)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Codex App Server timed out for %s" % method)
                self._condition.wait(timeout=remaining)
            message = self._responses.pop(request_id)
        if "error" in message:
            raise CodexProtocolError(
                "%s failed: %s"
                % (method, json.dumps(message["error"], ensure_ascii=False))
            )
        result = message.get("result")
        if not isinstance(result, dict):
            raise CodexProtocolError("%s returned an invalid result" % method)
        return result

    def _send(self, message: Dict[str, Any]) -> None:
        process = self._process
        if process is None or process.poll() is not None or process.stdin is None:
            raise CodexProtocolError("Codex App Server is not running")
        line = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
        with self._write_lock:
            process.stdin.write(line + "\n")
            process.stdin.flush()

    def _read_stdout(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        try:
            for line in process.stdout:
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(message, dict):
                    continue
                request_id = message.get("id")
                if isinstance(request_id, int):
                    with self._condition:
                        self._responses[request_id] = message
                        self._condition.notify_all()
                elif "method" in message:
                    self._notifications.put(message)
        except OSError as exc:
            self._reader_error = "Codex App Server output failed: %s" % exc
        finally:
            with self._condition:
                if not self._reader_error:
                    code = process.poll()
                    self._reader_error = (
                        "Codex App Server closed its output"
                        if code is None
                        else "Codex App Server exited with status %s" % code
                    )
                self._condition.notify_all()
