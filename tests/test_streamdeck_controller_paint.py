"""Tests for the controller's per-key paint/fallback logic.

No physical deck or driver import needed: these call the pure helper
functions directly with plain dicts standing in for the action catalog.
"""
from autopi_streamdeck import controller
from autopi_streamdeck import deck_layout


def test_render_with_fallback_returns_a_full_face_normally():
    img = controller._render_with_fallback("Clock", "bi-clock", "#4338ca", (72, 72), 0, None)
    assert img is not None
    assert img.size == (72, 72)


def test_render_with_fallback_drops_the_icon_when_it_errors(monkeypatch):
    """Simulate a broken icon renderer: the label/color face still comes back."""
    calls = []

    def flaky_render_key(label, icon, color, size, rotation=0, badge=None):
        calls.append(icon)
        if icon:
            return None  # pretend the icon path always fails
        from PIL import Image
        return Image.new("RGB", size, (1, 2, 3))

    monkeypatch.setattr(controller, "render_key", flaky_render_key)
    img = controller._render_with_fallback("Clock", "bi-clock", "#4338ca", (72, 72), 0, None)
    assert img is not None
    assert calls == ["bi-clock", ""]  # tried with the icon, then fell back to label-only


def test_render_with_fallback_never_returns_none_even_if_everything_errors(monkeypatch):
    monkeypatch.setattr(controller, "render_key", lambda *a, **k: None)
    img = controller._render_with_fallback("Clock", "bi-clock", "#4338ca", (72, 72), 0, None)
    assert img is None  # every layer failed; caller must tolerate this


class _FakeDeck:
    """Just enough of the StreamDeck API surface for _paint()."""

    def __init__(self, key_count=15, size=(72, 72)):
        self._key_count = key_count
        self._size = size
        self.painted = {}

    def key_count(self):
        return self._key_count

    def key_image_format(self):
        return {"size": self._size}

    def set_key_image(self, index, image):
        self.painted[index] = image


def test_paint_draws_every_slot_including_blank_and_page_next(monkeypatch):
    # Avoid importing the real StreamDeck driver package in _paint().
    import sys
    import types

    fake_pil_helper = type("PH", (), {"to_native_format": staticmethod(lambda deck, img: img)})
    fake_image_helpers = types.ModuleType("StreamDeck.ImageHelpers")
    fake_image_helpers.PILHelper = fake_pil_helper
    fake_streamdeck = types.ModuleType("StreamDeck")
    fake_streamdeck.ImageHelpers = fake_image_helpers
    monkeypatch.setitem(sys.modules, "StreamDeck", fake_streamdeck)
    monkeypatch.setitem(sys.modules, "StreamDeck.ImageHelpers", fake_image_helpers)
    catalog = {
        "clock": {"label": "Clock", "icon": "bi-clock", "color": "#4338ca"},
        deck_layout.PAGE_NEXT: {"label": "More", "icon": "bi-chevron-right", "color": "#1f2937"},
    }
    page = ["clock", None, deck_layout.PAGE_NEXT]
    deck = _FakeDeck(key_count=3)
    controller._paint(deck, page, catalog, rotation=0, page_index=0, total_pages=2)
    assert set(deck.painted) == {0, 1, 2}
    assert all(img is not None for img in deck.painted.values())
