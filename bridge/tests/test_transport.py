import unittest

from codex_flipper_monitor.transport import DualTransportSink, TransportDelivery


class FakeSink:
    def __init__(self, result=None, error=None, available=True) -> None:
        self.result = result
        self.error = error
        self.is_available = available
        self.payloads = []
        self.close_count = 0

    def available(self) -> bool:
        return self.is_available

    def send(self, payload):
        self.payloads.append(payload)
        if self.error is not None:
            raise self.error
        return self.result

    def close(self) -> None:
        self.close_count += 1


class DualTransportTests(unittest.TestCase):
    def test_reports_usb_presence_without_opening_the_port(self) -> None:
        usb = FakeSink(available=False)
        sink = DualTransportSink(usb=usb)
        self.assertFalse(sink.usb_available())

    def test_ble_is_preferred_even_when_usb_is_available(self) -> None:
        usb = FakeSink(result="/dev/cu.flipper")
        ble = FakeSink(result="TEST1")
        sink = DualTransportSink(usb=usb, ble=ble)
        self.assertEqual(
            sink.send("payload"), TransportDelivery("ble", "TEST1")
        )
        self.assertEqual(ble.payloads, ["payload"])
        self.assertEqual(usb.payloads, [])
        self.assertEqual(ble.close_count, 0)

    def test_usb_is_fallback_after_ble_failure(self) -> None:
        usb = FakeSink(result="/dev/cu.flipper")
        ble = FakeSink(error=OSError("ble bad"))
        sink = DualTransportSink(usb=usb, ble=ble)
        self.assertEqual(
            sink.send("payload"), TransportDelivery("usb", "/dev/cu.flipper")
        )
        self.assertEqual(ble.payloads, ["payload"])
        self.assertEqual(usb.payloads, ["payload"])
        self.assertEqual(ble.close_count, 0)

    def test_usb_is_used_when_ble_is_not_configured(self) -> None:
        usb = FakeSink(result="/dev/cu.flipper")
        sink = DualTransportSink(usb=usb)
        self.assertEqual(
            sink.send("payload"), TransportDelivery("usb", "/dev/cu.flipper")
        )

    def test_reports_both_failures(self) -> None:
        usb = FakeSink(error=OSError("usb bad"))
        ble = FakeSink(error=OSError("ble bad"))
        sink = DualTransportSink(usb=usb, ble=ble)
        with self.assertRaisesRegex(OSError, "BLE failed.*USB fallback failed"):
            sink.send("payload")


if __name__ == "__main__":
    unittest.main()
