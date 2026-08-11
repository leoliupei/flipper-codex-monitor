#!/usr/bin/env python3
import argparse
import difflib
import json
import os
import shlex
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Tuple


EVENTS = ("UserPromptSubmit", "Stop", "SubagentStart", "SubagentStop")


def encoded_config(config: Dict[str, Any]) -> str:
    return json.dumps(config, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def print_config_diff(before: Dict[str, Any], after: Dict[str, Any], target: Path) -> None:
    diff = difflib.unified_diff(
        encoded_config(before).splitlines(keepends=True),
        encoded_config(after).splitlines(keepends=True),
        fromfile=str(target),
        tofile=str(target) + " (planned)",
    )
    print("".join(diff), end="")


def merge_hook_config(config: Dict[str, Any], command: str) -> Tuple[Dict[str, Any], bool]:
    hooks = config.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("top-level hooks must be an object")

    changed = False
    for event in EVENTS:
        groups = hooks.setdefault(event, [])
        if not isinstance(groups, list):
            raise ValueError("hooks.%s must be an array" % event)
        exists = False
        for group in groups:
            if not isinstance(group, dict):
                continue
            handlers = group.get("hooks")
            if not isinstance(handlers, list):
                continue
            if any(
                isinstance(handler, dict)
                and handler.get("type") == "command"
                and handler.get("command") == command
                for handler in handlers
            ):
                exists = True
                break
        if not exists:
            groups.append(
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": command,
                            "timeout": 3,
                        }
                    ]
                }
            )
            changed = True
    return config, changed


def main() -> int:
    home = Path.home()
    default_script = (
        home
        / "Library"
        / "Application Support"
        / "CodexFlipperMonitor"
        / "app"
        / "codex_flipper_monitor"
        / "hook.py"
    )
    parser = argparse.ArgumentParser(description="Add privacy-minimized Codex Hooks")
    parser.add_argument("--hooks-file", default=str(home / ".codex" / "hooks.json"))
    parser.add_argument("--hook-script", default=str(default_script))
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the exact hooks.json change without writing it",
    )
    args = parser.parse_args()

    hooks_file = Path(args.hooks_file).expanduser()
    hook_script = Path(args.hook_script).expanduser().resolve()
    if not hook_script.is_file():
        raise SystemExit("installed hook script not found: %s" % hook_script)
    command = "/usr/bin/python3 %s" % shlex.quote(str(hook_script))

    hooks_file.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if hooks_file.exists():
        with hooks_file.open("r", encoding="utf-8") as handle:
            config = json.load(handle)
        if not isinstance(config, dict):
            raise SystemExit("hooks.json must contain a JSON object")
    else:
        config = {}

    before = json.loads(json.dumps(config))
    merged, changed = merge_hook_config(config, command)
    if not changed:
        print("Hooks already installed; no change")
        return 0

    if args.dry_run:
        print("Dry run only; no files were changed.")
        print_config_diff(before, merged, hooks_file)
        return 0

    if hooks_file.exists():
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = hooks_file.with_name(hooks_file.name + "." + timestamp + ".bak")
        shutil.copy2(hooks_file, backup)
        os.chmod(backup, 0o600)
        print("Backup: %s" % backup)

    temporary = hooks_file.with_suffix(".json.new")
    with temporary.open("w", encoding="utf-8") as handle:
        handle.write(encoded_config(merged))
    os.chmod(temporary, 0o600)
    os.replace(temporary, hooks_file)
    print("Installed Hooks: %s" % hooks_file)
    print("Review and trust the new command hooks with /hooks before testing.")
    print("Then fully quit and reopen ChatGPT/Codex before starting a new test task.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
