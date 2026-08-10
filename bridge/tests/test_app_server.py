import unittest
from unittest import mock

from codex_flipper_monitor import __version__
from codex_flipper_monitor.app_server import CodexAppServer


class CodexAppServerTests(unittest.TestCase):
    def test_initialize_reports_bridge_version(self) -> None:
        server = CodexAppServer("/usr/bin/codex")
        with mock.patch("codex_flipper_monitor.app_server.subprocess.Popen"), mock.patch(
            "codex_flipper_monitor.app_server.threading.Thread"
        ):
            with mock.patch.object(server, "_rpc") as rpc, mock.patch.object(
                server, "_send"
            ):
                server.start()

        method, params = rpc.call_args.args
        self.assertEqual(method, "initialize")
        self.assertEqual(params["clientInfo"]["version"], __version__)


if __name__ == "__main__":
    unittest.main()
