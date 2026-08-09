from pathlib import Path

from PIL import Image, ImageDraw

from render_homepage_v1 import (
    FONT_3X5,
    FONT_5X7,
    HEIGHT,
    SCALE,
    WIDTH,
    draw_text,
)


# Real account/usage/read daily buckets captured on 2026-08-08.
DAILY_TOKENS = (
    ("07-25", 450_415_895),
    ("07-26", 857_626_723),
    ("07-27", 372_478_410),
    ("07-28", 444_818_547),
    ("07-29", 478_783_758),
    ("07-30", 377_273_042),
    ("07-31", 256_812_520),
    ("08-01", 742_150_013),
    ("08-02", 916_189_521),
    ("08-03", 87_746_804),
    ("08-04", 70_053_439),
    ("08-05", 45_431_777),
    ("08-06", 124_199_590),
    ("08-07", 243_235_914),
)


def chart_points(
    values: tuple[int, ...], left: int, top: int, right: int, bottom: int
) -> list[tuple[int, int]]:
    maximum = max(values) or 1
    width = right - left
    height = bottom - top
    count = len(values)
    return [
        (
            left + round(index * width / (count - 1)),
            bottom - round(value * height / maximum),
        )
        for index, value in enumerate(values)
    ]


def draw_secondary_header(
    draw: ImageDraw.ImageDraw,
    title: str,
    link: str = "USB",
    battery_percent: int = 82,
) -> None:
    draw.line((7, 2, 3, 5, 7, 8), fill=0, width=1)
    draw.line((3, 5, 9, 5), fill=0, width=1)
    draw_text(draw, (12, 2), title, FONT_5X7, 5)
    draw_text(draw, (76, 2), link, FONT_5X7, 5, anchor="center")
    draw.rectangle((93, 2, 106, 8), outline=0)
    draw.rectangle((107, 4, 108, 6), fill=0)
    fill = max(0, min(10, battery_percent // 10))
    if fill:
        draw.rectangle((95, 4, 94 + fill, 6), fill=0)
    draw_text(draw, (126, 3), f"{battery_percent}%", FONT_3X5, 3, anchor="right")
    draw.line((0, 11, 127, 11), fill=0)


def render() -> Image.Image:
    image = Image.new("1", (WIDTH, HEIGHT), 1)
    draw = ImageDraw.Draw(image)

    draw_secondary_header(draw, "USAGE")

    values = tuple(value for _, value in DAILY_TOKENS)
    latest_millions = round(values[-1] / 1_000_000)
    peak_millions = round(max(values) / 1_000_000)

    # Two explicit statistics; MILLION is written in full to avoid an opaque unit.
    draw_text(draw, (31, 14), "RANGE PEAK", FONT_3X5, 3, anchor="center")
    draw_text(draw, (31, 21), f"{peak_millions} MILLION", FONT_3X5, 3, anchor="center")
    draw_text(draw, (95, 14), "LATEST", FONT_3X5, 3, anchor="center")
    draw_text(draw, (95, 21), f"{latest_millions} MILLION", FONT_3X5, 3, anchor="center")
    draw.line((0, 27, 127, 27), fill=0)

    # The full lower region is a deterministic, one-pixel daily line chart.
    chart_left = 4
    chart_top = 30
    chart_right = 123
    chart_bottom = 50
    for guide_y in (chart_top, (chart_top + chart_bottom) // 2):
        for guide_x in range(chart_left, chart_right + 1, 4):
            draw.point((guide_x, guide_y), fill=0)
    draw.line((chart_left, chart_bottom, chart_right, chart_bottom), fill=0)

    points = chart_points(values, chart_left, chart_top, chart_right, chart_bottom)
    draw.line(points, fill=0, width=1)
    for x, y in points:
        draw.point((x, y), fill=0)

    peak_index = values.index(max(values))
    peak_x, peak_y = points[peak_index]
    draw.rectangle((peak_x - 1, peak_y - 1, peak_x + 1, peak_y + 1), outline=0)

    latest_x, latest_y = points[-1]
    draw.rectangle((latest_x - 1, latest_y - 1, latest_x + 1, latest_y + 1), fill=0)

    draw_text(draw, (2, 56), DAILY_TOKENS[0][0], FONT_3X5, 3)
    draw_text(draw, (64, 56), "14 DAYS", FONT_3X5, 3, anchor="center")
    draw_text(draw, (126, 56), DAILY_TOKENS[-1][0], FONT_3X5, 3, anchor="right")

    return image


def main() -> None:
    output_dir = Path(__file__).resolve().parent
    native = render()
    native.save(output_dir / "usage-v1-128x64.png")
    preview = native.convert("RGB").resize(
        (WIDTH * SCALE, HEIGHT * SCALE), Image.Resampling.NEAREST
    )
    preview.save(output_dir / "usage-v1-preview-8x.png")


if __name__ == "__main__":
    main()
