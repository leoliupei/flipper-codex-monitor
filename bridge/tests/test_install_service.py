import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest import mock

from scripts.constants import SERVICE_LABEL
from scripts.install_service import bootstrap, build_plist


class InstallServiceTests(unittest.TestCase):
    def test_plist_uses_public_service_identity_and_private_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "CodexFlipperMonitor"
            app = root / "app"
            plist = build_plist(Path("/opt/codex"), root, app, "TEST1")

        self.assertEqual(plist["Label"], SERVICE_LABEL)
        self.assertEqual(
            SERVICE_LABEL, "io.github.leoliupei.flipper-codex-monitor"
        )
        arguments = plist["ProgramArguments"]
        self.assertIn("/opt/codex", arguments)
        self.assertIn("TEST1", arguments)
        self.assertEqual(plist["EnvironmentVariables"]["PYTHONPATH"], str(app))

    @mock.patch("scripts.install_service.time.sleep")
    @mock.patch("scripts.install_service.subprocess.run")
    def test_bootstrap_waits_for_a_slow_launchd_unload(
        self, run: mock.Mock, sleep: mock.Mock
    ) -> None:
        failures = [
            CompletedProcess([], 5, stdout="", stderr="Input/output error")
            for _attempt in range(12)
        ]
        run.side_effect = failures + [CompletedProcess([], 0, stdout="", stderr="")]

        self.assertIsNone(bootstrap("gui/501", Path("/tmp/service.plist")))
        self.assertEqual(run.call_count, 13)
        self.assertEqual(sleep.call_count, 12)


if __name__ == "__main__":
    unittest.main()
