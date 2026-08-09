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


def draw_pace_meter(draw: ImageDraw.ImageDraw, position: int) -> None:
    needle_end = (
        (21, 26),
        (23, 22),
        (27, 19),
        (31, 18),
        (35, 19),
        (39, 22),
        (41, 26),
    )
    draw.ellipse((18, 15, 44, 41), outline=0)
    draw.ellipse((19, 16, 43, 40), outline=0)
    draw.rectangle((17, 29, 45, 49), fill=1)
    draw.line((31, 28, *needle_end[position]), fill=0)
    draw.ellipse((30, 27, 32, 29), fill=0)


def render() -> Image.Image:
    image = Image.new("1", (WIDTH, HEIGHT), 1)
    draw = ImageDraw.Draw(image)

    draw_text(draw, (2, 2), "CODEX", FONT_5X7, 5)
    draw_text(draw, (76, 2), "USB", FONT_5X7, 5, anchor="center")
    draw.rectangle((93, 2, 106, 8), outline=0)
    draw.rectangle((107, 4, 108, 6), fill=0)
    draw.rectangle((95, 4, 102, 6), fill=0)
    draw_text(draw, (126, 3), "82%", FONT_3X5, 3, anchor="right")
    draw.line((0, 11, 127, 11), fill=0)

    draw.line((63, 12, 63, 50), fill=0)
    draw_pace_meter(draw, 3)
    draw_text(draw, (31, 33), "4%", FONT_5X7, 5, anchor="center")
    draw.rectangle((4, 43, 58, 48), outline=0)
    draw.rectangle((6, 45, 7, 46), fill=0)

    draw_text(draw, (96, 13), "WORKING", FONT_5X7, 5, anchor="center")
    for segment in (
        (91, 25, 101, 25),
        (90, 26, 102, 26),
        (92, 27, 92, 28),
        (92, 28, 96, 32),
        (100, 27, 100, 28),
        (100, 28, 96, 32),
        (96, 32, 92, 36),
        (92, 36, 92, 37),
        (96, 32, 100, 36),
        (100, 36, 100, 37),
        (90, 38, 102, 38),
        (91, 39, 101, 39),
    ):
        draw.line(segment, fill=0)
    for segment in (
        (96, 30, 96, 30),
        (96, 35, 96, 35),
        (95, 36, 97, 36),
        (94, 37, 98, 37),
    ):
        draw.line(segment, fill=0)
    draw.point((96, 33), fill=0)
    draw_text(draw, (96, 44), "1 TASK", FONT_3X5, 3, anchor="center")

    draw.line((0, 50, 127, 50), fill=0)
    draw_text(draw, (2, 55), "RESET IN 7 DAYS", FONT_3X5, 3)
    draw_text(draw, (126, 55), "1 RESET", FONT_3X5, 3, anchor="right")

    return image


def main() -> None:
    output_dir = Path(__file__).resolve().parent
    native = render()
    native.save(output_dir / "homepage-v3-128x64.png")
    preview = native.convert("RGB").resize(
        (WIDTH * SCALE, HEIGHT * SCALE), Image.Resampling.NEAREST
    )
    preview.save(output_dir / "homepage-v3-preview-8x.png")


if __name__ == "__main__":
    main()
