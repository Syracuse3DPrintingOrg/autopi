"""Automated test sequences: pure step evaluation, the runner state machine
driven with an injected clock and frames (no real thread or hardware),
persistence, and the router, including a full end-to-end run through a real
background thread with short delays.
"""
from __future__ import annotations

import time

import pytest
from starlette.testclient import TestClient

from app.main import app
from app.testseq import evaluation
from app.testseq import runner as runner_mod
from app.testseq import store
from app.testseq.model import Sequence, Step
from app.testseq.runner import DONE, RUNNING, WAITING_CONFIRM, Runner


@pytest.fixture(autouse=True)
def _reset_active_runner():
    yield
    runner_mod.reset_active()


class FakeClock:
    """A controllable clock: advance() moves time forward by milliseconds."""

    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def advance(self, ms: float) -> None:
        self.now += ms / 1000.0

    def __call__(self) -> float:
        return self.now


# -- pure evaluation ----------------------------------------------------------

def test_compare_value_ops():
    assert evaluation.compare_value("==", 1, 1) is True
    assert evaluation.compare_value("==", 1, 2) is False
    assert evaluation.compare_value("!=", 1, 2) is True
    assert evaluation.compare_value("<", 1, 2) is True
    assert evaluation.compare_value("<=", 2, 2) is True
    assert evaluation.compare_value(">", 3, 2) is True
    assert evaluation.compare_value(">=", 2, 2) is True
    assert evaluation.compare_value(">", 2, 2) is False


def test_compare_value_unknown_op_returns_false():
    assert evaluation.compare_value("~=", 1, 1) is False


def test_compare_value_type_mismatch_returns_false_not_raise():
    assert evaluation.compare_value("<", "abc", 1) is False


def test_evaluate_delay_pending_then_pass():
    step = Step(id="s1", type="delay", delay_ms=500)
    assert evaluation.evaluate_delay(step, started_at=0.0, now=0.1)["outcome"] == evaluation.PENDING
    result = evaluation.evaluate_delay(step, started_at=0.0, now=0.5)
    assert result["outcome"] == evaluation.PASS
    assert "500 ms" in result["message"]


def test_resolve_confirm_pass_and_fail():
    step = Step(id="s1", type="prompt", prompt_text="Did the horn sound?")
    passed = evaluation.resolve_confirm(step, True, "loud and clear")
    assert passed["outcome"] == evaluation.PASS
    assert "loud and clear" in passed["message"]
    failed = evaluation.resolve_confirm(step, False)
    assert failed["outcome"] == evaluation.FAIL


def test_match_expect_pending_when_no_frames_and_not_timed_out():
    step = Step(id="s1", type="expect", arbitration_id="0x100", timeout_ms=1000)
    result = evaluation.match_expect(step, [], None, started_at=0.0, now=0.2)
    assert result["outcome"] == evaluation.PENDING


def test_match_expect_fails_after_timeout_with_no_match():
    step = Step(id="s1", type="expect", arbitration_id="0x100", timeout_ms=100)
    result = evaluation.match_expect(step, [], None, started_at=0.0, now=0.2)
    assert result["outcome"] == evaluation.FAIL
    assert "Timed out" in result["message"]


def test_match_expect_passes_on_any_frame_with_matching_id():
    step = Step(id="s1", type="expect", arbitration_id="0x100", timeout_ms=1000)
    frames = [{"arbitration_id": 0x100, "data": [1, 2], "hex": "01 02", "timestamp": 0.1}]
    result = evaluation.match_expect(step, frames, None, started_at=0.0, now=0.15)
    assert result["outcome"] == evaluation.PASS
    assert result["observed"] == [1, 2]


def test_match_expect_ignores_non_matching_arbitration_id():
    step = Step(id="s1", type="expect", arbitration_id="0x100", timeout_ms=100)
    frames = [{"arbitration_id": 0x200, "data": [], "timestamp": 0.1}]
    result = evaluation.match_expect(step, frames, None, started_at=0.0, now=0.2)
    assert result["outcome"] == evaluation.FAIL


def test_match_expect_ignores_frames_from_before_the_step_started():
    """A frame left in the monitor's buffer from before this step began (or a
    previous run) must never count as this step's response."""
    step = Step(id="s1", type="expect", arbitration_id="0x100", timeout_ms=100)
    frames = [{"arbitration_id": 0x100, "data": [], "timestamp": 0.4}]  # before started_at
    result = evaluation.match_expect(step, frames, None, started_at=0.5, now=0.7)
    assert result["outcome"] == evaluation.FAIL


def test_match_expect_bad_arbitration_id_fails_immediately():
    step = Step(id="s1", type="expect", arbitration_id="not-hex", timeout_ms=1000)
    result = evaluation.match_expect(step, [], None, started_at=0.0, now=0.0)
    assert result["outcome"] == evaluation.FAIL
    assert "Bad arbitration id" in result["message"]


def test_match_expect_signal_check_passes_when_decoded_value_satisfies_op(monkeypatch):
    def fake_decode(dbc_text, arbitration_id, data):
        return {"DOOR_OPEN": 1}

    monkeypatch.setattr("app.can.dbc.decode", fake_decode)
    step = Step(id="s1", type="expect", arbitration_id="0x100", timeout_ms=1000,
                signal_name="DOOR_OPEN", op="==", value=1)
    frames = [{"arbitration_id": 0x100, "data": [1], "timestamp": 0.1}]
    result = evaluation.match_expect(step, frames, "fake dbc", started_at=0.0, now=0.15)
    assert result["outcome"] == evaluation.PASS
    assert result["observed"] == 1


def test_match_expect_signal_check_pending_when_value_does_not_satisfy_op_yet(monkeypatch):
    def fake_decode(dbc_text, arbitration_id, data):
        return {"DOOR_OPEN": 0}

    monkeypatch.setattr("app.can.dbc.decode", fake_decode)
    step = Step(id="s1", type="expect", arbitration_id="0x100", timeout_ms=1000,
                signal_name="DOOR_OPEN", op="==", value=1)
    frames = [{"arbitration_id": 0x100, "data": [0], "timestamp": 0.1}]
    result = evaluation.match_expect(step, frames, "fake dbc", started_at=0.0, now=0.15)
    assert result["outcome"] == evaluation.PENDING


def test_match_expect_signal_check_fails_after_timeout_reporting_last_seen(monkeypatch):
    def fake_decode(dbc_text, arbitration_id, data):
        return {"DOOR_OPEN": 0}

    monkeypatch.setattr("app.can.dbc.decode", fake_decode)
    step = Step(id="s1", type="expect", arbitration_id="0x100", timeout_ms=100,
                signal_name="DOOR_OPEN", op="==", value=1)
    frames = [{"arbitration_id": 0x100, "data": [0], "timestamp": 0.1}]
    result = evaluation.match_expect(step, frames, "fake dbc", started_at=0.0, now=0.2)
    assert result["outcome"] == evaluation.FAIL
    assert "last seen 0" in result["message"]


# -- runner state machine, injected clock and frames, no thread --------------

def _make_runner(steps, **collab):
    seq = Sequence(id="seq1", name="Bench check", steps=steps)
    return Runner(seq, **collab)


def test_runner_delay_step_pending_then_pass():
    clock = FakeClock()
    r = _make_runner([Step(id="d1", type="delay", delay_ms=200)], clock=clock)
    assert r.start(threaded=False) is True
    r.tick()  # begins the delay step
    assert r.status()["steps"][0]["status"] == "running"
    clock.advance(100)
    r.tick()
    assert r.status()["steps"][0]["status"] == "running"  # not yet elapsed
    clock.advance(150)
    r.tick()
    status = r.status()
    assert status["steps"][0]["status"] == "pass"
    assert status["state"] == DONE


def test_runner_start_twice_returns_false_while_running():
    clock = FakeClock()
    r = _make_runner([Step(id="d1", type="delay", delay_ms=1000)], clock=clock)
    assert r.start(threaded=False) is True
    assert r.start(threaded=False) is False


def test_runner_send_step_completes_in_one_tick():
    sent = []

    def fake_sender(channel, backend, step, dbc_text):
        sent.append((channel, step.arbitration_id))
        return True, "sent it"

    clock = FakeClock()
    step = Step(id="snd", type="send", channel="can0", arbitration_id="0x100", data="01 02")
    r = _make_runner([step], clock=clock, sender=fake_sender)
    r.start(threaded=False)
    r.tick()
    status = r.status()
    assert status["steps"][0]["status"] == "pass"
    assert status["state"] == DONE
    assert sent == [("can0", "0x100")]


def test_runner_send_step_fails_when_sender_reports_failure():
    def fake_sender(channel, backend, step, dbc_text):
        return False, "bus is down"

    r = _make_runner([Step(id="snd", type="send", arbitration_id="0x100")],
                     clock=FakeClock(), sender=fake_sender)
    r.start(threaded=False)
    r.tick()
    status = r.status()
    assert status["steps"][0]["status"] == "fail"
    assert status["steps"][0]["message"] == "bus is down"


def test_runner_expect_step_uses_injected_frames_and_clock():
    clock = FakeClock()
    frames: list[dict] = []
    step = Step(id="exp", type="expect", arbitration_id="0x200", timeout_ms=500)
    r = _make_runner([step], clock=clock, frame_source=lambda ch, be: frames)
    r.start(threaded=False)
    r.tick()  # begins the expect step
    assert r.status()["steps"][0]["status"] == "running"

    clock.advance(50)
    r.tick()
    assert r.status()["state"] == RUNNING  # still waiting, no frame yet

    frames.append({"arbitration_id": 0x200, "data": [9], "hex": "09", "timestamp": clock.now})
    r.tick()
    status = r.status()
    assert status["steps"][0]["status"] == "pass"
    assert status["state"] == DONE


def test_runner_expect_step_times_out_and_fails():
    clock = FakeClock()
    step = Step(id="exp", type="expect", arbitration_id="0x200", timeout_ms=100)
    r = _make_runner([step], clock=clock, frame_source=lambda ch, be: [])
    r.start(threaded=False)
    r.tick()
    clock.advance(150)
    r.tick()
    status = r.status()
    assert status["steps"][0]["status"] == "fail"
    assert "Timed out" in status["steps"][0]["message"]


def test_runner_action_step_runs_via_injected_action_runner():
    calls = []

    def fake_action_runner(action_id):
        calls.append(action_id)
        return True, "ran fine"

    r = _make_runner([Step(id="act", type="action", action_id="honk")],
                     clock=FakeClock(), action_runner=fake_action_runner)
    r.start(threaded=False)
    r.tick()
    status = r.status()
    assert status["steps"][0]["status"] == "pass"
    assert calls == ["honk"]


def test_runner_action_step_without_action_id_fails():
    r = _make_runner([Step(id="act", type="action", action_id="")], clock=FakeClock())
    r.start(threaded=False)
    r.tick()
    assert r.status()["steps"][0]["status"] == "fail"


def test_runner_prompt_step_waits_for_resolve_prompt():
    r = _make_runner([Step(id="p1", type="prompt", prompt_text="Confirm the horn sounded")],
                     clock=FakeClock())
    r.start(threaded=False)
    r.tick()
    status = r.status()
    assert status["state"] == WAITING_CONFIRM
    assert status["steps"][0]["status"] == "pending_confirm"

    # ticking while waiting on a confirm does nothing
    r.tick()
    assert r.status()["state"] == WAITING_CONFIRM

    assert r.resolve_prompt(True, "heard it") is True
    status = r.status()
    assert status["steps"][0]["status"] == "pass"
    assert status["steps"][0]["note"] == "heard it"
    assert status["state"] == DONE


def test_runner_resolve_prompt_returns_false_when_nothing_pending():
    r = _make_runner([Step(id="d1", type="delay", delay_ms=10)], clock=FakeClock())
    r.start(threaded=False)
    assert r.resolve_prompt(True) is False


def test_runner_prompt_step_can_fail():
    r = _make_runner([Step(id="p1", type="prompt", prompt_text="Confirm")], clock=FakeClock())
    r.start(threaded=False)
    r.tick()
    r.resolve_prompt(False, "nothing happened")
    assert r.status()["steps"][0]["status"] == "fail"


def test_runner_full_multi_step_run_with_injected_frames_and_clock():
    clock = FakeClock()
    frames: list[dict] = []
    sent = []
    actions = []

    steps = [
        Step(id="s1", type="delay", delay_ms=200),
        Step(id="s2", type="send", channel="can0", arbitration_id="0x100", data="01"),
        Step(id="s3", type="expect", channel="can0", arbitration_id="0x200", timeout_ms=1000),
        Step(id="s4", type="prompt", prompt_text="Confirm the light came on"),
        Step(id="s5", type="action", action_id="flash_light"),
    ]

    def fake_sender(channel, backend, step, dbc_text):
        sent.append(step.arbitration_id)
        return True, "sent"

    def fake_action_runner(action_id):
        actions.append(action_id)
        return True, "ran"

    r = _make_runner(
        steps, clock=clock, frame_source=lambda ch, be: frames,
        sender=fake_sender, action_runner=fake_action_runner,
    )
    r.start(threaded=False)

    r.tick()  # s1 begins
    clock.advance(250)
    r.tick()  # s1 passes, s2 begins+completes (send is one-shot)
    assert r.status()["current_index"] == 2

    r.tick()  # s3 begins
    frames.append({"arbitration_id": 0x200, "data": [], "timestamp": clock.now})
    r.tick()  # s3 passes, s4 begins (prompt)
    status = r.status()
    assert status["state"] == WAITING_CONFIRM

    assert r.resolve_prompt(True, "yes") is True
    r.tick()  # s5 begins+completes
    status = r.status()
    assert status["state"] == DONE

    report = r.report()
    assert report["ok"] is True
    assert report["passed"] == 5
    assert report["failed"] == 0
    assert report["total"] == 5
    assert sent == ["0x100"]
    assert actions == ["flash_light"]


def test_runner_sequence_with_no_steps_finishes_done_immediately():
    r = _make_runner([], clock=FakeClock())
    assert r.start(threaded=False) is True
    assert r.status()["state"] == DONE
    assert r.report()["total"] == 0
    assert r.report()["ok"] is True


def test_runner_a_failed_step_still_lets_the_run_finish_with_ok_false():
    clock = FakeClock()
    steps = [
        Step(id="e1", type="expect", arbitration_id="0x1", timeout_ms=50),
        Step(id="d2", type="delay", delay_ms=10),
    ]
    r = _make_runner(steps, clock=clock, frame_source=lambda ch, be: [])
    r.start(threaded=False)
    r.tick()
    clock.advance(60)
    r.tick()  # e1 fails, d2 begins
    clock.advance(20)
    r.tick()  # d2 passes
    report = r.report()
    assert report["state"] == DONE
    assert report["ok"] is False
    assert report["failed"] == 1
    assert report["passed"] == 1


# -- default collaborator: real CAN send path (no hardware present) ---------

def test_default_sender_reports_simulated_when_channel_unavailable():
    step = Step(id="s1", type="send", channel="can0", arbitration_id="0x100", data="01 02")
    ok, message = runner_mod._default_sender("can0", "socketcan", step, None)
    assert ok is True
    assert "simulated" in message


def test_default_sender_reports_error_for_bad_frame():
    step = Step(id="s1", type="send", channel="can0", arbitration_id="")
    ok, message = runner_mod._default_sender("can0", "socketcan", step, None)
    assert ok is False


# -- persistence ---------------------------------------------------------------

def test_store_create_get_update_delete_sequence():
    doc = store.create_sequence({
        "name": "Ignition check", "profile_id": 1,
        "steps": [{"id": "s1", "type": "delay", "delay_ms": 100}],
    })
    assert doc["id"]
    assert doc["name"] == "Ignition check"
    assert len(doc["steps"]) == 1
    assert doc["steps"][0]["type"] == "delay"

    fetched = store.get_sequence(doc["id"])
    assert fetched == doc

    updated = store.update_sequence(doc["id"], {"name": "Ignition check v2", "profile_id": 1, "steps": []})
    assert updated["name"] == "Ignition check v2"
    assert updated["steps"] == []

    assert store.delete_sequence(doc["id"]) is True
    assert store.get_sequence(doc["id"]) is None
    assert store.delete_sequence(doc["id"]) is False


def test_store_list_sequences_filters_by_profile_id():
    store.create_sequence({"name": "A", "profile_id": 1, "steps": []})
    store.create_sequence({"name": "B", "profile_id": 2, "steps": []})
    only_profile_1 = store.list_sequences(profile_id=1)
    assert [d["name"] for d in only_profile_1] == ["A"]
    assert len(store.list_sequences()) == 2


# -- router ---------------------------------------------------------------------

@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_router_crud_sequence(client):
    resp = client.post("/tests", json={"name": "Bench 1", "profile_id": None, "steps": []})
    assert resp.status_code == 200, resp.text
    seq_id = resp.json()["sequence"]["id"]

    listing = client.get("/tests").json()
    assert any(s["id"] == seq_id for s in listing["sequences"])

    got = client.get(f"/tests/{seq_id}")
    assert got.status_code == 200
    assert got.json()["name"] == "Bench 1"

    step = {
        "id": "st1", "type": "delay", "delay_ms": 10,
    }
    upd = client.put(f"/tests/{seq_id}", json={"name": "Bench 1", "profile_id": None, "steps": [step]})
    assert upd.status_code == 200
    assert len(upd.json()["sequence"]["steps"]) == 1

    dele = client.delete(f"/tests/{seq_id}")
    assert dele.status_code == 200
    assert client.get(f"/tests/{seq_id}").status_code == 404


def test_router_get_unknown_sequence_404s(client):
    assert client.get("/tests/does-not-exist").status_code == 404


def test_router_create_rejects_unknown_step_type(client):
    resp = client.post("/tests", json={"name": "Bad", "steps": [{"id": "s1", "type": "bogus"}]})
    assert resp.status_code == 400


def test_router_create_rejects_expect_without_arbitration_id(client):
    resp = client.post("/tests", json={"name": "Bad", "steps": [
        {"id": "s1", "type": "expect", "arbitration_id": ""},
    ]})
    assert resp.status_code == 400


def test_router_run_status_confirm_report_missing_run_404s(client):
    assert client.get("/tests/run/status").status_code == 404
    assert client.post("/tests/run/confirm", json={"passed": True}).status_code == 404
    assert client.get("/tests/run/report").status_code == 404


def test_router_run_unknown_sequence_404s(client):
    assert client.post("/tests/does-not-exist/run").status_code == 404


def test_router_run_sequence_with_no_steps_400s(client):
    created = client.post("/tests", json={"name": "Empty", "steps": []}).json()["sequence"]
    resp = client.post(f"/tests/{created['id']}/run")
    assert resp.status_code == 400


def test_router_full_run_over_the_real_background_thread(client):
    """A real run through the router: a short delay step, driven by the
    actual background thread and the real clock (not injected), the same
    path a technician's browser drives. Poll like the CAN monitor tests do
    for a background-thread result instead of sleeping a fixed amount.
    """
    created = client.post("/tests", json={
        "name": "Quick check", "steps": [{"id": "d1", "type": "delay", "delay_ms": 30}],
    }).json()["sequence"]

    run_resp = client.post(f"/tests/{created['id']}/run")
    assert run_resp.status_code == 200

    deadline = time.time() + 3.0
    status = client.get("/tests/run/status").json()
    while time.time() < deadline and status["state"] != "done":
        time.sleep(0.05)
        status = client.get("/tests/run/status").json()

    assert status["state"] == "done"
    assert status["steps"][0]["status"] == "pass"

    report = client.get("/tests/run/report").json()
    assert report["ok"] is True
    assert report["passed"] == 1


def test_router_run_with_prompt_step_waits_for_confirm(client):
    created = client.post("/tests", json={
        "name": "Needs confirm",
        "steps": [{"id": "p1", "type": "prompt", "prompt_text": "Did it beep?"}],
    }).json()["sequence"]

    client.post(f"/tests/{created['id']}/run")

    deadline = time.time() + 3.0
    status = client.get("/tests/run/status").json()
    while time.time() < deadline and status["state"] != "waiting_confirm":
        time.sleep(0.05)
        status = client.get("/tests/run/status").json()
    assert status["state"] == "waiting_confirm"

    confirm = client.post("/tests/run/confirm", json={"passed": True, "note": "yes it beeped"})
    assert confirm.status_code == 200

    deadline = time.time() + 3.0
    report = client.get("/tests/run/report").json()
    while time.time() < deadline and report["state"] != "done":
        time.sleep(0.05)
        report = client.get("/tests/run/report").json()
    assert report["ok"] is True
    assert report["steps"][0]["note"] == "yes it beeped"


def test_router_confirm_with_nothing_pending_400s(client):
    created = client.post("/tests", json={
        "name": "No prompt", "steps": [{"id": "d1", "type": "delay", "delay_ms": 5}],
    }).json()["sequence"]
    client.post(f"/tests/{created['id']}/run")
    deadline = time.time() + 3.0
    status = client.get("/tests/run/status").json()
    while time.time() < deadline and status["state"] != "done":
        time.sleep(0.05)
        status = client.get("/tests/run/status").json()
    resp = client.post("/tests/run/confirm", json={"passed": True})
    assert resp.status_code == 400


def test_ui_page_renders(client):
    resp = client.get("/ui/tests")
    assert resp.status_code == 200
    assert "Test sequences" in resp.text
