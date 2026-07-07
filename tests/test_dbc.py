"""Tests for DBC import, decode/encode, and the opendbc directory importer."""
import pytest

from app.can import dbc, opendbc_import
from app.db import CanDatabase, CanMessage, init_db, session_scope
from app.db.importexport import export_all, import_data

# A tiny valid DBC: one message with two signals.
SAMPLE_DBC = """VERSION ""

BU_: ECU TESTER

BO_ 256 EngineData: 8 ECU
 SG_ RPM : 0|16@1+ (0.25,0) [0|16383.75] "rpm" TESTER
 SG_ CoolantTemp : 16|8@1+ (1,-40) [-40|215] "degC" TESTER
"""

cantools_missing = not dbc.available()
skip_no_cantools = pytest.mark.skipif(cantools_missing, reason="cantools not installed")


@skip_no_cantools
def test_parse_dbc_reads_messages_and_signals():
    messages = dbc.parse_dbc(SAMPLE_DBC)
    assert len(messages) == 1
    msg = messages[0]
    assert msg["name"] == "EngineData"
    assert msg["arbitration_id"] == 256
    names = {s["name"] for s in msg["signals"]}
    assert names == {"RPM", "CoolantTemp"}
    rpm = next(s for s in msg["signals"] if s["name"] == "RPM")
    assert rpm["definition"]["scale"] == 0.25
    assert rpm["definition"]["length"] == 16


@skip_no_cantools
def test_import_dbc_stores_database_messages_and_signals():
    init_db()
    with session_scope() as s:
        d = dbc.import_dbc(s, name="sample", dbc_text=SAMPLE_DBC,
                           source="upload", license="MIT", make="test", year=2024)
        s.flush()
        db_id = d.id
    with session_scope() as s:
        d = s.get(CanDatabase, db_id)
        assert d.license == "MIT" and d.source == "upload"
        assert d.dbc_text  # kept for exact decode
        msgs = s.query(CanMessage).filter_by(database_id=db_id).all()
        assert len(msgs) == 1
        assert len(msgs[0].signals) == 2


@skip_no_cantools
def test_decode_and_encode_round_trip():
    # RPM 0.25 scale: raw 4000 -> 1000 rpm. Bytes little-endian: 4000 = 0x0FA0.
    data = dbc.encode(SAMPLE_DBC, "EngineData", {"RPM": 1000, "CoolantTemp": 0})
    decoded = dbc.decode(SAMPLE_DBC, 256, bytes(data))
    assert round(decoded["RPM"]) == 1000
    assert round(decoded["CoolantTemp"]) == 0


def test_available_reflects_cantools_import():
    assert dbc.available() == (not cantools_missing)


def test_guess_vehicle_from_opendbc_filename():
    v = opendbc_import.guess_vehicle("chrysler_pacifica_2017_powertrain.dbc")
    assert v["make"] == "chrysler"
    assert v["model"] == "pacifica"
    assert v["year"] == 2017


def test_guess_vehicle_without_year():
    v = opendbc_import.guess_vehicle("toyota_nodsu_pt_generated.dbc")
    assert v["make"] == "toyota"
    assert v["year"] is None


@skip_no_cantools
def test_import_directory_loads_dbc_files(tmp_path):
    (tmp_path / "honda_civic_2016_can.dbc").write_text(SAMPLE_DBC)
    (tmp_path / "notes.txt").write_text("ignore me")
    init_db()
    with session_scope() as s:
        summary = opendbc_import.import_directory(s, str(tmp_path))
    assert summary["ok"] and summary["imported"] == 1 and summary["failed"] == 0
    with session_scope() as s:
        d = s.query(CanDatabase).filter_by(make="honda").one()
        assert d.year == 2016 and d.license == "MIT" and d.source == "opendbc"


def test_import_directory_missing_dir_is_reported():
    with session_scope() as s:
        summary = opendbc_import.import_directory(s, "/no/such/dir")
    assert summary["ok"] is False


@skip_no_cantools
def test_export_import_round_trips_a_database():
    init_db()
    with session_scope() as s:
        dbc.import_dbc(s, name="rt", dbc_text=SAMPLE_DBC, source="upload", license="MIT")
    with session_scope() as s:
        dump = export_all(s)
    assert dump["can_databases"] and dump["can_databases"][0]["dbc_text"]
    # Re-importing the dump upserts without error and keeps the database.
    with session_scope() as s:
        counts = import_data(s, dump)
    assert counts["can_databases"] >= 1
