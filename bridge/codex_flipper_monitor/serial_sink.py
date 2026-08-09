import glob
import os
import select
import termios
import time
from typing import Callable, List, Optional


class FlipperSerialSink:
    def __init__(
        self,
        pattern: str = "/dev/cu.usbmodemflip_*",
        finder: Optional[Callable[[str], List[str]]] = None,
        ack_timeout: float = 2.0,
    ) -> None:
        self.pattern = pattern
        self.finder = finder or glob.glob
        self.ack_timeout = max(0.05, float(ack_timeout))
        self.last_port: Optional[str] = None

    def available(self) -> bool:
        return bool(self.finder(self.pattern))

    def send(self, payload: str) -> str:
        ports = sorted(self.finder(self.pattern))
        if not ports:
            raise FileNotFoundError("Flipper USB serial port is not connected")
        port = ports[0]
        fd = os.open(port, os.O_RDWR | os.O_NOCTTY)
        try:
            attrs = termios.tcgetattr(fd)
            attrs[0] = 0
            attrs[1] = 0
            attrs[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
            attrs[3] = 0
            attrs[4] = termios.B230400
            attrs[5] = termios.B230400
            attrs[6][termios.VMIN] = 0
            attrs[6][termios.VTIME] = 5
            termios.tcsetattr(fd, termios.TCSANOW, attrs)
            termios.tcflush(fd, termios.TCIFLUSH)
            os.write(fd, payload.encode("ascii", "strict"))
            termios.tcdrain(fd)
            deadline = time.monotonic() + self.ack_timeout
            response = b""
            while time.monotonic() < deadline:
                readable, _, _ = select.select(
                    [fd], [], [], min(0.2, max(0.0, deadline - time.monotonic()))
                )
                if not readable:
                    continue
                chunk = os.read(fd, 4096)
                if not chunk:
                    continue
                response = (response + chunk)[-8192:]
                normalized = response.lower()
                if b"\r\nok\r\n" in normalized:
                    break
                if b"\r\nerr " in normalized or b"command not found" in normalized:
                    raise OSError("Flipper rejected monitor command")
            else:
                raise OSError("Codex Monitor app did not acknowledge USB update")
        finally:
            os.close(fd)
        self.last_port = port
        return port
