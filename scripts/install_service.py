#!/usr/bin/env python3
import argparse
import hashlib
import os
import plistlib
import shutil
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional

try:
    from scripts.constants import (
        APPLICATION_SUPPORT_NAME,
        LEGACY_SERVICE_LABELS,
        SERVICE_LABEL,
    )
except ModuleNotFoundError:  # Direct `python3 scripts/install_service.py` execution.
    from constants import (  # type: ignore
        APPLICATION_SUPPORT_NAME,
        LEGACY_SERVICE_LABELS,
        SERVICE_LABEL,
    )


def run_launchctl(*args: str, check: bool = True) -> None:
    subprocess.run(["/bin/launchctl", *args], check=check)


def bootstrap(domain: str, plist_path: Path) -> Optional[str]:
    error = ""
    for _attempt in range(10):
        result = subprocess.run(
            ["/bin/launchctl", "bootstrap", domain, str(plist_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if result.returncode == 0:
            return None
        error = result.stderr.strip()
        time.sleep(0.2)
    return error or "unknown launchctl error"


def build_plist(
    codex_bin: Path,
    install_root: Path,
    app_dir: Path,
    ble_name: str,
) -> Dict[str, object]:
    return {
        "Label": SERVICE_LABEL,
        "ProgramArguments": [
            "/usr/bin/python3",
            "-m",
            "codex_flipper_monitor.service",
            "--codex-bin",
            str(codex_bin),
            "--runtime-dir",
            str(install_root),
            "--ble-helper",
            str(
                app_dir
                / "CodexFlipperBLE.app"
                / "Contents"
                / "MacOS"
                / "codex-flipper-ble"
            ),
            "--ble-name",
            ble_name,
        ],
        "EnvironmentVariables": {
            "PYTHONPATH": str(app_dir),
            "PATH": "%s:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
            % codex_bin.parent,
        },
        "RunAtLoad": True,
        "KeepAlive": True,
        "ProcessType": "Background",
        "ThrottleInterval": 5,
        "StandardOutPath": str(install_root / "service.stdout.log"),
        "StandardErrorPath": str(install_root / "service.stderr.log"),
    }


def print_dry_run(
    codex_bin: Path,
    ble_name: str,
    install_root: Path,
    plist_path: Path,
) -> None:
    print("Dry run only; no files or services were changed.")
    print("Service label: %s" % SERVICE_LABEL)
    print("Codex executable: %s" % codex_bin)
    print("Flipper Bluetooth name: %s" % ble_name)
    print("Application support: %s" % install_root)
    print("LaunchAgent: %s" % plist_path)
    print("The BLE helper would be compiled and ad-hoc signed locally.")
    if LEGACY_SERVICE_LABELS:
        print("Legacy service labels migrated after success: %s" % ", ".join(LEGACY_SERVICE_LABELS))


def main() -> int:
    parser = argparse.ArgumentParser(description="Install the local USB/BLE monitor service")
    parser.add_argument("--codex-bin", required=True)
    parser.add_argument("--ble-name", required=True)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate inputs and print planned changes without writing anything",
    )
    args = parser.parse_args()

    # Keep the user-facing launcher path instead of resolving its npm symlink.
    # Its sibling `node` binary must also be on PATH when launchd invokes it.
    codex_bin = Path(args.codex_bin).expanduser().absolute()
    if not codex_bin.is_file() or not os.access(str(codex_bin), os.X_OK):
        raise SystemExit("codex executable not found: %s" % codex_bin)
    if not args.ble_name.strip() or len(args.ble_name.encode("utf-8")) > 64:
        raise SystemExit("ble-name must contain between 1 and 64 UTF-8 bytes")

    project_root = Path(__file__).resolve().parents[1]
    source_package = project_root / "bridge" / "codex_flipper_monitor"
    source_ble = project_root / "bridge" / "macos_ble_helper"
    if not source_package.is_dir():
        raise SystemExit("bridge package not found: %s" % source_package)
    if not (source_ble / "main.swift").is_file():
        raise SystemExit("BLE helper source not found: %s" % source_ble)

    home = Path.home()
    install_root = home / "Library" / "Application Support" / APPLICATION_SUPPORT_NAME
    app_dir = install_root / "app"
    staging = install_root / "app.new"
    previous = install_root / "app.previous"
    launch_agents = home / "Library" / "LaunchAgents"
    plist_path = launch_agents / (SERVICE_LABEL + ".plist")
    legacy_plists = [launch_agents / (label + ".plist") for label in LEGACY_SERVICE_LABELS]

    if args.dry_run:
        print_dry_run(codex_bin, args.ble_name, install_root, plist_path)
        return 0

    helper_fingerprint = hashlib.sha256()
    helper_fingerprint.update((source_ble / "main.swift").read_bytes())
    helper_fingerprint.update((source_ble / "Info.plist").read_bytes())
    helper_source_hash = helper_fingerprint.hexdigest()

    install_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(install_root, 0o700)
    if staging.exists():
        shutil.rmtree(staging)
    shutil.copytree(source_package, staging / "codex_flipper_monitor")

    ble_bundle = staging / "CodexFlipperBLE.app"
    installed_ble_bundle = app_dir / "CodexFlipperBLE.app"
    installed_fingerprint = app_dir / "ble-helper-source.sha256"
    installed_info = installed_ble_bundle / "Contents" / "Info.plist"
    installed_executable = installed_ble_bundle / "Contents" / "MacOS" / "codex-flipper-ble"
    preserve_installed_helper = False
    if installed_executable.is_file() and installed_info.is_file():
        if installed_fingerprint.is_file():
            preserve_installed_helper = (
                installed_fingerprint.read_text(encoding="ascii").strip()
                == helper_source_hash
            )
        else:
            preserve_installed_helper = (
                installed_info.read_bytes() == (source_ble / "Info.plist").read_bytes()
            )

    if preserve_installed_helper:
        shutil.copytree(installed_ble_bundle, ble_bundle)
        (staging / "ble-helper-source.sha256").write_text(
            helper_source_hash + "\n", encoding="ascii"
        )
        print("Preserved existing BLE helper signature")
    else:
        ble_contents = ble_bundle / "Contents"
        ble_macos = ble_contents / "MacOS"
        ble_macos.mkdir(mode=0o755, parents=True)
        shutil.copy2(source_ble / "Info.plist", ble_contents / "Info.plist")
        ble_executable = ble_macos / "codex-flipper-ble"
        subprocess.run(
            [
                "/usr/bin/xcrun",
                "swiftc",
                "-swift-version",
                "5",
                "-O",
                "-framework",
                "Foundation",
                "-framework",
                "CoreBluetooth",
                str(source_ble / "main.swift"),
                "-o",
                str(ble_executable),
            ],
            check=True,
        )
        (staging / "ble-helper-source.sha256").write_text(
            helper_source_hash + "\n", encoding="ascii"
        )
        subprocess.run(
            ["/usr/bin/codesign", "--force", "--sign", "-", str(ble_bundle)],
            check=True,
        )

    launch_agents.mkdir(mode=0o755, parents=True, exist_ok=True)
    plist_data = build_plist(codex_bin, install_root, app_dir, args.ble_name)
    previous_plist = plist_path.read_bytes() if plist_path.is_file() else None
    domain = "gui/%d" % os.getuid()
    stopped_plists: List[Path] = []

    for label, candidate in [(SERVICE_LABEL, plist_path)] + list(
        zip(LEGACY_SERVICE_LABELS, legacy_plists)
    ):
        run_launchctl("bootout", "%s/%s" % (domain, label), check=False)
        if candidate.is_file():
            stopped_plists.append(candidate)

    if previous.exists():
        shutil.rmtree(previous)
    if app_dir.exists():
        app_dir.rename(previous)
    staging.rename(app_dir)

    temporary = plist_path.with_suffix(".plist.new")
    with temporary.open("wb") as handle:
        plistlib.dump(plist_data, handle, sort_keys=True)
    os.chmod(temporary, 0o644)
    os.replace(temporary, plist_path)

    bootstrap_error = bootstrap(domain, plist_path)
    if bootstrap_error is not None:
        run_launchctl("bootout", "%s/%s" % (domain, SERVICE_LABEL), check=False)
        if app_dir.exists():
            shutil.rmtree(app_dir)
        if previous.exists():
            previous.rename(app_dir)
        if previous_plist is None:
            plist_path.unlink(missing_ok=True)
        else:
            plist_path.write_bytes(previous_plist)
            os.chmod(plist_path, 0o644)
        for candidate in stopped_plists:
            if candidate.is_file():
                bootstrap(domain, candidate)
        raise RuntimeError("launchctl bootstrap failed; previous service restored: %s" % bootstrap_error)

    if previous.exists():
        shutil.rmtree(previous)
    for legacy_plist in legacy_plists:
        legacy_plist.unlink(missing_ok=True)
    print("Installed and started %s" % SERVICE_LABEL)
    print("Runtime: %s" % install_root)
    if stopped_plists:
        print("Migrated legacy or previous LaunchAgent configuration")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
