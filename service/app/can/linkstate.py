"""Pure parsing of ``ip -details -json link show`` output for a CAN channel.

Kept independent of the host-bridge relay and any hardware access so the
parsing and health classification are unit-testable without root, a real
CAN adapter, or the bridge running. The host-bridge runs the ``ip`` command
(it needs the host's network namespace) and hands back the parsed JSON; this
module turns that into the shape the CAN interfaces page and the bus health
check use.
"""
from __future__ import annotations

from typing import Any

# States python-can/SocketCAN report for a CAN controller. ERROR-ACTIVE is
# the normal operating state; ERROR-WARNING and ERROR-PASSIVE mean the
# controller is seeing bus errors but is still transmitting; BUS-OFF means it
# has given up after too many errors and needs a restart (bring the
# interface down and back up).
HEALTHY_STATES = {"ERROR-ACTIVE"}
WARNING_STATES = {"ERROR-WARNING", "ERROR-PASSIVE"}
ERROR_STATES = {"BUS-OFF"}


def parse_link_show(raw: Any) -> dict:
    """Normalize one ``ip -details -json link show canX`` entry.

    ``raw`` is whatever ``json.loads`` produced: normally a one-element list
    (``ip -json`` always wraps its output in an array), but a bare dict is
    accepted too. Returns a dict with ``name``, ``up``, ``state``,
    ``bitrate``, ``data_bitrate``, ``restart_ms``, ``rx_errors``,
    ``tx_errors``; any field ``ip`` did not report comes back as ``None``.
    An empty or unrecognized ``raw`` returns an empty dict.
    """
    if isinstance(raw, list):
        raw = raw[0] if raw else {}
    if not isinstance(raw, dict):
        return {}
    if not raw:
        return {}
    flags = raw.get("flags") or []
    linkinfo = raw.get("linkinfo") or {}
    info_data = linkinfo.get("info_data") or {}
    if not isinstance(info_data, dict):
        info_data = {}
    bittiming = info_data.get("bittiming") or {}
    data_bittiming = info_data.get("data_bittiming") or {}
    berr = info_data.get("berr_counter") or {}
    return {
        "name": raw.get("ifname"),
        "up": "UP" in flags,
        "state": info_data.get("state"),
        "bitrate": bittiming.get("bitrate"),
        "data_bitrate": data_bittiming.get("bitrate"),
        "restart_ms": info_data.get("restart_ms"),
        "rx_errors": berr.get("rx"),
        "tx_errors": berr.get("tx"),
    }


def classify_health(link: dict) -> dict:
    """Turn a parsed link dict (see ``parse_link_show``) into a pass/fail
    health read for the UI: ``status`` is one of ``ok``, ``warning``,
    ``error``, ``down``, or ``unknown``, with a plain-language ``message``.
    """
    if not link or link.get("name") is None:
        return {"status": "unknown", "message": "No status available for this interface."}
    state = (link.get("state") or "").upper()
    up = bool(link.get("up"))
    rx = link.get("rx_errors") or 0
    tx = link.get("tx_errors") or 0
    if not up:
        return {"status": "down", "message": "Interface is down."}
    if state in ERROR_STATES:
        return {"status": "error",
                "message": "Bus is off. It stopped transmitting after too many errors; "
                           "check wiring and termination, then bring the interface down and back up."}
    if state in WARNING_STATES or rx > 0 or tx > 0:
        return {"status": "warning",
                "message": f"Bus is reporting errors (rx={rx}, tx={tx}). Check wiring and termination."}
    if state in HEALTHY_STATES or (up and not state):
        return {"status": "ok", "message": "Bus is up with no errors."}
    return {"status": "unknown", "message": f"Unrecognized bus state: {state}."}
