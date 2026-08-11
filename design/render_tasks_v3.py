from pathlib import Path

from PIL import Image, ImageDraw

from render_homepage_v1 import FONT_3X5, FONT_5X7, HEIGHT, SCALE, WIDTH, draw_text
from render_usage_v1 import draw_secondary_header


def blank(title: str) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("1", (WIDTH, HEIGHT), 1)
    draw = ImageDraw.Draw(image)
    draw_secondary_header(draw, title)
    return image, draw


def render_overview() -> Image.Image:
    image, draw = blank("TASKS")
    draw_text(draw, (2, 14), "2 WORKING", FONT_3X5, 3)
    draw_text(draw, (126, 14), "7 TASKS", FONT_3X5, 3, anchor="right")
    draw.line((0, 20, 127, 20), fill=0)

    rows = (
        ("FLIPPER", "WORKING", "02:31"),
        ("TRADING", "WORKING", "02:27"),
        ("COLLECT", "DONE", "02:19"),
    )
    for index, (label, state, started) in enumerate(rows):
        y = 23 + index * 10
        if index == 2:
            draw.rectangle((0, y - 2, 122, y + 7), fill=0)
            color = 1
        else:
            color = 0
        draw_text(draw, (2, y), label, FONT_3X5, 3, color=color)
        draw_text(draw, (44, y), state, FONT_3X5, 3, color=color)
        draw_text(draw, (121, y), started, FONT_3X5, 3, anchor="right", color=color)

    draw.line((126, 22, 126, 50), fill=0)
    draw.rectangle((124, 35, 126, 46), fill=0)

    draw.line((0, 53, 127, 53), fill=0)
    draw_text(draw, (2, 57), "TASK 6 OF 7", FONT_3X5, 3)
    draw_text(draw, (126, 57), "OK DETAILS", FONT_3X5, 3, anchor="right")
    return image


def render_live() -> Image.Image:
    image, draw = blank("FLIPPER")
    draw_text(draw, (2, 14), "WORKING", FONT_5X7, 5)
    draw_text(draw, (126, 15), "12 MINUTES", FONT_3X5, 3, anchor="right")
    draw.line((0, 23, 127, 23), fill=0)

    draw_text(draw, (31, 26), "TOTAL TOKENS", FONT_3X5, 3, anchor="center")
    draw_text(draw, (31, 34), "843973", FONT_5X7, 5, anchor="center")
    draw.line((63, 24, 63, 44), fill=0)
    draw_text(draw, (95, 26), "LAST CALL", FONT_3X5, 3, anchor="center")
    draw_text(draw, (95, 34), "14320", FONT_5X7, 5, anchor="center")

    draw_text(draw, (2, 47), "CONTEXT 33%", FONT_3X5, 3)
    draw.rectangle((49, 47, 126, 51), outline=0)
    draw.rectangle((51, 49, 74, 49), fill=0)
    draw.line((0, 54, 127, 54), fill=0)
    draw_text(draw, (2, 58), "UPDATED 3 SECONDS", FONT_3X5, 3)
    return image


def render_tokens() -> Image.Image:
    image, draw = blank("FLIPPER")
    rows = (
        ("INPUT", "520432"),
        ("CACHED INPUT", "388096"),
        ("OUTPUT", "8820"),
        ("REASONING OUTPUT", "1625"),
    )
    for index, (label, value) in enumerate(rows):
        y = 14 + index * 10
        draw_text(draw, (2, y), label, FONT_3X5, 3)
        draw_text(draw, (126, y), value, FONT_3X5, 3, anchor="right")
        if index < len(rows) - 1:
            draw.line((2, y + 6, 125, y + 6), fill=0)

    draw.line((0, 53, 127, 53), fill=0)
    draw_text(draw, (2, 57), "TOTAL 843973", FONT_3X5, 3)
    return image


def main() -> None:
    output_dir = Path(__file__).resolve().parent
    pages = {
        "tasks-overview-v3": render_overview(),
        "task-live-v3": render_live(),
        "task-tokens-v3": render_tokens(),
    }
    previews: list[Image.Image] = []
    for name, native in pages.items():
        native.save(output_dir / f"{name}-128x64.png")
        preview = native.convert("RGB").resize(
            (WIDTH * SCALE, HEIGHT * SCALE), Image.Resampling.NEAREST
        )
        preview.save(output_dir / f"{name}-preview-8x.png")
        previews.append(preview)

    gap = 16
    overview = Image.new(
        "RGB", (WIDTH * SCALE, HEIGHT * SCALE * len(previews) + gap * 2), "black"
    )
    y = 0
    for preview in previews:
        overview.paste(preview, (0, y))
        y += HEIGHT * SCALE + gap
    overview.save(output_dir / "tasks-v3-overview.png")


if __name__ == "__main__":
    main()
