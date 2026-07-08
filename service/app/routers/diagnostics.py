"""Automotive diagnostics API: run a UDS request, read an OBD-II PID, or
read DTCs, over a CAN channel via ISO-TP.

A thin REST wrapper over :mod:`app.can.diagnostics`. Every endpoint returns
a decoded result even when udsoncan/isotp or the CAN hardware itself is
unavailable; in that case the result carries ``"simulated": true`` instead
of failing the request, so the diagnostics page always has something to
show.
"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from ..can.base import parse_arbitration_id
from ..can.diagnostics import (
    DEFAULT_REQUEST_ID,
    DEFAULT_RESPONSE_ID,
    OBD_FUNCTIONAL_ID,
    OBD_RESPONSE_ID,
    OBD_PIDS,
    ObdClient,
    UdsClient,
)

router = APIRouter(prefix="/diag", tags=["diagnostics"])


class ChannelIn(BaseModel):
    channel: str = "can0"
    backend: str = "socketcan"
    request_id: str = "0x7E0"
    response_id: str = "0x7E8"


def _ids(body: ChannelIn) -> tuple[int, int]:
    request_id = parse_arbitration_id(body.request_id) if body.request_id else DEFAULT_REQUEST_ID
    response_id = parse_arbitration_id(body.response_id) if body.response_id else DEFAULT_RESPONSE_ID
    return request_id, response_id


class SessionIn(ChannelIn):
    session: int = 0x03


class ReadDidIn(ChannelIn):
    did: str


class WriteDidIn(ChannelIn):
    did: str
    data: str = ""


class RoutineIn(ChannelIn):
    routine_id: str
    subfunction: int = 0x01
    data: str = ""


class DtcIn(ChannelIn):
    status_mask: str = "0xFF"


class ObdIn(BaseModel):
    channel: str = "can0"
    backend: str = "socketcan"
    request_id: str = "0x7DF"
    response_id: str = "0x7E8"
    pid: str


def _parse_hex(raw: str, default: int = 0) -> int:
    raw = (raw or "").strip()
    if not raw:
        return default
    return parse_arbitration_id(raw)


def _parse_data_hex(raw: str) -> list[int]:
    tokens = (raw or "").replace(",", " ").split()
    return [int(t, 16) for t in tokens]


@router.get("/pids")
def list_pids():
    """The mode-01 PIDs this build knows how to decode by name."""
    return {
        "pids": [
            {"pid": pid, "name": spec["name"], "unit": spec["unit"]}
            for pid, spec in sorted(OBD_PIDS.items())
        ]
    }


@router.get("/status")
def status(channel: str = "can0", backend: str = "socketcan"):
    uds = UdsClient(channel, backend=backend)
    obd = ObdClient(channel, backend=backend)
    return {
        "channel": channel,
        "backend": backend,
        "isotp_installed": uds.transport.module_importable(),
        "udsoncan_installed": uds.module_importable(),
        "uds_available": uds.available,
        "obd_available": obd.available,
    }


@router.post("/uds/session")
def uds_session(body: SessionIn):
    request_id, response_id = _ids(body)
    client = UdsClient(body.channel, backend=body.backend,
                        request_id=request_id, response_id=response_id)
    return client.diagnostic_session_control(body.session)


@router.post("/uds/tester-present")
def uds_tester_present(body: ChannelIn):
    request_id, response_id = _ids(body)
    client = UdsClient(body.channel, backend=body.backend,
                        request_id=request_id, response_id=response_id)
    return client.tester_present()


@router.post("/uds/read-did")
def uds_read_did(body: ReadDidIn):
    request_id, response_id = _ids(body)
    did = _parse_hex(body.did)
    client = UdsClient(body.channel, backend=body.backend,
                        request_id=request_id, response_id=response_id)
    return client.read_data_by_identifier(did)


@router.post("/uds/write-did")
def uds_write_did(body: WriteDidIn):
    request_id, response_id = _ids(body)
    did = _parse_hex(body.did)
    data = _parse_data_hex(body.data)
    client = UdsClient(body.channel, backend=body.backend,
                        request_id=request_id, response_id=response_id)
    return client.write_data_by_identifier(did, data)


@router.post("/uds/routine")
def uds_routine(body: RoutineIn):
    request_id, response_id = _ids(body)
    routine_id = _parse_hex(body.routine_id)
    data = _parse_data_hex(body.data)
    client = UdsClient(body.channel, backend=body.backend,
                        request_id=request_id, response_id=response_id)
    return client.routine_control(routine_id, body.subfunction, data or None)


@router.post("/uds/dtcs")
def uds_dtcs(body: DtcIn):
    request_id, response_id = _ids(body)
    status_mask = _parse_hex(body.status_mask, default=0xFF)
    client = UdsClient(body.channel, backend=body.backend,
                        request_id=request_id, response_id=response_id)
    return client.read_dtcs(status_mask)


@router.post("/obd/pid")
def obd_pid(body: ObdIn):
    request_id = _parse_hex(body.request_id, default=OBD_FUNCTIONAL_ID)
    response_id = _parse_hex(body.response_id, default=OBD_RESPONSE_ID)
    pid = _parse_hex(body.pid)
    client = ObdClient(body.channel, backend=body.backend,
                        request_id=request_id, response_id=response_id)
    return client.read_pid(pid)
