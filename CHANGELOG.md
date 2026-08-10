# Changelog

All notable changes are documented here. The project follows Semantic
Versioning while remaining pre-1.0.

## Unreleased

- Aligned Codex App Server client metadata with the bridge release version and
  added regression coverage on Python 3.9 and 3.12.
- Pinned the local Flipper SDK setup, documented first-run Hook reload and
  troubleshooting, and disabled privacy-bypassing blank issue forms.
- Added a metadata-free real-device photo and changed the license attribution
  to the maintainer's GitHub username.

## 0.9.18 - 2026-08-10

- Added the two-second `DONE` check-mark animation.
- Added persistent recent-task history, task details, live token breakdowns,
  daily usage charts, link diagnostics, and per-task completion notifications.
- Added Bluetooth-first transport with acknowledged USB fallback.
- Added reproducible official-SDK FAP builds and native macOS Bluetooth helper
  compilation.
- Added MIT licensing, security and privacy documentation, installation dry
  runs, precise uninstallers, release metadata checks, and GitHub Actions.
- Isolated the optional design renderer on the patched Pillow 12.3.0 release;
  runtime and FAP builds do not install Pillow.
- Made same-label service reinstallation wait for slow launchd shutdowns and
  verified both legacy-label migration and idempotent reinstall on macOS.
- Migrated the public LaunchAgent identity to
  `io.github.leoliupei.flipper-codex-monitor` while retaining a one-time legacy
  migration path.
