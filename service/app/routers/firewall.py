"""CAN firewall/gateway API: rule CRUD, gateway start/stop/status, and the
inhale (capture) / exhale (replay) endpoints.

A thin REST wrapper over :mod:`app.can.firewall` (rule set and forwarding
engine) and :mod:`app.can.capture` (named frame buffers and replay).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..can import capture as cap
from ..can import firewall as fw

router = APIRouter(prefix="/firewall", tags=["firewall"])


def _resolve_dbc_text(database_id: int) -> str | None:
    from ..db import session_scope
    from ..db.models import CanDatabase
    with session_scope() as s:
        database = s.get(CanDatabase, database_id)
        if database is None:
            raise HTTPException(404, "No such CAN database")
        return database.dbc_text


def _dbc_lookup(database_id: int) -> str | None:
    """Same as :func:`_resolve_dbc_text` but never raises: a rule referencing
    a database that was later deleted should just fail its signal match
    instead of taking the gateway down."""
    from ..db import session_scope
    from ..db.models import CanDatabase
    with session_scope() as s:
        database = s.get(CanDatabase, database_id)
        return database.dbc_text if database else None


# -- gateway configuration and control ---------------------------------------

class ConfigIn(BaseModel):
    channel_a: str | None = None
    backend_a: str | None = None
    channel_b: str | None = None
    backend_b: str | None = None
    forward_a_to_b: bool | None = None
    forward_b_to_a: bool | None = None


@router.get("/config")
def get_config():
    return fw.get_config()


@router.put("/config")
def update_config(body: ConfigIn):
    data = {k: v for k, v in body.model_dump().items() if v is not None}
    return fw.update_config(data)


@router.post("/start")
def start_gateway():
    ok, error = fw.engine.start()
    if not ok and error and "already running" not in error:
        raise HTTPException(400, error)
    return {"ok": ok, "error": error, "status": fw.engine.status()}


@router.post("/stop")
def stop_gateway():
    stopped = fw.engine.stop()
    return {"ok": True, "stopped": stopped}


@router.get("/status")
def gateway_status():
    return fw.engine.status()


# -- rule CRUD ------------------------------------------------------------

class MatchIn(BaseModel):
    arbitration_id: int | None = None
    mask: int | None = None
    id_min: int | None = None
    id_max: int | None = None
    database_id: int | None = None
    signal: str | None = None
    op: str = "eq"
    value: float | str | None = None


class RewriteIn(BaseModel):
    data: str | None = None
    database_id: int | None = None
    message: str | int | None = None
    signals: dict = Field(default_factory=dict)
    checksum: str = ""


class InjectIn(BaseModel):
    arbitration_id: str | int | None = None
    data: str = ""
    database_id: int | None = None
    message: str | int | None = None
    signals: dict = Field(default_factory=dict)
    checksum: str = ""
    is_fd: bool = False
    is_extended_id: bool = False


class RuleIn(BaseModel):
    name: str = ""
    enabled: bool = True
    direction: str = "both"  # "a_to_b" | "b_to_a" | "both"
    action: str = "allow"    # "allow" | "block" | "rewrite" | "inject"
    match: MatchIn = Field(default_factory=MatchIn)
    rewrite: RewriteIn = Field(default_factory=RewriteIn)
    inject: InjectIn = Field(default_factory=InjectIn)


def _validate_rule(rule: dict) -> None:
    if rule.get("direction") not in ("a_to_b", "b_to_a", "both"):
        raise HTTPException(400, "direction must be a_to_b, b_to_a, or both")
    if rule.get("action") not in ("allow", "block", "rewrite", "inject"):
        raise HTTPException(400, "action must be allow, block, rewrite, or inject")
    database_id = (rule.get("match") or {}).get("database_id")
    if database_id:
        _resolve_dbc_text(database_id)  # raises 404 if missing
    if rule.get("action") == "rewrite":
        rewrite_db = (rule.get("rewrite") or {}).get("database_id")
        if rewrite_db:
            _resolve_dbc_text(rewrite_db)
    if rule.get("action") == "inject":
        inject_db = (rule.get("inject") or {}).get("database_id")
        if inject_db:
            _resolve_dbc_text(inject_db)


@router.get("/rules")
def list_rules():
    return {"rules": fw.list_rules()}


@router.get("/rules/{rule_id}")
def get_rule(rule_id: str):
    rule = fw.get_rule(rule_id)
    if rule is None:
        raise HTTPException(404, "No such rule")
    return rule


@router.post("/rules")
def create_rule(body: RuleIn):
    rule = body.model_dump()
    _validate_rule(rule)
    created = fw.create_rule(rule)
    return {"ok": True, "rule": created}


@router.put("/rules/{rule_id}")
def update_rule(rule_id: str, body: RuleIn):
    if fw.get_rule(rule_id) is None:
        raise HTTPException(404, "No such rule")
    rule = body.model_dump()
    _validate_rule(rule)
    updated = fw.update_rule(rule_id, rule)
    return {"ok": True, "rule": updated}


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: str):
    if not fw.delete_rule(rule_id):
        raise HTTPException(404, "No such rule")
    return {"ok": True}


class ReorderIn(BaseModel):
    rule_ids: list[str]


@router.post("/rules/reorder")
def reorder_rules(body: ReorderIn):
    return {"rules": fw.reorder_rules(body.rule_ids)}


# -- inhale (capture) -------------------------------------------------------

class InhaleStartIn(BaseModel):
    name: str = ""
    channel: str = "can0"
    backend: str = "socketcan"
    max_frames: int | None = Field(None, ge=1)
    max_duration_s: float | None = Field(None, gt=0)


@router.post("/inhale/start")
def start_inhale(body: InhaleStartIn):
    session = cap.get_inhale_session(body.channel, backend=body.backend)
    started = session.start(body.name, max_frames=body.max_frames, max_duration_s=body.max_duration_s)
    return {"ok": True, "started": started, "status": session.status()}


@router.post("/inhale/stop")
def stop_inhale(channel: str = "can0", backend: str = "socketcan"):
    session = cap.get_inhale_session(channel, backend=backend)
    saved = session.stop()
    if saved is None:
        raise HTTPException(400, "No inhale capture is running on that channel")
    return {"ok": True, "capture": {k: v for k, v in saved.items() if k != "frames"}}


@router.get("/inhale/status")
def inhale_status(channel: str = "can0", backend: str = "socketcan"):
    return cap.get_inhale_session(channel, backend=backend).status()


# -- captures ---------------------------------------------------------------

@router.get("/captures")
def list_captures():
    return {"captures": cap.list_captures()}


@router.get("/captures/{capture_id}")
def get_capture(capture_id: str):
    capture = cap.get_capture(capture_id)
    if capture is None:
        raise HTTPException(404, "No such capture")
    return capture


@router.delete("/captures/{capture_id}")
def delete_capture(capture_id: str):
    if not cap.delete_capture(capture_id):
        raise HTTPException(404, "No such capture")
    return {"ok": True}


# -- exhale (replay) ---------------------------------------------------------

class ExhaleStartIn(BaseModel):
    channel: str = "can0"
    backend: str = "socketcan"
    speed: float = Field(1.0, gt=0)
    use_rules: bool = False


@router.post("/captures/{capture_id}/exhale")
def start_exhale(capture_id: str, body: ExhaleStartIn):
    capture = cap.get_capture(capture_id)
    if capture is None:
        raise HTTPException(404, "No such capture")
    rules = fw.list_rules() if body.use_rules else None
    started = cap.exhale.start(
        capture, body.channel, body.backend,
        rules=rules, dbc_lookup=_dbc_lookup, speed=body.speed,
    )
    if not started:
        raise HTTPException(400, "A replay is already running")
    return {"ok": True, "status": cap.exhale.status()}


@router.post("/exhale/stop")
def stop_exhale():
    stopped = cap.exhale.stop()
    return {"ok": True, "stopped": stopped}


@router.get("/exhale/status")
def exhale_status():
    return cap.exhale.status()
