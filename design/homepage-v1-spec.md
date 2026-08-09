# Homepage pixel draft v1

- Native canvas: `128x64`, monochrome, no antialiasing.
- Preview: exact `8x` nearest-neighbor enlargement.
- Header divider: `y=11`.
- Main vertical divider: `x=63`, from `y=12` through `y=50`.
- Bottom divider: `y=50`.
- Large quota: `4%`, centered at `x=31`, using a deterministic `5x7` font at `2x` scale.
- Weekly quota bar: frame `(4,43)` to `(58,48)`; 4% fill is exactly two pixels wide.
- Working-state squares: `6x6` at `x=80,89,98,107`, `y=28`.
- Full labels use a deterministic `3x5` font. Nothing is abbreviated.
- Bottom labels leave a 14-pixel gap between `RESET AT 11:45` and `1 RESET CREDIT`.
- Every visible pixel is produced by `render_homepage_v1.py` and can be reproduced in the FAP later.
