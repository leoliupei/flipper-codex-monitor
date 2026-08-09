#!/usr/bin/env python3
import plistlib
import re
from pathlib import Path


def extract(pattern: str, text: str, source: Path) -> str:
    match = re.search(pattern, text)
    if match is None:
        raise SystemExit("version not found in %s" % source)
    return match.group(1)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    version = (root / "VERSION").read_text(encoding="ascii").strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise SystemExit("VERSION must use x.y.z format")

    fam_path = root / "flipper" / "application.fam"
    fam_version = extract(
        r'fap_version="([^"]+)"', fam_path.read_text(encoding="utf-8"), fam_path
    )
    init_path = root / "bridge" / "codex_flipper_monitor" / "__init__.py"
    bridge_version = extract(
        r'__version__\s*=\s*"([^"]+)"',
        init_path.read_text(encoding="utf-8"),
        init_path,
    )
    plist_path = root / "bridge" / "macos_ble_helper" / "Info.plist"
    with plist_path.open("rb") as handle:
        helper_version = plistlib.load(handle)["CFBundleShortVersionString"]

    versions = {
        "VERSION": version,
        "FAP": fam_version,
        "bridge": bridge_version,
        "BLE helper": helper_version,
    }
    mismatched = {name: value for name, value in versions.items() if value != version}
    if mismatched:
        raise SystemExit("version mismatch: %r" % mismatched)
    print("Release versions aligned at %s" % version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
