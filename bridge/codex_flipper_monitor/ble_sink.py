import json
import os
import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional, Set


class FlipperBleSink:
    """Persistent JSONL client for the native macOS CoreBluetooth helper."""

    def __init__(
        self,
        helper_path: str,
        device_name: str,
        timeout: float = 8.0,
        connect_timeout: float = 45.0,
    ) -> None:
        self.helper_path = helper_path
        self.device_name = device_name
        self.timeout = max(1.0, float(timeout))
        self.connect_timeout = max(self.timeout, float(connect_timeout))
        self._process: Optional[subprocess.Popen] = None
        self._server_socket: Optional[socket.socket] = None
        self._connection_socket: Optional[socket.socket] = None
        self._reader_handle: Optional[Any] = None
        self._writer_handle: Optional[Any] = None
        self._socket_path: Optional[str] = None
        self._reader: Optional[threading.Thread] = None
        self._condition = threading.Condition()
        self._responses: Dict[int, Dict[str, Any]] = {}
        self._expired_ids: Set[int] = set()
        self._reader_error: Optional[str] = None
        self._next_id = 1
        self._send_lock = threading.Lock()
        self._used_connect_timeout = False

    def send(self, payload: str) -> str:
        payload.encode("ascii", "strict")
        with self._send_lock:
            self._ensure_process()
            writer = self._writer_handle
            if writer is None:
                raise OSError("BLE helper is unavailable")
            request_id = self._next_id
            self._next_id += 1
            request = json.dumps(
                {"id": request_id, "payload": payload}, separators=(",", ":")
            )
            try:
                writer.write(request + "\n")
                writer.flush()
            except (BrokenPipeError, OSError) as exc:
                self.close()
                raise OSError("BLE helper input failed: %s" % exc)

            wait_timeout = (
                self.timeout if self._used_connect_timeout else self.connect_timeout
            )
            self._used_connect_timeout = True
            deadline = time.monotonic() + wait_timeout
            failure: Optional[str] = None
            response: Optional[Dict[str, Any]] = None
            with self._condition:
                while request_id not in self._responses:
                    if self._reader_error:
                        failure = self._reader_error
                        break
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        failure = "BLE connection or acknowledgement timed out"
                        self._expired_ids.add(request_id)
                        break
                    self._condition.wait(timeout=remaining)
                if request_id in self._responses:
                    response = self._responses.pop(request_id)
            if failure is not None:
                if failure != "BLE connection or acknowledgement timed out":
                    self.close()
                raise OSError(failure)
            if response is None:
                raise OSError("BLE helper returned no response")
            if response.get("status") != "ok":
                raise OSError(str(response.get("error") or "BLE update failed"))
            return self.device_name

    def close(self) -> None:
        process = self._process
        reader = self._reader
        self._process = None
        self._reader = None
        writer = self._writer_handle
        reader_handle = self._reader_handle
        connection = self._connection_socket
        server = self._server_socket
        socket_path = self._socket_path
        self._writer_handle = None
        self._reader_handle = None
        self._connection_socket = None
        self._server_socket = None
        self._socket_path = None
        self._used_connect_timeout = False
        if connection is not None:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        for handle in (writer, reader_handle):
            if handle is not None:
                try:
                    handle.close()
                except OSError:
                    pass
        if connection is not None:
            try:
                connection.close()
            except OSError:
                pass
        if server is not None:
            try:
                server.close()
            except OSError:
                pass
        if socket_path is not None:
            try:
                os.unlink(socket_path)
            except FileNotFoundError:
                pass
        if process is not None:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
        if reader and reader.is_alive() and reader is not threading.current_thread():
            reader.join(timeout=1)
        with self._condition:
            self._condition.notify_all()

    def _ensure_process(self) -> None:
        if self._writer_handle is not None and self._reader_error is None:
            return
        if not os.path.isfile(self.helper_path) or not os.access(self.helper_path, os.X_OK):
            raise OSError("BLE helper is not executable: %s" % self.helper_path)
        self.close()
        self._responses = {}
        self._expired_ids = set()
        self._reader_error = None
        bundle = self._bundle_path()
        if bundle is not None:
            self._launch_bundle(bundle)
        else:
            self._process = subprocess.Popen(
                [self.helper_path, "--name", self.device_name],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
            self._writer_handle = self._process.stdin
            self._reader_handle = self._process.stdout
        self._reader = threading.Thread(
            target=self._read_stdout,
            name="codex-flipper-ble-helper",
            daemon=True,
        )
        self._reader.start()

    def _bundle_path(self) -> Optional[str]:
        path = Path(self.helper_path)
        try:
            bundle = path.parents[2]
        except IndexError:
            return None
        if bundle.suffix != ".app":
            return None
        return str(bundle)

    def _launch_bundle(self, bundle: str) -> None:
        socket_path = "/tmp/codex-flipper-ble-%d-%d.sock" % (os.getuid(), os.getpid())
        try:
            os.unlink(socket_path)
        except FileNotFoundError:
            pass
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server_socket = server
        self._socket_path = socket_path
        try:
            server.bind(socket_path)
            os.chmod(socket_path, 0o600)
            server.listen(1)
            server.settimeout(min(10.0, self.timeout))
            subprocess.run(
                [
                    "/usr/bin/open",
                    "-g",
                    "-j",
                    "-n",
                    bundle,
                    "--args",
                    "--name",
                    self.device_name,
                    "--socket",
                    socket_path,
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
            connection, _ = server.accept()
        except (OSError, subprocess.CalledProcessError) as exc:
            self.close()
            raise OSError("BLE helper app launch failed: %s" % exc)
        connection.settimeout(None)
        self._connection_socket = connection
        self._reader_handle = connection.makefile("r", encoding="utf-8")
        self._writer_handle = connection.makefile(
            "w", encoding="utf-8", buffering=1
        )

    def _read_stdout(self) -> None:
        reader = self._reader_handle
        if reader is None:
            return
        try:
            for line in reader:
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(message, dict):
                    continue
                request_id = message.get("id")
                if isinstance(request_id, int):
                    with self._condition:
                        if request_id in self._expired_ids:
                            self._expired_ids.remove(request_id)
                        else:
                            self._responses[request_id] = message
                        self._condition.notify_all()
        except OSError as exc:
            error = "BLE helper output failed: %s" % exc
        else:
            process = self._process
            code = process.poll() if process is not None else None
            error = (
                "BLE helper disconnected"
                if process is None
                else ("BLE helper exited" if code is None else "BLE helper exited: %s" % code)
            )
        with self._condition:
            self._reader_error = error
            self._condition.notify_all()
