from app.services import layout as layout_svc


def test_set_and_get_roundtrips_blanks():
    layout_svc.set_layout("start", ["a", None, "b"])
    assert layout_svc.get_layout("start") == ["a", None, "b"]


def test_unknown_surface_rejected():
    import pytest
    with pytest.raises(ValueError):
        layout_svc.set_layout("nope", ["a"])


def test_remove_action_everywhere_blanks_in_place():
    layout_svc.set_layout("start", ["a", "b", "c"])
    layout_svc.set_layout("streamdeck", ["x", "b", "y"])
    layout_svc.remove_action_everywhere("b")
    assert layout_svc.get_layout("start") == ["a", None, "c"]
    assert layout_svc.get_layout("streamdeck") == ["x", None, "y"]


def test_empty_string_normalizes_to_blank():
    layout_svc.set_layout("start", ["a", "", "b"])
    assert layout_svc.get_layout("start") == ["a", None, "b"]
