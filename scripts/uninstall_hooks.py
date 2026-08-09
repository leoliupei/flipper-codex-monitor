#!/usr/bin/env python3
import argparse
import json
import os
import shlex
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Tuple

try:
    from scripts.install_hooks import EVENTS, encoded_config, print_config_diff
except ModuleNotFoundError:  # Direct `python3 scripts/uninstall_hooks.py` execution.
    from install_hooks import EVENTS, encoded_config, print_config_diff  # type: ignore


def remove_hook_config(config: Dict[str, Any], command: str) -> Tuple[Dict[str, Any], bool]:
    hooks = config.get("hooks")
    if not isinstance(hooks, dict):
        return config, False

    changed = False
    for event in EVENTS:
        groups = hooks.get(event)
        if not isinstance(groups, list):
            continue
        kept_groups = []
        for group in groups:
            if not isinstance(group, dict):
                kept_groups.append(group)
                continue
            handlers = group.get("hooks")
            if not isinstance(handlers, list):
                kept_groups.append(group)
                continue
            kept_handlers = [
                handler
                for handler in handlers
                if not (
                    isinstance(handler, dict)
                    and handler.get("type") == "command"
                    and handler.get("command") == command
                )
            ]
            if len(kept_handlers) != len(handlers):
                changed = True
            if kept_handlers:
                updated = dict(group)
                updated["hooks"] = kept_handlers
                kept_groups.append(updated)
        if kept_groups:
            hooks[event] = kept_groups
        elif event in hooks:
            del hooks[event]
    if not hooks:
        config.pop("hooks", None)
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
    parser = argparse.ArgumentParser(description="Remove Codex Flipper command hooks")
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
    command = "/usr/bin/python3 %s" % shlex.quote(str(hook_script))
    if not hooks_file.is_file():
        print("Hooks file does not exist; no change")
        return 0

    with hooks_file.open("r", encoding="utf-8") as handle:
        config = json.load(handle)
    if not isinstance(config, dict):
        raise SystemExit("hooks.json must contain a JSON object")
    before = json.loads(json.dumps(config))
    updated, changed = remove_hook_config(config, command)
    if not changed:
        print("Codex Flipper hooks are not installed; no change")
        return 0

    if args.dry_run:
        print("Dry run only; no files were changed.")
        print_config_diff(before, updated, hooks_file)
        return 0

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = hooks_file.with_name(hooks_file.name + "." + timestamp + ".bak")
    shutil.copy2(hooks_file, backup)
    os.chmod(backup, 0o600)

    temporary = hooks_file.with_suffix(".json.new")
    with temporary.open("w", encoding="utf-8") as handle:
        handle.write(encoded_config(updated))
    os.chmod(temporary, 0o600)
    os.replace(temporary, hooks_file)
    print("Removed Hooks: %s" % hooks_file)
    print("Backup: %s" % backup)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
