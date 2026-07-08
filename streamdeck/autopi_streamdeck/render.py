"""Render a key face image for the Stream Deck.

Draws the same face the web start menu shows for a key: a solid background
color, the action's Bootstrap Icons glyph centered above its label. The start
menu and this renderer share the same three fields off an ``ActionSpec``
(``label``, ``icon``, ``color``), so a key arranged on screen looks the same
on the physical deck.

Bootstrap Icons ships as a webfont addressed by CSS class (``bi-alarm`` etc).
Rather than depend on the app's static files being reachable from wherever
the controller runs, this module vendors its own copy of the font plus a
small glyph-name -> codepoint map generated from the app's CSS (see
``streamdeck/gen_icon_map.py``). When a requested icon has no entry in that
map, or the font fails to load at all, the icon falls back to a short text
abbreviation instead of leaving the key blank.

Kept pure and dependency-light: given a label/icon/color/size it returns a
PIL Image, nothing else touched. No network, no deck, no filesystem writes.
Any rendering error, or a missing Pillow, returns ``None``; callers fall back
on their own (the controller drops to a plainer face rather than crash).
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Optional

_ASSETS = Path(__file__).resolve().parent / "assets"
_FONT_PATH = _ASSETS / "bootstrap-icons.woff2"
_MAP_PATH = _ASSETS / "bootstrap-icons-map.json"

_BLANK_RGB = (17, 24, 39)      # matches the app's blank-key color, #111827
_TEXT_RGB = (255, 255, 255)
_BADGE_BG = (0, 0, 0)


@lru_cache(maxsize=1)
def _icon_codepoints() -> dict[str, str]:
    """Bootstrap Icons class name (e.g. "bi-alarm") to a one-character glyph."""
    try:
        with open(_MAP_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


@lru_cache(maxsize=16)
def _icon_font(size: int):
    from PIL import ImageFont
    return ImageFont.truetype(str(_FONT_PATH), size)


@lru_cache(maxsize=8)
def _label_font(size: int):
    from PIL import ImageFont
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        # Older Pillow: load_default() takes no size argument, so it is
        # always the same small bitmap font regardless of requested size.
        return ImageFont.load_default()


def render_key(
    label: str,
    icon: str,
    color: str,
    size: tuple[int, int],
    rotation: int = 0,
    badge: Optional[str] = None,
):
    """Return a PIL image for one key, or None if rendering is unavailable.

    ``label``, ``icon`` (a "bi-*" class name, or empty), and ``color`` (a hex
    string) are the same fields the web start menu renders for a key, so the
    physical face matches the on-screen tile. Pass empty label and icon for a
    blank slot: it draws as a plain background tile.

    ``badge`` draws a small marker in the bottom-right corner (used for the
    page-cycle key's "n of total" indicator); leave it None for a normal key.
    """
    try:
        from PIL import Image, ImageDraw
    except Exception:
        return None
    try:
        width, height = size
        img = Image.new("RGB", (max(1, width), max(1, height)), _hex_to_rgb(color))
        draw = ImageDraw.Draw(img)
        if icon or label:
            _draw_icon(draw, icon, label, width, height)
        if label:
            _draw_label(draw, label, width, height)
        if badge:
            _draw_badge(draw, badge, width, height)
        if rotation:
            img = img.rotate(-rotation, expand=False)
        return img
    except Exception:
        return None


def _draw_icon(draw, icon: str, label: str, width: int, height: int) -> None:
    """Draw the icon glyph in the upper portion of the tile.

    Falls back to a short text abbreviation when the icon name has no known
    glyph (an unrecognized or missing "bi-*" name), so a key never renders
    silently blank just because its icon could not be looked up.
    """
    cx = width / 2
    cy = height * 0.42
    glyph_size = int(min(width, height) * 0.44)
    if glyph_size < 1:
        return
    glyph = _icon_codepoints().get(icon) if icon else None
    if glyph:
        try:
            font = _icon_font(glyph_size)
            bbox = draw.textbbox((0, 0), glyph, font=font)
            w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
            draw.text((cx - w / 2 - bbox[0], cy - h / 2 - bbox[1]), glyph,
                      fill=_TEXT_RGB, font=font)
            return
        except Exception:
            pass  # fall through to the text abbreviation below
    abbrev = _abbreviate(icon, label)
    if not abbrev:
        return
    font = _label_font(int(glyph_size * 0.6) or 1)
    bbox = draw.textbbox((0, 0), abbrev, font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text((cx - w / 2 - bbox[0], cy - h / 2 - bbox[1]), abbrev, fill=_TEXT_RGB, font=font)


def _abbreviate(icon: str, label: str) -> str:
    """A one or two letter stand-in for a glyph that could not be drawn."""
    source = icon[3:] if icon and icon.startswith("bi-") else (icon or label)
    words = [w for w in re.split(r"[-_\s]+", source or "") if w]
    if not words:
        return ""
    if len(words) == 1:
        return words[0][:2].upper()
    return (words[0][0] + words[1][0]).upper()


def _draw_label(draw, label: str, width: int, height: int) -> None:
    """Draw the label, wrapped onto up to two lines, in the lower portion."""
    font_size = max(8, int(height * 0.15))
    font = _label_font(font_size)
    lines = _wrap_label(draw, label, font, int(width * 0.92))
    line_height = font_size * 1.25
    total_h = line_height * len(lines)
    y = height * 0.72 - total_h / 2
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        w = bbox[2] - bbox[0]
        draw.text((width / 2 - w / 2 - bbox[0], y - bbox[1]), line, fill=_TEXT_RGB, font=font)
        y += line_height


def _fits(draw, text: str, font, max_width: int) -> bool:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0] <= max_width


def _wrap_label(draw, label: str, font, max_width: int, max_lines: int = 2) -> list[str]:
    """Greedy word wrap onto at most ``max_lines``; overflow gets an ellipsis."""
    words = label.split()
    if not words:
        return []
    lines: list[str] = []
    idx = 0
    while idx < len(words) and len(lines) < max_lines:
        current = words[idx]
        idx += 1
        while idx < len(words) and _fits(draw, f"{current} {words[idx]}", font, max_width):
            current = f"{current} {words[idx]}"
            idx += 1
        lines.append(current)
    if idx < len(words) and lines:
        # More words than fit: mark the last line as truncated.
        last = lines[-1]
        while last and not _fits(draw, last + "…", font, max_width):
            last = last[:-1].rstrip()
        lines[-1] = (last or lines[-1][:1]) + "…"
    return lines


def _draw_badge(draw, badge: str, width: int, height: int) -> None:
    """Draw a small "n/total" style marker in the bottom-right corner."""
    font_size = max(8, int(height * 0.13))
    font = _label_font(font_size)
    bbox = draw.textbbox((0, 0), badge, font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pad = max(2, int(width * 0.03))
    x0, y0 = width - w - pad * 2, height - h - pad * 2
    x1, y1 = width - pad // 2, height - pad // 2
    draw.rectangle((x0, y0, x1, y1), fill=_BADGE_BG)
    draw.text((x0 + pad - bbox[0], y0 + pad - bbox[1]), badge, fill=_TEXT_RGB, font=font)


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    v = (value or "").lstrip("#")
    if len(v) == 3:
        v = "".join(c * 2 for c in v)
    try:
        return int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)
    except ValueError:
        return _BLANK_RGB
