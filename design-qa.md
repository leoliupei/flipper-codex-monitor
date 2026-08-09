# Flipper homepage v3 design QA

- Source visual truth: `design/homepage-v3-128x64.png`
- Implementation screenshot: `/var/folders/dv/qjt1nb554lsfzv8z7_1513l00000gn/T/codex-clipboard-6a804106-cfae-4da0-bc1f-49a6c96f0e70.png`
- Combined comparison: `design/homepage-v3-reference-vs-actual.png`
- Source viewport: 128x64 monochrome pixels, shown at exact 8x nearest-neighbor scale.
- Implementation evidence: 1720x1024 camera photograph; framebuffer region normalized from crop `(329,246)-(1313,758)` to 1024x512.
- State difference: source shows `4%`, `WORKING`, `1 TASK`, and 82% battery; implementation shows live `100%`, `IDLE`, `0 TASKS`, and 100% battery. These are expected data/state differences.

## Full-view comparison

- Header, horizontal dividers, vertical split, labels, quota value, activity indicator, footer, and battery occupy the intended positions.
- The live maximum quota value `100%` fits without clipping or touching the center divider.
- The day countdown and reset count are readable on the physical amber LCD.

## Focused fidelity surfaces

- Fonts and typography: the implementation uses the selected deterministic 3x5 and 5x7 bitmaps; glyph shapes and spacing match the source.
- Spacing and layout: no actionable drift is visible after normalizing the photographed framebuffer.
- Colors and tokens: the source is logical monochrome; the amber LCD background is expected hardware rendering.
- Image and asset fidelity: the selected homepage contains no external image assets or decorative logo.
- Copy and content: live-state substitutions are correct; compact labels match the approved rules.

## Findings

- No P0, P1, or P2 mismatch.
- P3: at 100%, the two-pixel-high progress fill reads as a thin stripe inside the frame. This matches the selected pixel source but could be made visually heavier in a future polish pass.
- P3: `IDLE` plus four empty squares and `0 TASKS` is slightly redundant. This is an unmocked state-design choice, not implementation drift.

## Comparison history

- Earlier implementation used native Flipper fonts and differed substantially from the conceptual mock.
- The v3 source replaced those fonts with deterministic bitmap glyphs and fixed coordinates.
- The photographed v0.5.0 implementation now matches those glyphs and coordinates.

final result: passed
