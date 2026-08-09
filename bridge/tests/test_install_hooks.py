import unittest

from scripts.install_hooks import merge_hook_config
from scripts.uninstall_hooks import remove_hook_config


class InstallHooksTests(unittest.TestCase):
    def test_additive_and_idempotent_merge(self) -> None:
        existing = {
            "description": "keep me",
            "hooks": {
                "Stop": [
                    {
                        "hooks": [
                            {"type": "command", "command": "/usr/bin/existing"}
                        ]
                    }
                ]
            },
        }
        merged, changed = merge_hook_config(existing, "/usr/bin/monitor")
        self.assertTrue(changed)
        self.assertEqual(merged["description"], "keep me")
        self.assertEqual(
            merged["hooks"]["Stop"][0]["hooks"][0]["command"],
            "/usr/bin/existing",
        )
        again, changed_again = merge_hook_config(merged, "/usr/bin/monitor")
        self.assertFalse(changed_again)
        self.assertIs(again, merged)

    def test_remove_only_monitor_hooks_and_keep_existing_handlers(self) -> None:
        command = "/usr/bin/monitor"
        config = {
            "description": "keep me",
            "hooks": {
                "Stop": [
                    {
                        "hooks": [
                            {"type": "command", "command": "/usr/bin/existing"},
                            {"type": "command", "command": command},
                        ]
                    }
                ],
                "UserPromptSubmit": [
                    {"hooks": [{"type": "command", "command": command}]}
                ],
            },
        }
        updated, changed = remove_hook_config(config, command)
        self.assertTrue(changed)
        self.assertEqual(updated["description"], "keep me")
        self.assertEqual(
            updated["hooks"]["Stop"][0]["hooks"],
            [{"type": "command", "command": "/usr/bin/existing"}],
        )
        self.assertNotIn("UserPromptSubmit", updated["hooks"])

        again, changed_again = remove_hook_config(updated, command)
        self.assertFalse(changed_again)
        self.assertIs(again, updated)


if __name__ == "__main__":
    unittest.main()
