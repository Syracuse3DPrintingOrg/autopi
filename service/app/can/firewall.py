"""CAN gateway: forward frames between two channels through an ordered rule
set, with allow, block, rewrite, and inject actions.

The rule evaluation (:func:`apply_rules`) is a pure function of a
:class:`~app.can.base.Frame`, the rule list, and the direction being
evaluated, so it is unit-testable with hand-built frames and no thread or
hardware involved: a test calls it directly and checks the returned
:class:`Decision`. The background engine (:class:`GatewayEngine`) mirrors
:class:`app.can.simulation.SimEngine`: one daemon thread per forwarding
direction, each a thin loop around ``provider.recv()`` -> :func:`apply_rules`
-> ``provider.send()``. Reading channel A and sending to channel B (and vice
versa) never triggers a provider's own-message loopback, since that concern
only applies to a single provider hearing frames it sent itself; a gateway
always sends on the *other* channel.

Rule sets and the gateway's channel pair persist in a JSON state file
(``can_firewall.json`` under data_dir) through the same atomic
:class:`~app.services.state.StateFile` pattern used by the transmit
simulation list.
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field, replace
from typing import Any, Callable

from ..config import settings
from ..services.state import StateFile
from .base import Frame, parse_data_bytes
from .registry import get_channel

log = logging.getLogger(__name__)

DIRECTIONS = ("a_to_b", "b_to_a")

# How long a direction's reader blocks waiting for a frame before checking
# the stop flag.
RECV_TIMEOUT = 0.5


def _store() -> StateFile:
    return StateFile(settings.data_dir / "can_firewall.json", default={
        "channel_a": "can0",
        "backend_a": "socketcan",
        "channel_b": "can1",
        "backend_b": "socketcan",
        "forward_a_to_b": True,
        "forward_b_to_a": True,
        "rules": [],
    })


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


# -- configuration persistence -----------------------------------------------

def get_config() -> dict[str, Any]:
    return _store().read()


def update_config(data: dict[str, Any]) -> dict[str, Any]:
    """Merge fields into the gateway configuration (channels, directions)."""
    store = _store()
    doc = store.read()
    doc.update({k: v for k, v in data.items() if k != "rules"})
    store.write(doc)
    return doc


# -- rule persistence ---------------------------------------------------

def list_rules() -> list[dict[str, Any]]:
    return _store().read().get("rules", [])


def get_rule(rule_id: str) -> dict[str, Any] | None:
    for rule in list_rules():
        if rule.get("id") == rule_id:
            return rule
    return None


def create_rule(data: dict[str, Any]) -> dict[str, Any]:
    rule = dict(data)
    rule["id"] = rule.get("id") or _new_id()
    store = _store()
    doc = store.read()
    rules = doc.get("rules", [])
    rules.append(rule)
    doc["rules"] = rules
    store.write(doc)
    return rule


def update_rule(rule_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
    store = _store()
    doc = store.read()
    rules = doc.get("rules", [])
    for i, rule in enumerate(rules):
        if rule.get("id") == rule_id:
            updated = dict(rule)
            updated.update(data)
            updated["id"] = rule_id
            rules[i] = updated
            doc["rules"] = rules
            store.write(doc)
            return updated
    return None


def delete_rule(rule_id: str) -> bool:
    store = _store()
    doc = store.read()
    rules = doc.get("rules", [])
    remaining = [r for r in rules if r.get("id") != rule_id]
    if len(remaining) == len(rules):
        return False
    doc["rules"] = remaining
    store.write(doc)
    return True


def reorder_rules(rule_ids: list[str]) -> list[dict[str, Any]]:
    """Set the evaluation order explicitly. Unlisted rules keep their
    relative order and are appended after the ones named."""
    store = _store()
    doc = store.read()
    rules = doc.get("rules", [])
    by_id = {r.get("id"): r for r in rules}
    ordered = [by_id[i] for i in rule_ids if i in by_id]
    ordered += [r for r in rules if r.get("id") not in rule_ids]
    doc["rules"] = ordered
    store.write(doc)
    return ordered


# -- rule evaluation (pure) ---------------------------------------------

DbcTextLookup = Callable[[int], "str | None"]


@dataclass
class Decision:
    """The outcome of evaluating one frame against the rule set."""

    action: str  # "allow" | "block" | "rewrite" | "inject"
    rule_id: str | None
    frame: Frame | None            # the frame to forward, None when blocked
    injected: list[Frame] = field(default_factory=list)


def _compare(value: Any, op: str, target: Any) -> bool:
    try:
        if op == "eq":
            return value == target
        if op == "ne":
            return value != target
        if op == "gt":
            return value > target
        if op == "lt":
            return value < target
        if op == "ge":
            return value >= target
        if op == "le":
            return value <= target
    except TypeError:
        return False
    return False


def _match_id(arbitration_id: int, match: dict[str, Any]) -> bool:
    if match.get("arbitration_id") is not None:
        target = match["arbitration_id"]
        mask = match.get("mask")
        if mask is not None:
            return (arbitration_id & mask) == (target & mask)
        return arbitration_id == target
    id_min = match.get("id_min")
    id_max = match.get("id_max")
    if id_min is not None or id_max is not None:
        lo = id_min if id_min is not None else 0
        hi = id_max if id_max is not None else 0x1FFFFFFF
        return lo <= arbitration_id <= hi
    return True


def _match_signal(frame: Frame, match: dict[str, Any], dbc_lookup: DbcTextLookup | None) -> bool:
    signal = match.get("signal")
    if not signal:
        return True
    database_id = match.get("database_id")
    if not database_id or dbc_lookup is None:
        return False  # a signal condition that cannot be evaluated does not match
    dbc_text = dbc_lookup(database_id)
    if not dbc_text:
        return False
    from . import dbc as dbc_mod
    try:
        decoded = dbc_mod.decode(dbc_text, frame.arbitration_id, bytes(frame.data))
    except Exception:
        return False
    if signal not in decoded:
        return False
    op = match.get("op", "eq")
    return _compare(decoded[signal], op, match.get("value"))


def _rule_matches(frame: Frame, rule: dict[str, Any], direction: str) -> bool | None:
    """Returns False right away when the direction does not apply, so the
    caller can skip the (potentially DBC-decoding) match check entirely."""
    rule_direction = rule.get("direction", "both")
    if rule_direction != "both" and rule_direction != direction:
        return False
    return None


def _rewrite_frame(frame: Frame, spec: dict[str, Any], dbc_lookup: DbcTextLookup | None) -> Frame:
    """Apply a rewrite action's spec to a frame.

    Raw ``data`` overwrites the payload outright. A ``database_id`` +
    ``message`` + ``signals`` spec decodes the frame's current signal values,
    merges in the overridden ones, and re-encodes the whole message, so a
    rule that changes one signal (e.g. spoof a speed reading) leaves every
    other field, counter, and checksum consistent rather than zeroing them.
    """
    if spec.get("data") is not None:
        raw = spec["data"]
        data = parse_data_bytes(raw) if isinstance(raw, str) else list(raw)
        return replace(frame, data=data)

    database_id = spec.get("database_id")
    message = spec.get("message")
    if database_id and message not in (None, ""):
        if dbc_lookup is None:
            return frame
        dbc_text = dbc_lookup(database_id)
        if not dbc_text:
            return frame  # no database to rewrite against; pass through unmodified
        from . import dbc as dbc_mod
        try:
            current = dbc_mod.decode(dbc_text, frame.arbitration_id, bytes(frame.data))
        except Exception:
            current = {}
        merged = {**current, **(spec.get("signals") or {})}
        try:
            data = dbc_mod.encode(dbc_text, message, merged, checksum=spec.get("checksum", ""))
        except Exception as exc:
            log.info("Firewall rewrite failed to re-encode %s: %s", message, exc)
            return frame
        return replace(frame, data=data)
    return frame


def _build_inject_frame(spec: dict[str, Any], dbc_lookup: DbcTextLookup | None) -> Frame | None:
    """Build the extra frame an inject rule emits, reusing the transmit
    simulation's entry-building logic (raw hex data, or DBC-encoded signals)
    so both surfaces describe a frame the same way."""
    if not spec or spec.get("arbitration_id") in (None, ""):
        return None
    from .simulation import build_frame as build_entry_frame
    dbc_text = None
    if spec.get("database_id") and dbc_lookup is not None:
        dbc_text = dbc_lookup(spec["database_id"])
    try:
        return build_entry_frame(spec, dbc_text)
    except ValueError as exc:
        log.info("Firewall inject rule produced an invalid frame: %s", exc)
        return None


def apply_rules(
    frame: Frame,
    rules: list[dict[str, Any]],
    direction: str,
    dbc_lookup: DbcTextLookup | None = None,
) -> Decision:
    """Evaluate the ordered rule set against one frame for one direction.

    The first enabled rule that matches wins; its action decides the
    outcome. A rule's ``direction`` field ("a_to_b", "b_to_a", or "both")
    gates whether it is even considered for this call's ``direction``. No
    rule matching means the default: pass the frame through unmodified
    (``action`` "allow", ``rule_id`` None).
    """
    for rule in rules:
        if not rule.get("enabled", True):
            continue
        if _rule_matches(frame, rule, direction) is False:
            continue
        match = rule.get("match", {}) or {}
        if not _match_id(frame.arbitration_id, match):
            continue
        if not _match_signal(frame, match, dbc_lookup):
            continue

        action = rule.get("action", "allow")
        rule_id = rule.get("id")
        if action == "block":
            return Decision(action="block", rule_id=rule_id, frame=None)
        if action == "rewrite":
            rewritten = _rewrite_frame(frame, rule.get("rewrite", {}) or {}, dbc_lookup)
            return Decision(action="rewrite", rule_id=rule_id, frame=rewritten)
        if action == "inject":
            injected = _build_inject_frame(rule.get("inject", {}) or {}, dbc_lookup)
            return Decision(action="inject", rule_id=rule_id, frame=frame,
                            injected=[injected] if injected is not None else [])
        # "allow" (or anything unrecognized) passes the frame through as-is.
        return Decision(action="allow", rule_id=rule_id, frame=frame)

    return Decision(action="allow", rule_id=None, frame=frame)


# -- gateway engine (impure: threads and providers) --------------------------

ConfigResolver = Callable[[], dict[str, Any]]
RulesResolver = Callable[[], list[dict[str, Any]]]
FrameSender = Callable[[str, str, Frame], bool]


def _default_dbc_text_resolver(database_id: int) -> str | None:
    from ..db import session_scope
    from ..db.models import CanDatabase
    with session_scope() as s:
        database = s.get(CanDatabase, database_id)
        return database.dbc_text if database else None


def _default_sender(backend: str, channel: str, frame: Frame) -> bool:
    return get_channel(channel, backend=backend).send(frame)


def _empty_stats() -> dict[str, int]:
    return {"forwarded": 0, "blocked": 0, "rewritten": 0, "injected": 0, "errors": 0}


class GatewayEngine:
    """Background forwarder between two CAN channels, gated by an ordered
    rule set. One daemon thread runs per enabled forwarding direction; each
    is a thin loop around ``provider.recv()`` -> :func:`apply_rules` ->
    ``provider.send()`` on the opposite channel, so tests can drive the
    forwarding decision directly through :func:`apply_rules` with no thread
    at all, and only start/stop need a real (or fake) provider.
    """

    def __init__(
        self,
        config_resolver: ConfigResolver | None = None,
        rules_resolver: RulesResolver | None = None,
        dbc_text_resolver: DbcTextLookup | None = None,
        sender: FrameSender | None = None,
        channel_factory: Callable[..., Any] | None = None,
    ) -> None:
        self._config_resolver = config_resolver or get_config
        self._rules_resolver = rules_resolver or list_rules
        self._dbc_text_resolver = dbc_text_resolver or _default_dbc_text_resolver
        self._sender = sender or _default_sender
        self._get_channel = channel_factory or get_channel
        self._lock = threading.Lock()
        self._threads: list[threading.Thread] = []
        self._running = False
        self._stats = _empty_stats()
        self._error: str | None = None

    def is_running(self) -> bool:
        return self._running

    def _channel_pair(self, config: dict[str, Any]) -> tuple[tuple[str, str], tuple[str, str]]:
        a = (config.get("channel_a", "can0"), config.get("backend_a", "socketcan"))
        b = (config.get("channel_b", "can1"), config.get("backend_b", "socketcan"))
        return a, b

    def start(self) -> tuple[bool, str | None]:
        """Start the enabled forwarding direction(s). Returns ``(ok, error)``;
        ``error`` explains why when the gateway cannot start (same channel on
        both sides, or neither direction turned on)."""
        config = self._config_resolver()
        (chan_a, backend_a), (chan_b, backend_b) = self._channel_pair(config)
        if (chan_a, backend_a) == (chan_b, backend_b):
            return False, "The gateway needs two different CAN interfaces; A and B are the same channel right now."
        directions = []
        if config.get("forward_a_to_b", True):
            directions.append("a_to_b")
        if config.get("forward_b_to_a", True):
            directions.append("b_to_a")
        if not directions:
            return False, "Turn on forwarding in at least one direction to start the gateway."
        with self._lock:
            if self._running:
                return False, "The gateway is already running."
            self._running = True
            self._stats = _empty_stats()
            self._error = None
            self._threads = [
                threading.Thread(target=self._loop, args=(d,), daemon=True, name=f"can-gateway-{d}")
                for d in directions
            ]
            for t in self._threads:
                t.start()
        return True, None

    def stop(self) -> bool:
        with self._lock:
            if not self._running:
                return False
            self._running = False
        for t in self._threads:
            t.join(timeout=2.0)
        self._threads = []
        return True

    def status(self) -> dict[str, Any]:
        config = self._config_resolver()
        (chan_a, backend_a), (chan_b, backend_b) = self._channel_pair(config)
        try:
            live_a = self._get_channel(chan_a, backend=backend_a).available
        except Exception:
            live_a = False
        try:
            live_b = self._get_channel(chan_b, backend=backend_b).available
        except Exception:
            live_b = False
        needs_two = (chan_a, backend_a) == (chan_b, backend_b)
        with self._lock:
            stats = dict(self._stats)
            error = self._error
        return {
            "running": self._running,
            "channel_a": chan_a, "backend_a": backend_a, "live_a": live_a,
            "channel_b": chan_b, "backend_b": backend_b, "live_b": live_b,
            "forward_a_to_b": config.get("forward_a_to_b", True),
            "forward_b_to_a": config.get("forward_b_to_a", True),
            "needs_two_interfaces": needs_two,
            "stats": stats,
            "error": error,
        }

    def _loop(self, direction: str) -> None:
        config = self._config_resolver()
        (chan_a, backend_a), (chan_b, backend_b) = self._channel_pair(config)
        if direction == "a_to_b":
            from_channel, from_backend = chan_a, backend_a
            to_channel, to_backend = chan_b, backend_b
        else:
            from_channel, from_backend = chan_b, backend_b
            to_channel, to_backend = chan_a, backend_a
        provider = self._get_channel(from_channel, backend=from_backend)
        while self._running:
            try:
                frame = provider.recv(timeout=RECV_TIMEOUT)
            except Exception as exc:
                log.info("CAN gateway recv failed on %s: %s", from_channel, exc)
                with self._lock:
                    self._error = str(exc)
                    self._stats["errors"] += 1
                time.sleep(RECV_TIMEOUT)
                continue
            if frame is None:
                continue
            rules = self._rules_resolver()
            decision = apply_rules(frame, rules, direction, self._dbc_text_resolver)
            with self._lock:
                if decision.action == "block":
                    self._stats["blocked"] += 1
                elif decision.action == "rewrite":
                    self._stats["rewritten"] += 1
                else:
                    self._stats["forwarded"] += 1
                if decision.injected:
                    self._stats["injected"] += len(decision.injected)
            to_send = ([decision.frame] if decision.frame is not None else []) + decision.injected
            for out_frame in to_send:
                try:
                    ok = self._sender(to_backend, to_channel, out_frame)
                except Exception as exc:
                    log.info("CAN gateway send failed on %s: %s", to_channel, exc)
                    ok = False
                if not ok:
                    with self._lock:
                        self._stats["errors"] += 1


# Module-level singleton shared by the router and anything else in-process.
engine = GatewayEngine()
