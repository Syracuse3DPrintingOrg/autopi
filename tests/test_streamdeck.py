from starlette.testclient import TestClient

from app.main import app


def _client():
    return TestClient(app)


def test_status_falls_back_to_model_without_a_deck(monkeypatch):
    from app.config import settings
    settings.deck_model = 15
    with _client() as c:
        st = c.get("/streamdeck/status").json()
    assert st["connected"] is False
    assert st["key_count"] == 15
    assert st["supported"] == [6, 15, 32]


def test_reported_deck_scales_the_grid():
    with _client() as c:
        c.post("/streamdeck/status", json={"connected": True, "key_count": 32, "deck_type": "XL"})
        st = c.get("/streamdeck/status").json()
    assert st["connected"] is True
    assert st["key_count"] == 32
    assert st["deck_type"] == "XL"


def test_unknown_reported_key_count_ignored():
    with _client() as c:
        c.post("/streamdeck/status", json={"connected": True, "key_count": 99})
        st = c.get("/streamdeck/status").json()
    # 99 is not a real deck size: fall back to the configured model.
    assert st["key_count"] in (6, 15, 32)


def test_restart_sets_a_flag_the_controller_reads():
    with _client() as c:
        before = c.get("/streamdeck/status").json().get("restart_ts", 0)
        r = c.post("/streamdeck/restart").json()
        after = c.get("/streamdeck/status").json()["restart_ts"]
    assert r["ok"] is True                    # never the old "no service" error
    assert after > before                     # controller will see this and relaunch


def test_status_exposes_desired_rotation_and_brightness():
    from app.config import settings
    settings.deck_rotation = 90
    settings.deck_brightness = 42
    with _client() as c:
        st = c.get("/streamdeck/status").json()
    assert st["rotation"] == 90
    assert st["brightness"] == 42


def test_actions_carry_category_and_deck_only_flags():
    with _client() as c:
        actions = c.get("/actions").json()["actions"]
    by_id = {a["id"]: a for a in actions}
    assert by_id["page_next"]["deck_only"] is True
    assert by_id["page_next"]["category"] == "Navigation"
