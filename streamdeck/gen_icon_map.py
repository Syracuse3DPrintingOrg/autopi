#!/usr/bin/env python3
"""Regenerate the Bootstrap Icons glyph-name to codepoint map.

The Stream Deck controller renders each key's icon by drawing a single glyph
from the same Bootstrap Icons webfont the start menu uses, at the codepoint
its CSS class maps to. Rather than parse that CSS at controller startup, this
script does it once and writes a small JSON map the controller loads instead.

Run this after bumping the vendored bootstrap-icons.min.css (and re-copy the
matching bootstrap-icons.woff2, see below) so the two stay in lockstep:

    python3 streamdeck/gen_icon_map.py
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CSS_PATH = REPO_ROOT / "service" / "app" / "static" / "vendor" / "bootstrap-icons.min.css"
FONT_PATH = REPO_ROOT / "service" / "app" / "static" / "vendor" / "fonts" / "bootstrap-icons.woff2"

OUT_DIR = Path(__file__).resolve().parent / "autopi_streamdeck" / "assets"
OUT_MAP = OUT_DIR / "bootstrap-icons-map.json"
OUT_FONT = OUT_DIR / "bootstrap-icons.woff2"

_RULE = re.compile(r'\.bi-([a-z0-9-]+)::before\{content:"\\([0-9a-f]+)"\}')


def build_map(css_text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for name, hexcode in _RULE.findall(css_text):
        out[f"bi-{name}"] = chr(int(hexcode, 16))
    return out


def main() -> int:
    css_text = CSS_PATH.read_text(encoding="utf-8")
    icon_map = build_map(css_text)
    if not icon_map:
        raise SystemExit(f"No bi-*::before rules found in {CSS_PATH}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_MAP.write_text(json.dumps(icon_map, sort_keys=True, ensure_ascii=False), encoding="utf-8")
    shutil.copyfile(FONT_PATH, OUT_FONT)
    print(f"Wrote {len(icon_map)} glyphs to {OUT_MAP}")
    print(f"Copied font to {OUT_FONT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
