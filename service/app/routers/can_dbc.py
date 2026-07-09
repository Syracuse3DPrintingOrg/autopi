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
from ..services import dbc_catalog

router = APIRouter(prefix="/can", tags=["can-dbc"])


@router.get("/dbc/available")
def dbc_available():
    return {"available": dbc_mod.available()}


@router.get("/dbc/catalog")
def dbc_catalog_route():
    """A directory of open-source DBC sources: the permissive ones can be
    imported directly, the rest are links. Nothing here ships with the app."""
    return {"catalog": dbc_catalog.catalog()}


@router.get("/databases")
def list_databases():
    with session_scope() as s:
        return {"databases": [d.to_dict() for d in s.query(CanDatabase).all()]}


class NewDatabaseIn(BaseModel):
    name: str = ""
    make: str = ""
    model: str = ""
    models: str = ""
    year: int | None = None
    years: str = ""
    author: str = ""
    license: str = ""
    source: str = "custom"


@router.post("/databases")
def create_database(body: NewDatabaseIn):
    """Create an empty custom database to reverse-engineer signals into."""
    with session_scope() as s:
        d = CanDatabase(name=body.name or "Custom database", make=body.make, model=body.model,
                        models=body.models, year=body.year, years=body.years, author=body.author,
                        license=body.license, source=body.source or "custom", dbc_text="")
        s.add(d)
        s.flush()
        return {"ok": True, "database": d.to_dict()}


@router.get("/databases/for-vehicle")
def databases_for_vehicle(make: str = "", model: str = "", year: int | None = None):
    """Installed databases compatible with a vehicle's make/model/year, most
    specific first, so selecting a vehicle can offer the databases that fit it."""
    with session_scope() as s:
        dbs = [d.to_dict() for d in s.query(CanDatabase).all()]
    return {"databases": dbc_catalog.compatible_databases(dbs, make, model, year)}


class DatabaseMetaIn(BaseModel):
    name: str | None = None
    make: str | None = None
    model: str | None = None
    models: str | None = None
    year: int | None = None
    years: str | None = None
    author: str | None = None
    updated: str | None = None
    license: str | None = None
    source: str | None = None
    version: str | None = None
    notes: str | None = None


@router.patch("/databases/{database_id}")
def update_database_meta(database_id: int, body: DatabaseMetaIn):
    """Edit a database's metadata (make, model(s), years, author, license, ...)
    without re-importing it, so a vehicle can be matched to it."""
    with session_scope() as s:
        d = s.get(CanDatabase, database_id)
        if d is None:
            raise HTTPException(404, "No such CAN database")
        for key, value in body.model_dump(exclude_unset=True).items():
            setattr(d, key, value)
        s.flush()
        return {"ok": True, "database": d.to_dict()}


class ImportUrlIn(BaseModel):
    url: str
    name: str = ""
    make: str = ""
    model: str = ""
    models: str = ""
    year: int | None = None
    years: str = ""
    author: str = ""
    updated: str = ""
    license: str = ""
    source: str = ""


@router.post("/dbc/import-url")
def import_url(body: ImportUrlIn):
    """Fetch a raw .dbc from a URL and import it (used by the catalog's importable
    open-source entries, and for any DBC the user has a link to)."""
    if not dbc_mod.available():
        raise HTTPException(400, "cantools is not installed on this host")
    url = body.url.strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        raise HTTPException(400, "A http(s) URL to a .dbc file is required")
    try:
        import httpx
        resp = httpx.get(url, timeout=30.0, follow_redirects=True)
    except Exception as exc:
        return {"ok": False, "error": f"Could not fetch the URL: {exc}"}
    if resp.status_code >= 400:
        return {"ok": False, "error": f"The URL returned {resp.status_code}. Check the link or import the file by hand."}
    text = resp.text
    name = body.name or url.rsplit("/", 1)[-1].removesuffix(".dbc")
    try:
        with session_scope() as s:
            d = dbc_mod.import_dbc(
                s, name=name, dbc_text=text, source=body.source or url,
                license=body.license, make=body.make, model=body.model,
                models=body.models, year=body.year, years=body.years,
                author=body.author, updated=body.updated)
            s.flush()
            return {"ok": True, "database": d.to_dict()}
    except Exception as exc:
        return {"ok": False, "error": f"Could not parse the DBC: {exc}"}


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
    models: str = Form(""),
    year: int | None = Form(None),
    years: str = Form(""),
    author: str = Form(""),
    updated: str = Form(""),
):
    if not dbc_mod.available():
        raise HTTPException(400, "cantools is not installed on this host")
    text = (await file.read()).decode("utf-8", errors="replace")
    try:
        with session_scope() as s:
            d = dbc_mod.import_dbc(
                s, name=name or (file.filename or "database").removesuffix(".dbc"),
                dbc_text=text, source=source, license=license,
                make=make, model=model, models=models, year=year, years=years,
                author=author, updated=updated)
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


# --- live bus: interface status and a direct frame send --------------------
from ..can import Frame, get_channel  # noqa: E402

_DEFAULT_CHANNELS = ("can0", "can1")


@router.get("/interfaces")
def list_interfaces():
    """Report the default CAN channels and whether each is a real, open bus."""
    out = []
    for ch in _DEFAULT_CHANNELS:
        try:
            available = get_channel(ch).available
        except Exception:
            available = False
        out.append({"channel": ch, "available": available})
    return {"interfaces": out}


class SendIn(BaseModel):
    channel: str = "can0"
    arbitration_id: str            # hex or int string, e.g. "0x7DF"
    data: str = ""                 # hex bytes
    is_fd: bool = False
    is_extended_id: bool = False


@router.post("/send")
def send_frame(body: SendIn):
    """Send a single CAN frame on a channel (simulated when no hardware)."""
    from ..can import parse_arbitration_id, parse_data_bytes
    try:
        arb = parse_arbitration_id(body.arbitration_id)
        data = parse_data_bytes(body.data)
    except ValueError as exc:
        raise HTTPException(400, f"Invalid frame: {exc}")
    frame = Frame(arbitration_id=arb, data=data, is_fd=body.is_fd,
                  is_extended_id=body.is_extended_id)
    err = frame.validate()
    if err:
        raise HTTPException(400, err)
    channel = get_channel(body.channel)
    if not channel.available:
        return {"ok": True, "simulated": True,
                "message": f"(simulated) would send {frame.format()} on {body.channel}"}
    if channel.send(frame):
        return {"ok": True, "simulated": False,
                "message": f"Sent {frame.format()} on {body.channel}"}
    return {"ok": False, "message": f"Send failed on {body.channel}"}
