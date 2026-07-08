"""The logic runtime: run rules on a scan loop against live inputs.

This closes the loop between the physical and CAN worlds (Phase 3). Each scan it
gathers named inputs, runs the pure logic engine, and fires the action ids the
rules ask for. Inputs can be:

- ``can_signal``: a signal decoded from the latest frame seen on a channel
  (via the CAN monitor buffer and the DBC), so a rule can react to, say, a
  vehicle speed or an infotainment state,
- ``gpio``: a GPIO input pin (a button, a sensor), and
- ``constant``: a fixed value, handy for testing.

The gathering and a single scan are kept injectable and pure so the loop is
testable without hardware or real threads. The thread is a thin wrapper.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable

from ..actions import registry
from ..can import monitor
from ..can import dbc as dbc_mod
from ..db import CanDatabase, CanMessage, session_scope
from ..services.state import StateFile
from ..config import settings
from .engine import Engine
from .store import load_rules


def _config_store() -> StateFile:
    return StateFile(settings.data_dir / "logic_runtime.json",
                     default={"enabled": False, "scan_ms": 200, "inputs": []})


def get_config() -> dict:
    return _config_store().read()


def set_config(cfg: dict) -> dict:
    doc = _config_store().read()
    for k in ("enabled", "scan_ms", "inputs"):
        if k in cfg:
            doc[k] = cfg[k]
    _config_store().write(doc)
    return doc


# --- input gathering (pure, given a frames provider and a gpio reader) -------
_resolve_cache: dict[tuple, tuple] = {}


def _resolve_can(database_id: int, message: str) -> tuple[int | None, str]:
    """Return (arbitration_id, dbc_text) for a message, cached."""
    key = (database_id, message)
    if key in _resolve_cache:
        return _resolve_cache[key]
    arb_id, dbc_text = None, ""
    try:
        with session_scope() as s:
            db = s.get(CanDatabase, database_id)
            if db is not None:
                dbc_text = db.dbc_text or ""
                msg = s.query(CanMessage).filter_by(database_id=database_id, name=message).first()
                if msg is not None:
                    arb_id = msg.arbitration_id
    except Exception:
        pass
    _resolve_cache[key] = (arb_id, dbc_text)
    return arb_id, dbc_text


def _latest_frame(records: list[dict], arb_id: int) -> dict | None:
    for rec in reversed(records):
        if rec.get("arbitration_id") == arb_id:
            return rec
    return None


def gather_inputs(inputs: list[dict], frames_for: Callable[[str, str], list[dict]],
                  gpio_read: Callable[[int], Any]) -> dict[str, Any]:
    """Build the {name: value} input map. Pure given the two readers."""
    out: dict[str, Any] = {}
    for spec in inputs or []:
        name = spec.get("name")
        if not name:
            continue
        kind = spec.get("type", "constant")
        if kind == "constant":
            out[name] = spec.get("value")
        elif kind == "gpio":
            try:
                out[name] = gpio_read(int(spec.get("pin")))
            except Exception:
                out[name] = None
        elif kind == "can_signal":
            arb_id, dbc_text = _resolve_can(int(spec.get("database_id", 0)), spec.get("message", ""))
            if arb_id is None or not dbc_text:
                out[name] = None
                continue
            records = frames_for(spec.get("channel", "can0"), spec.get("backend", "socketcan"))
            rec = _latest_frame(records, arb_id)
            decoded = monitor.decode_record(rec, dbc_text) if rec else None
            out[name] = decoded.get(spec.get("signal")) if decoded else None
    return out


def _real_frames(channel: str, backend: str) -> list[dict]:
    return monitor.get_monitor(channel, backend).frames()


def _real_gpio_read(pin: int):
    try:
        from gpiozero import Button
        return int(Button(pin).is_pressed)
    except Exception:
        return None


class LogicRuntime:
    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.last_result: dict = {}
        # One Engine instance lives for the runtime's whole life so its
        # per-scan state (edge memory, timer anchors, latch bits, and each
        # rule's previous output for rising/falling triggers) survives
        # between calls to scan_once. Only the rule list is refreshed each
        # scan, so an edit in the builder takes effect on the next scan
        # without losing in-flight timers or latches for rules that did not
        # change shape.
        self._engine = Engine([])

    def scan_once(self, now: float, *, frames_for=_real_frames, gpio_read=_real_gpio_read,
                  fire: Callable[[str], Any] = registry.run) -> dict:
        """One scan: gather inputs, run the engine, fire actions. Injectable."""
        cfg = get_config()
        self._engine.rules = load_rules()
        inputs = gather_inputs(cfg.get("inputs", []), frames_for, gpio_read)
        result = self._engine.scan(inputs, now)
        fired = []
        for action_id in result.fire:
            r = fire(action_id)
            fired.append({"id": action_id, "ok": getattr(r, "ok", None)})
        self.last_result = {"inputs": inputs, "outputs": result.outputs, "fired": fired, "ts": now}
        return self.last_result

    def _loop(self) -> None:
        while not self._stop.is_set():
            cfg = get_config()
            # Make sure the monitors feeding can_signal inputs are running.
            for spec in cfg.get("inputs", []):
                if spec.get("type") == "can_signal":
                    monitor.start_monitor(spec.get("channel", "can0"), spec.get("backend", "socketcan"))
            try:
                self.scan_once(time.time())
            except Exception:
                pass
            self._stop.wait(max(0.02, cfg.get("scan_ms", 200) / 1000.0))

    def start(self) -> bool:
        if self._thread and self._thread.is_alive():
            return True
        self._stop.clear()
        set_config({"enabled": True})
        self._thread = threading.Thread(target=self._loop, name="autopi-logic-runtime", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> bool:
        self._stop.set()
        set_config({"enabled": False})
        return True

    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())


runtime = LogicRuntime()
