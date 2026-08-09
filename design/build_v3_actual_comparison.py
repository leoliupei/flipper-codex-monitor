from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parent
PHOTO = Path(
    "/var/folders/dv/qjt1nb554lsfzv8z7_1513l00000gn/T/"
    "codex-clipboard-6a804106-cfae-4da0-bc1f-49a6c96f0e70.png"
)


def main() -> None:
    reference = Image.open(ROOT / "homepage-v3-preview-8x.png").convert("RGB")
    photo = Image.open(PHOTO).convert("RGB")

    # Normalize the photographed framebuffer region to the reference's 2:1 canvas.
    actual = photo.crop((329, 246, 1313, 758)).resize(
        reference.size, Image.Resampling.LANCZOS
    )

    comparison = Image.new("RGB", (reference.width * 2, reference.height), "white")
    comparison.paste(reference, (0, 0))
    comparison.paste(actual, (reference.width, 0))
    comparison.save(ROOT / "homepage-v3-reference-vs-actual.png")


if __name__ == "__main__":
    main()
