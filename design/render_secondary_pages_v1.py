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
from render_usage_v1 import draw_secondary_header


def blank_page(title: str) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("1", (WIDTH, HEIGHT), 1)
    draw = ImageDraw.Draw(image)
    draw_secondary_header(draw, title)
    return image, draw


def render_quota() -> Image.Image:
    image, draw = blank_page("QUOTA")
    draw.line((63, 12, 63, 49), fill=0)
    draw_text(draw, (31, 15), "LEFT", FONT_3X5, 3, anchor="center")
    draw_text(draw, (31, 23), "99%", FONT_5X7, 5, scale=2, anchor="center")
    draw.rectangle((4, 43, 58, 48), outline=0)
    draw.rectangle((6, 45, 56, 46), fill=0)
    draw_text(draw, (95, 15), "RESET", FONT_3X5, 3, anchor="center")
    draw_text(draw, (95, 23), "7 DAYS", FONT_5X7, 5, anchor="center")
    draw_text(draw, (95, 36), "08-15 11:46", FONT_3X5, 3, anchor="center")
    draw.line((0, 50, 127, 50), fill=0)
    draw_text(draw, (2, 56), "1 RESET", FONT_3X5, 3)
    draw_text(draw, (126, 56), "UPDATED 17:27", FONT_3X5, 3, anchor="right")
    return image


def render_tasks() -> Image.Image:
    image, draw = blank_page("TASKS")
    draw_text(draw, (64, 15), "WORKING", FONT_5X7, 5, anchor="center")
    for index, x in enumerate((45, 54, 63, 72)):
        if index == 1:
            draw.rectangle((x, 27, x + 5, 32), fill=0)
        else:
            draw.rectangle((x, 27, x + 5, 32), outline=0)
    draw_text(draw, (64, 37), "1 TASK", FONT_3X5, 3, anchor="center")
    draw.line((0, 45, 127, 45), fill=0)
    draw_text(draw, (2, 49), "FOR 00:12", FONT_3X5, 3)
    draw_text(draw, (126, 49), "LAST DONE 16:53", FONT_3X5, 3, anchor="right")
    return image


def render_link() -> Image.Image:
    image, draw = blank_page("LINK")
    draw.line((63, 12, 63, 36), fill=0)
    draw_text(draw, (31, 15), "ACTIVE", FONT_3X5, 3, anchor="center")
    draw_text(draw, (31, 23), "USB", FONT_5X7, 5, anchor="center")
    draw_text(draw, (95, 15), "CODEX", FONT_3X5, 3, anchor="center")
    draw_text(draw, (95, 23), "ONLINE", FONT_5X7, 5, anchor="center")
    draw.line((0, 37, 127, 37), fill=0)
    draw.line((63, 38, 63, 52), fill=0)
    draw_text(draw, (31, 39), "USB", FONT_3X5, 3, anchor="center")
    draw_text(draw, (31, 46), "DISCONNECTED", FONT_3X5, 3, anchor="center")
    draw_text(draw, (95, 39), "BLUETOOTH", FONT_3X5, 3, anchor="center")
    draw_text(draw, (95, 46), "LINKED", FONT_3X5, 3, anchor="center")
    draw.line((0, 53, 127, 53), fill=0)
    draw_text(draw, (64, 57), "LINKED FOR 12 MINUTES", FONT_3X5, 3, anchor="center")
    return image


def render_usage_weekly() -> Image.Image:
    image, draw = blank_page("USAGE")
    draw_text(draw, (31, 14), "PEAK WEEK", FONT_3X5, 3, anchor="center")
    draw_text(draw, (31, 21), "3238 MILLION", FONT_3X5, 3, anchor="center")
    draw_text(draw, (95, 14), "THIS WEEK", FONT_3X5, 3, anchor="center")
    draw_text(draw, (95, 21), "2229 MILLION", FONT_3X5, 3, anchor="center")
    draw.line((0, 27, 127, 27), fill=0)
    values = (2191, 1853, 3238, 2229)
    maximum = max(values)
    for index, value in enumerate(values):
        x = 19 + index * 29
        height = max(1, round(20 * value / maximum))
        draw.rectangle((x, 50 - height, x + 12, 50), outline=0)
        if index == len(values) - 1:
            draw.rectangle((x + 2, 48 - height, x + 10, 48), fill=0)
    draw.line((4, 50, 123, 50), fill=0)
    draw_text(draw, (64, 56), "4 WEEKS", FONT_3X5, 3, anchor="center")
    return image


def render_usage_total() -> Image.Image:
    image, draw = blank_page("USAGE")
    rows = (
        ("TOTAL TOKENS", "23587528907"),
        ("PEAK DAY", "1032483805"),
        ("LONGEST TASK", "12:46"),
        ("CURRENT STREAK", "55 DAYS"),
        ("LONGEST STREAK", "55 DAYS"),
    )
    for index, (label, value) in enumerate(rows):
        y = 14 + index * 9
        draw_text(draw, (2, y), label, FONT_3X5, 3)
        draw_text(draw, (126, y), value, FONT_3X5, 3, anchor="right")
        if index < len(rows) - 1:
            draw.line((2, y + 6, 125, y + 6), fill=0)
    return image


def main() -> None:
    output_dir = Path(__file__).resolve().parent
    pages = {
        "quota-v1": render_quota(),
        "tasks-v1": render_tasks(),
        "link-v1": render_link(),
        "usage-weekly-v1": render_usage_weekly(),
        "usage-total-v1": render_usage_total(),
    }
    previews = []
    for name, native in pages.items():
        native.save(output_dir / f"{name}-128x64.png")
        preview = native.convert("RGB").resize(
            (WIDTH * SCALE, HEIGHT * SCALE), Image.Resampling.NEAREST
        )
        preview.save(output_dir / f"{name}-preview-8x.png")
        previews.append(preview)

    usage_daily = Image.open(output_dir / "usage-v1-preview-8x.png").convert("RGB")
    previews.insert(1, usage_daily)
    gap = 16
    overview = Image.new(
        "RGB",
        (WIDTH * SCALE * 2 + gap, HEIGHT * SCALE * 3 + gap * 2),
        "black",
    )
    for index, preview in enumerate(previews):
        x = (index % 2) * (WIDTH * SCALE + gap)
        y = (index // 2) * (HEIGHT * SCALE + gap)
        overview.paste(preview, (x, y))
    overview.save(output_dir / "secondary-pages-v1-overview.png")


if __name__ == "__main__":
    main()
