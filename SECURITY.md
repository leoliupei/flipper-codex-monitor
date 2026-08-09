# Security policy

## Supported versions

Security fixes are provided for the latest release. This project is still
pre-1.0, so users should review release notes before upgrading.

## Trust boundary

Flipper Codex Monitor is local-first software. The macOS bridge launches the
locally installed Codex App Server, reads aggregate quota and usage values, and
reads token-count and terminal-event metadata from Codex transcript files.
It does not send prompt text or assistant responses to the Flipper.

The private runtime directory is:

`~/Library/Application Support/CodexFlipperMonitor`

It can contain local session identifiers, turn identifiers, transcript paths,
task labels, quota data, and token counters. The installer creates the
directory with mode `0700`; state files and the local hook socket use mode
`0600`.

The compact USB or Bluetooth payload can contain quota values, aggregate usage,
short task labels, task state, token counters, timestamps, and battery or link
state. Bluetooth users should treat those values as data visible to the paired
local transport rather than as secret material.

The project has no telemetry service and does not require a project-operated
cloud backend.

## Reporting a vulnerability

Do not open a public issue for a vulnerability that could expose private Codex
data or execute commands on another user's Mac. Use GitHub's private
vulnerability reporting feature for this repository. Include the affected
version, reproduction steps, and the expected impact. Please allow a reasonable
window for validation and a coordinated fix before public disclosure.

## Installation review

The installer writes a per-user LaunchAgent, a private application-support
directory, and two optional Codex command hooks. Run each installer with
`--dry-run` first and review the exact paths before applying it. Root access is
not required.
