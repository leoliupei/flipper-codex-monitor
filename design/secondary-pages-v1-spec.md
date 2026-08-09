# Secondary pages pixel contract v1

- Every page is native `128x64`, monochrome, and rendered without antialiasing.
- Every secondary page begins with the approved back/level arrow.
- Header order is page title, active transport, and live Flipper battery.
- Home directional navigation:
  - Left: quota.
  - Down: usage.
  - Right: tasks.
  - Up: link.
- Secondary-page Left/Right cycles through Quota, Usage, Tasks, and Link.
- Back returns to Home; Back on Home exits the application.
- Pages never return to Home automatically.
- Usage Up/Down cycles Daily, Weekly, and Total modes.
- Usage Daily defaults to 14 days; OK cycles 7, 14, and 30 days.
- Link shows USB and Bluetooth in separate columns with the label above the
  state, preventing long status strings from colliding.
- The Link footer shows how long the currently active USB or Bluetooth
  transport has remained linked. It resets whenever the active transport
  changes or disconnects.
- The FAP must use live fields and the same deterministic 3x5/5x7 glyphs.
- No prompt text, assistant output, paths, project names, account identifiers, or
  transcript locations may cross the monitor protocol.
