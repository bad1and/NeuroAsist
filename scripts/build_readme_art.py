"""Compose README artwork from existing Iris illustrations; no image generation.

Requires Pillow and the two PNG renders of the unchanged SVG wordmarks in
--logo-dir. Original flower PNGs live in the ignored local source folder.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "Docs/media/readme"
SOURCE = ROOT / "Для мусора (не удалять)"
FONTS = Path("C:/Windows/Fonts")


def sprig(filename: str, height: int) -> Image.Image:
    image = Image.open(SOURCE / filename).convert("RGBA")
    image = image.crop(image.getchannel("A").getbbox())
    image.thumbnail((600, height), Image.Resampling.LANCZOS)
    alpha = image.getchannel("A")
    # Only soften the source's clipped stem/outer edge; preserve the blossoms.
    pixels = alpha.load()
    fade = max(1, round(image.height * 0.13))
    for y in range(image.height):
        bottom = min(1.0, (image.height - 1 - y) / fade)
        bottom = bottom * bottom * (3 - 2 * bottom)
        for x in range(image.width):
            edge = min(1.0, x / 8)
            pixels[x, y] = round(pixels[x, y] * bottom * edge)
    image.putalpha(alpha)
    return image


def centred(draw: ImageDraw.ImageDraw, y: int, text: str, size: int, colour: str, *, bold: bool = False) -> None:
    font = ImageFont.truetype(str(FONTS / ("segoeuib.ttf" if bold else "segoeui.ttf")), size)
    draw.text((900, y), text, font=font, fill=colour, anchor="mt")


def frame(height: int, flower: Image.Image) -> Image.Image:
    canvas = Image.new("RGBA", (1800, height))
    y = (height - flower.height) // 2
    canvas.alpha_composite(flower, (32, y))
    canvas.alpha_composite(ImageOps.mirror(flower), (1800 - 32 - flower.width, y))
    return canvas


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--logo-dir", type=Path, required=True)
    args = parser.parse_args()
    hero_flower = sprig("Акварельные ирисы на прозрачном фоне.png", 580)
    section_flower = sprig("Фиолетовые ирисы на прозрачном фоне.png", 340)
    for theme in ("light", "dark"):
        colour = "#59636E" if theme == "light" else "#B7BEC9"
        logo = Image.open(args.logo_dir / f"logo-{theme}.png").convert("RGBA")
        logo.thumbnail((570, 240), Image.Resampling.LANCZOS)
        for lang, tagline, title in (
            ("ru", "Помощник, с которым можно поговорить", "Как выглядит Ирис"),
            ("en", "An assistant you can talk to", "What Iris looks like"),
        ):
            hero = frame(620, hero_flower)
            hero.alpha_composite(logo, ((1800 - logo.width) // 2, 135))
            centred(ImageDraw.Draw(hero), 395, tagline, 48, colour)
            hero.save(OUTPUT / f"header.{lang}.{theme}.png", optimize=True)
            section = frame(380, section_flower)
            draw = ImageDraw.Draw(section)
            centred(draw, 155, title, 64, colour)
            section.save(OUTPUT / f"interface.{lang}.{theme}.png", optimize=True)


if __name__ == "__main__":
    main()
