import os
import pty
import threading
import unittest

from codex_flipper_monitor.serial_sink import FlipperSerialSink


class SerialSinkTests(unittest.TestCase):
    def test_writes_ascii_payload_to_selected_serial_device(self) -> None:
        master, slave = pty.openpty()
        slave_path = os.ttyname(slave)
        received = []

        def emulate_flipper() -> None:
            received.append(os.read(master, 128))
            os.write(master, b"\r\nOK\r\n")

        reader = threading.Thread(target=emulate_flipper)
        reader.start()
        try:
            sink = FlipperSerialSink(finder=lambda _pattern: [slave_path])
            selected = sink.send("codexmon v=1 s=I\r")
            self.assertEqual(selected, slave_path)
            reader.join(timeout=1.0)
            self.assertFalse(reader.is_alive())
            self.assertEqual(received, [b"codexmon v=1 s=I\r"])
        finally:
            os.close(slave)
            os.close(master)

    def test_requires_monitor_acknowledgement(self) -> None:
        master, slave = pty.openpty()
        slave_path = os.ttyname(slave)

        def consume_without_ack() -> None:
            os.read(master, 128)

        reader = threading.Thread(target=consume_without_ack)
        reader.start()
        try:
            sink = FlipperSerialSink(
                finder=lambda _pattern: [slave_path], ack_timeout=0.05
            )
            with self.assertRaisesRegex(OSError, "did not acknowledge"):
                sink.send("codexmon v=1 s=I\r")
            reader.join(timeout=1.0)
            self.assertFalse(reader.is_alive())
        finally:
            os.close(slave)
            os.close(master)


if __name__ == "__main__":
    unittest.main()
