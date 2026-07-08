"""Tests for the server profile-sync client (AutoPi-aj2).

No real sync server exists yet, so every network path here mocks ``httpx``;
these tests must never touch the network.
"""
from __future__ import annotations

import httpx
import pytest
from starlette.testclient import TestClient

from app.config import settings
from app.db import init_db
from app.main import app
from app.services import profile_bundle, profile_sync
from app.services import profiles as profiles_svc


@pytest.fixture(autouse=True)
def _tables(temp_data_dir):
    init_db()


@pytest.fixture
def configured_settings(monkeypatch):
    monkeypatch.setattr(settings, "sync_server_url", "https://sync.example.com")
    monkeypatch.setattr(settings, "sync_device_token", "test-token")


class _FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def _client():
    return TestClient(app)


_SAMPLE_BUNDLE = {
    "key": "atlantis-high",
    "name": "Atlantis High",
    "year": 2023,
    "make": "Stellantis",
    "model": "Atlantis High",
    "updated": "2026-01-01T00:00:00Z",
    "bundle": {
        "databases": [],
        "actions": [],
        "layout": {},
        "simulation": [],
    },
}


# --- configured() ------------------------------------------------------------


def test_not_configured_when_empty():
    assert profile_sync.configured() is False


def test_not_configured_when_only_url_set(monkeypatch):
    monkeypatch.setattr(settings, "sync_server_url", "https://sync.example.com")
    monkeypatch.setattr(settings, "sync_device_token", "")
    assert profile_sync.configured() is False


def test_configured_when_both_set(configured_settings):
    assert profile_sync.configured() is True


# --- pure parsing ------------------------------------------------------------


def test_parse_remote_list_bare_list():
    parsed = profile_sync.parse_remote_list([
        {"key": "a", "name": "Car A", "year": 2020, "make": "M", "model": "X"},
        {"key": "b"},
    ])
    assert parsed[0]["name"] == "Car A"
    assert parsed[1]["name"] == "b"  # falls back to the key


def test_parse_remote_list_wrapped_in_profiles_key():
    parsed = profile_sync.parse_remote_list({"profiles": [{"key": "a", "name": "Car A"}]})
    assert parsed == [{"key": "a", "name": "Car A", "year": None, "make": "", "model": "", "updated": ""}]


def test_parse_remote_list_drops_entries_without_a_key():
    parsed = profile_sync.parse_remote_list([{"name": "No key"}, {"key": "ok"}])
    assert len(parsed) == 1
    assert parsed[0]["key"] == "ok"


def test_parse_remote_list_rejects_non_list_shape():
    assert profile_sync.parse_remote_list({"nope": True}) is None
    assert profile_sync.parse_remote_list("not a list") is None


def test_validate_bundle_payload_accepts_sample():
    assert profile_sync.validate_bundle_payload(_SAMPLE_BUNDLE) is None


def test_validate_bundle_payload_rejects_non_dict():
    assert profile_sync.validate_bundle_payload(["nope"]) is not None


def test_validate_bundle_payload_requires_key():
    bad = dict(_SAMPLE_BUNDLE)
    bad.pop("key")
    assert profile_sync.validate_bundle_payload(bad) is not None


def test_validate_bundle_payload_requires_bundle_object():
    bad = dict(_SAMPLE_BUNDLE)
    bad["bundle"] = "not an object"
    assert profile_sync.validate_bundle_payload(bad) is not None


def test_validate_bundle_payload_requires_list_fields():
    bad = {**_SAMPLE_BUNDLE, "bundle": {**_SAMPLE_BUNDLE["bundle"], "actions": "nope"}}
    assert profile_sync.validate_bundle_payload(bad) is not None


def test_validate_bundle_payload_requires_layout_object():
    bad = {**_SAMPLE_BUNDLE, "bundle": {**_SAMPLE_BUNDLE["bundle"], "layout": ["nope"]}}
    assert profile_sync.validate_bundle_payload(bad) is not None


# --- graceful degradation when unconfigured ----------------------------------


def test_list_remote_unconfigured():
    result = profile_sync.list_remote()
    assert result == {"ok": False, "error": profile_sync.NOT_CONFIGURED}


def test_pull_unconfigured():
    result = profile_sync.pull("atlantis-high")
    assert result["ok"] is False
    assert result["error"] == profile_sync.NOT_CONFIGURED


def test_pull_all_unconfigured():
    result = profile_sync.pull_all()
    assert result["ok"] is False


def test_push_is_a_clean_stub(configured_settings):
    result = profile_sync.push(1)
    assert result["ok"] is False
    assert "not implemented" in result["error"]


# --- unreachable server never raises -----------------------------------------


def test_list_remote_unreachable_server(configured_settings, monkeypatch):
    def _boom(*args, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "request", _boom)
    result = profile_sync.list_remote()
    assert result["ok"] is False
    assert "sync server" in result["error"].lower()


def test_pull_unreachable_server(configured_settings, monkeypatch):
    monkeypatch.setattr(httpx, "request", lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectError("nope")))
    result = profile_sync.pull("atlantis-high")
    assert result["ok"] is False


def test_list_remote_server_error_status(configured_settings, monkeypatch):
    monkeypatch.setattr(httpx, "request", lambda *a, **k: _FakeResponse(status_code=500))
    result = profile_sync.list_remote()
    assert result["ok"] is False
    assert "500" in result["error"]


def test_list_remote_malformed_json(configured_settings, monkeypatch):
    monkeypatch.setattr(httpx, "request", lambda *a, **k: _FakeResponse(status_code=200, payload=None))
    result = profile_sync.list_remote()
    assert result["ok"] is False


# --- list_remote against a mocked server -------------------------------------


def test_list_remote_success(configured_settings, monkeypatch):
    def _fake_request(method, url, headers=None, timeout=None):
        assert method == "GET"
        assert url == "https://sync.example.com/profiles"
        assert headers["Authorization"] == "Bearer test-token"
        return _FakeResponse(payload=[{"key": "atlantis-high", "name": "Atlantis High"}])

    monkeypatch.setattr(httpx, "request", _fake_request)
    result = profile_sync.list_remote()
    assert result["ok"] is True
    assert result["profiles"][0]["key"] == "atlantis-high"


# --- pull(): downloads, creates/finds the local profile, applies the bundle -


def test_pull_creates_local_profile_and_applies(configured_settings, monkeypatch):
    def _fake_request(method, url, headers=None, timeout=None):
        assert url == "https://sync.example.com/profiles/atlantis-high"
        return _FakeResponse(payload=_SAMPLE_BUNDLE)

    monkeypatch.setattr(httpx, "request", _fake_request)

    applied = {}

    def _fake_apply(pid):
        applied["id"] = pid
        return {"ok": True, "message": "ok"}

    monkeypatch.setattr(profile_bundle, "apply", _fake_apply)

    result = profile_sync.pull("atlantis-high")
    assert result["ok"] is True
    assert result["key"] == "atlantis-high"

    profiles = profiles_svc.list_profiles()
    assert len(profiles) == 1
    assert profiles[0]["name"] == "Atlantis High"
    assert profiles[0]["config"]["sync_key"] == "atlantis-high"
    assert applied["id"] == profiles[0]["id"]
    assert profile_bundle.has_bundle(profiles[0]["id"]) is True


def test_pull_reuses_existing_profile_by_sync_key(configured_settings, monkeypatch):
    def _fake_request(method, url, headers=None, timeout=None):
        return _FakeResponse(payload=_SAMPLE_BUNDLE)

    monkeypatch.setattr(httpx, "request", _fake_request)
    monkeypatch.setattr(profile_bundle, "apply", lambda pid: {"ok": True, "message": "ok"})

    first = profile_sync.pull("atlantis-high")
    second = profile_sync.pull("atlantis-high")
    assert first["profile_id"] == second["profile_id"]
    assert len(profiles_svc.list_profiles()) == 1


def test_pull_rejects_malformed_bundle(configured_settings, monkeypatch):
    monkeypatch.setattr(httpx, "request", lambda *a, **k: _FakeResponse(payload={"key": "x"}))
    result = profile_sync.pull("x")
    assert result["ok"] is False
    assert profiles_svc.list_profiles() == []


def test_pull_propagates_apply_failure(configured_settings, monkeypatch):
    monkeypatch.setattr(httpx, "request", lambda *a, **k: _FakeResponse(payload=_SAMPLE_BUNDLE))
    monkeypatch.setattr(profile_bundle, "apply", lambda pid: {"ok": False, "error": "boom"})
    result = profile_sync.pull("atlantis-high")
    assert result == {"ok": False, "error": "boom"}


def test_pull_all_success(configured_settings, monkeypatch):
    def _fake_request(method, url, headers=None, timeout=None):
        if url.endswith("/profiles"):
            return _FakeResponse(payload=[{"key": "a", "name": "Car A"}, {"key": "b", "name": "Car B"}])
        return _FakeResponse(payload={**_SAMPLE_BUNDLE, "key": url.rsplit("/", 1)[-1]})

    monkeypatch.setattr(httpx, "request", _fake_request)
    monkeypatch.setattr(profile_bundle, "apply", lambda pid: {"ok": True, "message": "ok"})

    result = profile_sync.pull_all()
    assert result["ok"] is True
    assert result["pulled"] == 2
    assert result["total"] == 2
    assert len(profiles_svc.list_profiles()) == 2


# --- router --------------------------------------------------------------


def test_router_status_unconfigured():
    with _client() as c:
        r = c.get("/sync/status")
    assert r.status_code == 200
    assert r.json()["configured"] is False


def test_router_list_unconfigured():
    with _client() as c:
        r = c.post("/sync/list")
    assert r.status_code == 200
    assert r.json()["ok"] is False


def test_router_pull_unconfigured():
    with _client() as c:
        r = c.post("/sync/pull", json={"key": "atlantis-high"})
    assert r.status_code == 200
    assert r.json()["ok"] is False


def test_router_pull_all_unconfigured():
    with _client() as c:
        r = c.post("/sync/pull-all")
    assert r.status_code == 200
    assert r.json()["ok"] is False


def test_router_status_reflects_configured(configured_settings):
    with _client() as c:
        r = c.get("/sync/status")
    body = r.json()
    assert body["configured"] is True
    assert body["server"] == "https://sync.example.com"


def test_router_list_success(configured_settings, monkeypatch):
    monkeypatch.setattr(
        httpx, "request",
        lambda *a, **k: _FakeResponse(payload=[{"key": "atlantis-high", "name": "Atlantis High"}]),
    )
    with _client() as c:
        r = c.post("/sync/list")
    body = r.json()
    assert body["ok"] is True
    assert body["profiles"][0]["key"] == "atlantis-high"


def test_router_pull_success(configured_settings, monkeypatch):
    monkeypatch.setattr(httpx, "request", lambda *a, **k: _FakeResponse(payload=_SAMPLE_BUNDLE))
    monkeypatch.setattr(profile_bundle, "apply", lambda pid: {"ok": True, "message": "ok"})
    with _client() as c:
        r = c.post("/sync/pull", json={"key": "atlantis-high"})
    body = r.json()
    assert body["ok"] is True
    assert body["key"] == "atlantis-high"


def test_setup_page_renders_profile_sync_pane():
    with _client() as c:
        r = c.get("/setup")
    assert r.status_code == 200
    assert "pane-profile-sync" in r.text
