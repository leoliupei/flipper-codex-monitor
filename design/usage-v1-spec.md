# Usage pixel draft v1

- Native canvas: `128x64`, monochrome, no antialiasing.
- Scope: design artifact only. The FAP and installed application are unchanged.
- Data source: a live `account/usage/read` snapshot captured on 2026-08-08.
- Range: the latest 14 available daily buckets, 2026-07-25 through 2026-08-07.
- Header begins with a small back/level arrow, identifying this as a secondary page and
  reinforcing that Back returns to the homepage.
- The remaining header hierarchy is unchanged: page title, active transport, Flipper battery.
- Summary uses the visible range, not the lifetime account maximum:
  - `RANGE PEAK 916 MILLION`: highest daily value in the visible 14-day range.
  - `LATEST 243 MILLION`: latest available bucket, 2026-08-07.
- `MILLION` is written in full instead of using an unexplained `M` abbreviation.
- The chart uses one exact point per daily bucket and a linear zero-based scale.
- The visible range peak uses an outlined 3x3 marker; the latest day uses a filled 3x3 marker.
- Missing dates will be inserted as zero before rendering; the line must not skip them.
- Footer shows the first date, full `14 DAYS` range, and latest date.
- The page remains visible until the user navigates away or presses Back; there is no automatic return to the homepage.
