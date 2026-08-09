# Contributing

Thanks for helping improve Flipper Codex Monitor.

## Before opening a pull request

1. Keep the project local-first and do not add telemetry.
2. Do not forward prompt text, assistant output, raw transcript contents, or
   account identifiers to the Flipper.
3. Keep payloads bounded and compatible with the documented USB and Bluetooth
   protocol.
4. Add or update tests for bridge and installer changes.
5. Update the pixel specification when a screen layout changes.

Run the checks from the repository root:

```sh
PYTHONPATH="$PWD:$PWD/bridge" python3 -m unittest discover -s bridge/tests -v
xcrun swiftc -swift-version 5 -O \
  -framework Foundation -framework CoreBluetooth \
  bridge/macos_ble_helper/main.swift -o /tmp/codex-flipper-ble
(cd flipper && ufbt)
```

Regenerating files under `design/` is optional and requires Python 3.10 or
newer with `python3 -m pip install -r requirements-design.txt`. Pillow is kept
out of the bridge and FAP build dependency set.

Contributions are accepted under the repository's MIT License. By submitting a
pull request, you confirm that you have the right to license your contribution
on those terms.
