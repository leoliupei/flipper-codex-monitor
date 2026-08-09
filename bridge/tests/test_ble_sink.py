import io
import unittest
from unittest import mock

from codex_flipper_monitor.ble_sink import FlipperBleSink


class BleSinkReconnectTests(unittest.TestCase):
    def test_scan_timeout_keeps_helper_alive_for_late_fap_reopen(self) -> None:
        sink = FlipperBleSink(
            "/unused/helper", "TEST1", timeout=1.0, connect_timeout=1.0
        )
        writer = io.StringIO()
        sink._writer_handle = writer
        try:
            with mock.patch.object(sink, "_ensure_process"):
                with self.assertRaisesRegex(OSError, "timed out"):
                    sink.send("codexmon v=1\r")
            self.assertIs(sink._writer_handle, writer)
            self.assertIn(1, sink._expired_ids)
        finally:
            sink._writer_handle = None


if __name__ == "__main__":
    unittest.main()
