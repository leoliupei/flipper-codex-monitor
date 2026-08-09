# Homepage pixel draft v3

- Native canvas: `128x64`, monochrome, no antialiasing.
- The quota panel starts with a continuous 180-degree pace meter instead of a
  text label. It compares quota used with elapsed time in the current weekly
  window: left means slower consumption, center means on pace, and right means
  faster consumption.
- The needle has exactly seven stable positions numbered `0` through `6`.
  Position `3` is vertical. Positions `0` and `6` stop one pixel inside the
  literal arc endpoints so the needle remains distinct from the outline.
- Deviation from elapsed quota pace maps to the seven positions at these
  boundaries: `<= -17`, `-16..-10`, `-9..-4`, `-3..3`, `4..9`, `10..16`, and
  `>= 17` percentage points.
- The meter uses the Flipper canvas circle rasterizer at radii 13 and 12, then
  clears the lower half. The two concentric outlines produce a continuous
  2-pixel semicircle without hand-authored line segments.
- The seven stable positions are mathematical needle endpoints only. They do
  not draw seven protruding tick marks into the arc, so the circular silhouette
  remains clean.
- The SDK line primitive draws the needle, and a radius-1 SDK disc forms its
  round pivot. The complete meter occupies approximately 27 by 14 pixels.
- The remaining percentage uses the native 5-by-7-pixel font at 1x scale. It
  is substantially smaller than the original 2x value and sits beneath the
  enlarged meter at `y=33`. The meter and percentage are shifted down together
  by two pixels while preserving their internal spacing.
- Activity count: singular `1 TASK`; plural values use `2 TASKS`, `3 TASKS`, and so on.
- Reset countdown uses two display modes:
  - More than 24 hours: `RESET IN N DAYS`, rounded up to the next whole day.
  - 24 hours or less: `RESET IN HH:MM`.
- The day-count draft uses `RESET IN 7 DAYS`, which occupies 59 pixels and fits through `x=60`.
- When only one day remains, the label uses singular `RESET IN 1 DAY`.
- Available reset count remains the compact full-word label `1 RESET`; plural values use `2 RESETS`.
- The status label moves to `y=13` and the task count to `y=44`, reserving a
  19-by-19-pixel animation area between them.
- The `WORKING` activity indicator is a classic Windows-style hourglass centered
  at `(96, 32)`. Its upright body is 13 pixels wide and 15 pixels high, with
  thick caps, stepped curved walls, a narrow waist, and distinct sand piles.
- The larger 19-by-19-pixel area is used only as clearance while the 13-by-15
  body passes through diagonal angles during its flip.
- A 28-phase cycle runs at 125 milliseconds per phase. For the first 2.5
  seconds, the upper sand pile drops through four visible levels while the
  lower pile grows and a falling grain alternates below the waist.
- Only after the upper chamber empties does the complete hourglass flip 180
  degrees through eight intermediate angles. The one-second flip places the
  accumulated sand back on top and starts the next 3.5-second cycle.
- The eight flip angles are pre-rendered as complete 19-by-19-pixel bitmaps.
  Caps are rasterized as solid thick shapes and the sand as a single connected
  mass, preventing cap narrowing and internal gaps at diagonal angles.
- `IDLE` shows the official 18-by-18-pixel ChatGPT macOS template icon from the
  installed application's `chatgptTemplate.png`, converted directly to 1-bit
  black and white. It is centered at `(87, 23)` without scaling or animation
  and does not activate the LED or backlight. `DONE` and `OFFLINE` do not show
  a busy indicator.
- `DONE` draws a two-pixel-thick check mark inside the same 18-by-18-pixel icon
  area. The short descending stroke uses five 125-millisecond frames and the
  long ascending stroke uses eleven frames, completing in exactly two seconds.
  The complete check remains static for the rest of the ten-second `DONE` hold.
