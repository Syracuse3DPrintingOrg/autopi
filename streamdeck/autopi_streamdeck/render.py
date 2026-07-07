"""Render a key face image for the Stream Deck.

A minimal renderer: a solid accent-colored tile with the key label centered.
This is deliberately small; the source project's richer face styles (gradients,
glyphs, live faces) can be ported on top of this later without changing the
controller loop.
"""
from __future__ import annotations


def render_key(label: str, color: str, size: tuple[int, int], rotation: int = 0):
    """Return a PIL image for one key, or None if Pillow is unavailable."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception:
        return None
    img = Image.new("RGB", size, _hex_to_rgb(color))
    draw = ImageDraw.Draw(img)
    if label:
        try:
            font = ImageFont.load_default()
        except Exception:
            font = None
        text = label if len(label) <= 12 else label[:11] + "…"
        bbox = draw.textbbox((0, 0), text, font=font)
        w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text(((size[0] - w) / 2, (size[1] - h) / 2), text, fill=(255, 255, 255), font=font)
    if rotation:
        img = img.rotate(-rotation, expand=False)
    return img


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    v = (value or "#334155").lstrip("#")
    if len(v) == 3:
        v = "".join(c * 2 for c in v)
    try:
        return int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)
    except ValueError:
        return 51, 65, 85
