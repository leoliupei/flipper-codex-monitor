from dataclasses import dataclass
from typing import Optional

from .ble_sink import FlipperBleSink
from .serial_sink import FlipperSerialSink


@dataclass(frozen=True)
class TransportDelivery:
    mode: str
    endpoint: str


class DualTransportSink:
    """Prefer BLE and use USB only when BLE delivery fails."""

    def __init__(
        self,
        usb: Optional[FlipperSerialSink] = None,
        ble: Optional[FlipperBleSink] = None,
    ) -> None:
        self.usb = usb or FlipperSerialSink()
        self.ble = ble

    def usb_available(self) -> bool:
        return self.usb.available()

    def send(self, payload: str) -> TransportDelivery:
        if self.ble is not None:
            try:
                device = self.ble.send(payload)
            except OSError as ble_error:
                try:
                    port = self.usb.send(payload)
                except OSError as usb_error:
                    raise OSError(
                        "BLE failed: %s; USB fallback failed: %s"
                        % (ble_error, usb_error)
                    )
                return TransportDelivery("usb", port)
            return TransportDelivery("ble", device)
        port = self.usb.send(payload)
        return TransportDelivery("usb", port)

    def close(self) -> None:
        if self.ble is not None:
            self.ble.close()
