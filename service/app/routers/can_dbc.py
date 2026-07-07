"""CAN database (DBC) import, listing, and decode/encode.

Import open-source DBC libraries (opendbc and any DBC file), then decode raw
frames into named signals or encode signal values into frames. Each imported
database records its source and license so open-source content stays
attributable (see LICENSING.md).
"""
from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from ..can import dbc as dbc_mod
from ..can import opendbc_import
from ..db import CanDatabase, session_scope

router = APIRouter(prefix="/can", tags=["can-dbc"])


@router.get("/dbc/available")
def dbc_available():
    return {"available": dbc_mod.available()}


@router.get("/databases")
def list_databases():
    with session_scope() as s:
        return {"databases": [d.to_dict() for d in s.query(CanDatabase).all()]}


@router.get("/databases/{database_id}")
def get_database(database_id: int):
    with session_scope() as s:
        d = s.get(CanDatabase, database_id)
        if d is None:
            raise HTTPException(404, "No such CAN database")
        return d.to_dict(with_messages=True)


@router.delete("/databases/{database_id}")
def delete_database(database_id: int):
    with session_scope() as s:
        d = s.get(CanDatabase, database_id)
        if d is None:
            raise HTTPException(404, "No such CAN database")
        s.delete(d)  # cascades to messages and their signals
    return {"ok": True}


@router.post("/dbc/import")
async def import_dbc(
    file: UploadFile = File(...),
    name: str = Form(""),
    source: str = Form("upload"),
    license: str = Form(""),
    make: str = Form(""),
    model: str = Form(""),
    year: int | None = Form(None),
):
    if not dbc_mod.available():
        raise HTTPException(400, "cantools is not installed on this host")
    text = (await file.read()).decode("utf-8", errors="replace")
    try:
        with session_scope() as s:
            d = dbc_mod.import_dbc(
                s, name=name or (file.filename or "database").removesuffix(".dbc"),
                dbc_text=text, source=source, license=license,
                make=make, model=model, year=year)
            s.flush()
            return {"ok": True, "database": d.to_dict()}
    except Exception as exc:
        raise HTTPException(400, f"Could not parse DBC: {exc}")


class ImportDirIn(BaseModel):
    path: str
    source: str = "opendbc"
    license: str = "MIT"


@router.post("/dbc/import-directory")
def import_directory(body: ImportDirIn):
    """Bulk-import a directory of DBC files already on the device (opendbc)."""
    with session_scope() as s:
        return opendbc_import.import_directory(
            s, body.path, source=body.source, license=body.license)


class DecodeIn(BaseModel):
    database_id: int
    arbitration_id: int
    data: str  # hex bytes, e.g. "02 01 0C" or "02010C"


class EncodeIn(BaseModel):
    database_id: int
    message: str | int
    signals: dict


def _hex_to_bytes(text: str) -> bytes:
    cleaned = text.replace(",", " ").replace("0x", " ").split()
    if len(cleaned) == 1 and len(cleaned[0]) % 2 == 0:
        return bytes.fromhex(cleaned[0])
    return bytes(int(b, 16) for b in cleaned)


@router.post("/decode")
def decode(body: DecodeIn):
    with session_scope() as s:
        d = s.get(CanDatabase, body.database_id)
        if d is None or not d.dbc_text:
            raise HTTPException(404, "No DBC text for that database")
    try:
        values = dbc_mod.decode(d.dbc_text, body.arbitration_id, _hex_to_bytes(body.data))
        return {"ok": True, "signals": values}
    except Exception as exc:
        raise HTTPException(400, f"Decode failed: {exc}")


@router.post("/encode")
def encode(body: EncodeIn):
    with session_scope() as s:
        d = s.get(CanDatabase, body.database_id)
        if d is None or not d.dbc_text:
            raise HTTPException(404, "No DBC text for that database")
    try:
        data = dbc_mod.encode(d.dbc_text, body.message, body.signals)
        return {"ok": True, "data": data, "hex": " ".join(f"{b:02X}" for b in data)}
    except Exception as exc:
        raise HTTPException(400, f"Encode failed: {exc}")
