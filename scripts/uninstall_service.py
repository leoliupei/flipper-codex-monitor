#!/usr/bin/env python3
import argparse
import os
import shutil
import subprocess
from pathlib import Path

try:
    from scripts.constants import (
        APPLICATION_SUPPORT_NAME,
        LEGACY_SERVICE_LABELS,
        SERVICE_LABEL,
    )
except ModuleNotFoundError:  # Direct `python3 scripts/uninstall_service.py` execution.
    from constants import (  # type: ignore
        APPLICATION_SUPPORT_NAME,
        LEGACY_SERVICE_LABELS,
        SERVICE_LABEL,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Uninstall the Codex Flipper monitor service")
    parser.add_argument(
        "--purge",
        action="store_true",
        help="also delete private state and logs from Application Support",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the exact removal plan without changing anything",
    )
    args = parser.parse_args()

    home = Path.home()
    launch_agents = home / "Library" / "LaunchAgents"
    install_root = home / "Library" / "Application Support" / APPLICATION_SUPPORT_NAME
    labels = (SERVICE_LABEL,) + LEGACY_SERVICE_LABELS
    plist_paths = [launch_agents / (label + ".plist") for label in labels]

    print("LaunchAgents:")
    for path in plist_paths:
        print("  %s" % path)
    if args.purge:
        print("Application Support purge: %s" % install_root)
    else:
        print("Installed app removal: %s" % (install_root / "app"))
        print("Private state and logs will be preserved in %s" % install_root)

    if args.dry_run:
        print("Dry run only; no files or services were changed.")
        return 0

    domain = "gui/%d" % os.getuid()
    for label, plist_path in zip(labels, plist_paths):
        subprocess.run(
            ["/bin/launchctl", "bootout", "%s/%s" % (domain, label)],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        plist_path.unlink(missing_ok=True)

    if args.purge:
        if install_root.is_dir():
            shutil.rmtree(install_root)
    else:
        for name in ("app", "app.new", "app.previous"):
            target = install_root / name
            if target.is_dir():
                shutil.rmtree(target)
    print("Service uninstalled")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
