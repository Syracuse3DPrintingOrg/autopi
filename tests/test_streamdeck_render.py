"""Tests for the Stream Deck key-face renderer.

Pure PIL rendering: no physical deck, no network. These exercise the same
render_key() the controller calls for every key so the face-matching logic
stays covered without needing hardware.
"""
from autopi_streamdeck.render import render_key, _abbreviate, _icon_codepoints


SIZE = (72, 72)


def test_blank_key_is_a_plain_tile_of_the_right_size():
    img = render_key("", "", "#111827", SIZE)
    assert img is not None
    assert img.size == SIZE
    # A blank key has no icon or label drawn: every pixel is the fill color.
    colors = img.getcolors(maxcolors=SIZE[0] * SIZE[1])
    assert colors == [(SIZE[0] * SIZE[1], (17, 24, 39))]


def test_label_only_key_draws_text_without_an_icon():
    img = render_key("Start", "", "#334155", SIZE)
    assert img is not None
    assert img.size == SIZE
    # Some pixels differ from the flat background: the label was drawn.
    assert len(img.getcolors(maxcolors=SIZE[0] * SIZE[1])) > 1


def test_icon_and_label_key_draws_both():
    img = render_key("Clock", "bi-clock", "#4338ca", SIZE)
    assert img is not None
    assert img.size == SIZE
    assert len(img.getcolors(maxcolors=SIZE[0] * SIZE[1])) > 1


def test_known_icon_has_a_mapped_codepoint():
    codepoints = _icon_codepoints()
    assert "bi-clock" in codepoints
    assert "bi-chevron-right" in codepoints
    assert len(codepoints["bi-clock"]) == 1


def test_unknown_icon_falls_back_to_abbreviation_not_a_blank_key():
    known = render_key("Widget", "bi-clock", "#334155", SIZE)
    unknown = render_key("Widget", "bi-totally-not-a-real-icon", "#334155", SIZE)
    assert known is not None and unknown is not None
    # Both draw something (not a flat tile); they need not match pixel-for-pixel.
    assert len(unknown.getcolors(maxcolors=SIZE[0] * SIZE[1])) > 1
    assert known.tobytes() != unknown.tobytes()


def test_abbreviate_prefers_two_words_then_one_word_then_label():
    assert _abbreviate("bi-chevron-right", "More") == "CR"
    assert _abbreviate("bi-clock", "Clock") == "CL"
    assert _abbreviate("", "Screen Off") == "SO"
    assert _abbreviate("", "") == ""


def test_badge_draws_a_page_indicator_without_crashing():
    img = render_key("More", "bi-chevron-right", "#1f2937", SIZE, badge="2/3")
    assert img is not None
    assert img.size == SIZE


def test_rotation_preserves_size():
    for rotation in (0, 90, 180, 270):
        img = render_key("Clock", "bi-clock", "#4338ca", SIZE, rotation=rotation)
        assert img is not None
        assert img.size == SIZE


def test_size_adapts_to_the_deck_key_resolution():
    small = render_key("Clock", "bi-clock", "#4338ca", (48, 48))
    large = render_key("Clock", "bi-clock", "#4338ca", (144, 144))
    assert small.size == (48, 48)
    assert large.size == (144, 144)


def test_long_label_wraps_instead_of_overflowing():
    img = render_key("A Very Long Label That Will Not Fit On One Line",
                     "bi-clock", "#4338ca", SIZE)
    assert img is not None
    assert img.size == SIZE


def test_never_raises_on_a_bad_color():
    img = render_key("Oops", "bi-clock", "not-a-color", SIZE)
    assert img is not None
