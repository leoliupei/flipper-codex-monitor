import tempfile
import unittest
from pathlib import Path

from scripts.constants import SERVICE_LABEL
from scripts.install_service import build_plist


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


if __name__ == "__main__":
    unittest.main()
