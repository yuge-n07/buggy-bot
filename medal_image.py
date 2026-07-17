"""
medal_image.py
--------------
Generate a transparent‑background PNG image for a medal set,
matching the AceKyle site's layout but with a transparent background.
"""

from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import Optional

import requests
from PIL import Image, ImageDraw, ImageFont

from opbr import MedalSetResult

logger = logging.getLogger("buggy.medal_image")

# ----- Constants -----
WIDTH = 800
MARGIN = 30
MEDAL_SIZE = 80
TEXT_COLOR = (255, 255, 255)
GOLD = (204, 157, 80)
LINE_SPACING = 6

# Fonts – fallback to default if not found
FONT_BOLD = None
FONT_REGULAR = None
try:
    FONT_BOLD = ImageFont.truetype(
        str(Path(__file__).parent / "assets" / "fonts" / "NotoSans-Bold.ttf"),
        24
    )
    FONT_REGULAR = ImageFont.truetype(
        str(Path(__file__).parent / "assets" / "fonts" / "NotoSans-Regular.ttf"),
        16
    )
    FONT_SMALL = ImageFont.truetype(
        str(Path(__file__).parent / "assets" / "fonts" / "NotoSans-Regular.ttf"),
        12
    )
except Exception:
    FONT_BOLD = ImageFont.load_default()
    FONT_REGULAR = ImageFont.load_default()
    FONT_SMALL = ImageFont.load_default()


def download_icon(url: str, size: int = MEDAL_SIZE) -> Image.Image:
    try:
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        img = Image.open(io.BytesIO(resp.content))
        img = img.convert("RGBA")
        img = img.resize((size, size))
        return img
    except Exception as e:
        logger.warning(f"Failed to download icon: {e}")
        img = Image.new("RGBA", (size, size), (60, 60, 60, 255))
        draw = ImageDraw.Draw(img)
        draw.text((size//2-8, size//2-10), "?", fill=(255,255,255,255))
        return img


def wrap_text(text: str, font: ImageFont, max_width: int) -> list[str]:
    words = text.split()
    lines = []
    current_line = []
    for word in words:
        current_line.append(word)
        line = " ".join(current_line)
        bbox = font.getbbox(line)
        if bbox[2] - bbox[0] > max_width:
            current_line.pop()
            lines.append(" ".join(current_line))
            current_line = [word]
    if current_line:
        lines.append(" ".join(current_line))
    return lines


def generate_medal_set_image(
    result: MedalSetResult,
    tag_map: dict[int, str],
    alternative: Optional[MedalSetResult] = None
) -> Image.Image:
    y = MARGIN
    x = MARGIN
    content_width = WIDTH - 2 * MARGIN

    img = Image.new("RGBA", (WIDTH, 2000), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Header
    draw.text((x, y), "🏅 Best Medal Set", font=FONT_BOLD, fill=GOLD)
    y += 50

    # Medals
    for medal in result.medals:
        icon = download_icon(medal.icon_url)
        img.paste(icon, (x, y), icon)
        name_x = x + MEDAL_SIZE + 20
        draw.text((name_x, y), medal.name[:50], font=FONT_BOLD, fill=TEXT_COLOR)
        trait_lines = wrap_text(medal.unique_trait, FONT_SMALL, content_width - MEDAL_SIZE - 20)
        for j, line in enumerate(trait_lines[:2]):
            draw.text((name_x, y + 28 + j * 18), line, font=FONT_SMALL, fill=(200, 200, 200))
        y += MEDAL_SIZE + 15

    # Effects (tag bonuses)
    if result.tag_bonuses:
        y += 15
        draw.text((x, y), "📌 Effects", font=FONT_BOLD, fill=GOLD)
        y += 40
        for bonus in result.tag_bonuses:
            prefix = "🔺" if bonus.kind == "trio" else "🔹"
            line = f"{prefix} {bonus.tag_name}: {bonus.detail}"
            lines = wrap_text(line, FONT_SMALL, content_width)
            for line in lines:
                draw.text((x, y), line, font=FONT_SMALL, fill=TEXT_COLOR)
                y += 20
            y += 5

    # Tags
    all_tag_ids = set()
    for medal in result.medals:
        all_tag_ids.update(medal.tag_ids)
    if all_tag_ids:
        y += 15
        draw.text((x, y), "🏷️ Tags", font=FONT_BOLD, fill=GOLD)
        y += 35
        tag_names = [tag_map.get(tid, f"Tag {tid}") for tid in all_tag_ids]
        tag_text = ", ".join(sorted(tag_names))
        for line in wrap_text(tag_text, FONT_SMALL, content_width):
            draw.text((x, y), line, font=FONT_SMALL, fill=TEXT_COLOR)
            y += 20

    # Alternative set
    if alternative:
        y += 30
        draw.text((x, y), "🔄 Alternative Medals", font=FONT_BOLD, fill=GOLD)
        y += 50
        for medal in alternative.medals:
            icon = download_icon(medal.icon_url)
            img.paste(icon, (x, y), icon)
            name_x = x + MEDAL_SIZE + 20
            draw.text((name_x, y), medal.name[:50], font=FONT_BOLD, fill=TEXT_COLOR)
            trait_lines = wrap_text(medal.unique_trait, FONT_SMALL, content_width - MEDAL_SIZE - 20)
            for j, line in enumerate(trait_lines[:2]):
                draw.text((name_x, y + 28 + j * 18), line, font=FONT_SMALL, fill=(200, 200, 200))
            y += MEDAL_SIZE + 15

    # Footer
    y += 30
    draw.text((x, y), "ace-kyle.github.io/medal-set-builder", font=FONT_SMALL, fill=GOLD)
    y += 20
    draw.text((x, y), "Data from Ace Kyle's OPBR Medal Set Builder (fan tool)", font=FONT_SMALL, fill=(150, 150, 150))

    cropped = img.crop((0, 0, WIDTH, y + MARGIN))
    return cropped
