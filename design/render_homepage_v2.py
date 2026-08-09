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


def render() -> Image.Image:
    image = Image.new("1", (WIDTH, HEIGHT), 1)
    draw = ImageDraw.Draw(image)

    # Header: the decorative logo is intentionally removed.
    draw_text(draw, (2, 2), "CODEX", FONT_5X7, 5)
    draw_text(draw, (76, 2), "USB", FONT_5X7, 5, anchor="center")

    draw.rectangle((93, 2, 106, 8), outline=0)
    draw.rectangle((107, 4, 108, 6), fill=0)
    draw.rectangle((95, 4, 102, 6), fill=0)
    draw_text(draw, (126, 3), "82%", FONT_3X5, 3, anchor="right")
    draw.line((0, 11, 127, 11), fill=0)

    # Main split area remains unchanged from the approved direction.
    draw.line((63, 12, 63, 50), fill=0)
    draw_text(draw, (31, 15), "WEEKLY LEFT", FONT_3X5, 3, anchor="center")
    draw_text(draw, (31, 24), "4%", FONT_5X7, 5, scale=2, anchor="center")
    draw.rectangle((4, 43, 58, 48), outline=0)
    draw.rectangle((6, 45, 7, 46), fill=0)

    draw_text(draw, (96, 16), "WORKING", FONT_5X7, 5, anchor="center")
    for index, x in enumerate((80, 89, 98, 107)):
        if index == 0:
            draw.rectangle((x, 28, x + 5, 33), fill=0)
        else:
            draw.rectangle((x, 28, x + 5, 33), outline=0)
    draw_text(draw, (96, 39), "1 ACTIVE TASK", FONT_3X5, 3, anchor="center")

    # Three-digit hours cover the full weekly countdown range without truncation.
    draw.line((0, 50, 127, 50), fill=0)
    draw_text(draw, (2, 55), "RESET IN 167:52", FONT_3X5, 3)
    draw_text(draw, (126, 55), "1 RESET", FONT_3X5, 3, anchor="right")

    return image


def main() -> None:
    output_dir = Path(__file__).resolve().parent
    native = render()
    native.save(output_dir / "homepage-v2-128x64.png")
    preview = native.convert("RGB").resize(
        (WIDTH * SCALE, HEIGHT * SCALE), Image.Resampling.NEAREST
    )
    preview.save(output_dir / "homepage-v2-preview-8x.png")


if __name__ == "__main__":
    main()
