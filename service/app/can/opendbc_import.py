"""Bulk-import a directory of DBC files (built for comma.ai's opendbc).

opendbc (https://github.com/commaai/opendbc, MIT) is the largest open
collection of vehicle DBC files, one file per vehicle/bus. This walks a
directory of ``.dbc`` files and imports each as its own named CanDatabase,
guessing the make and year from the opendbc filename convention
(``<make>_<model>_<year>_<bus>.dbc``). Files that do not parse are skipped and
reported rather than aborting the whole import.

Fetch the files on a device with ``scripts/import-opendbc.sh``; this function
takes a local directory so it stays testable without any network.
"""
from __future__ import annotations

import os
import re
from typing import Any

from . import dbc

_YEAR_RE = re.compile(r"(19|20)\d{2}")


def guess_vehicle(filename: str) -> dict[str, Any]:
    """Guess make/model/year from an opendbc-style filename."""
    stem = os.path.splitext(os.path.basename(filename))[0]
    parts = stem.split("_")
    make = parts[0] if parts else ""
    year = None
    for p in parts:
        if _YEAR_RE.fullmatch(p):
            year = int(p)
            break
    model = parts[1] if len(parts) > 1 and not _YEAR_RE.fullmatch(parts[1]) else ""
    return {"make": make, "model": model, "year": year}


def import_directory(session, dbc_dir: str, *, source: str = "opendbc",
                     license: str = "MIT") -> dict[str, Any]:
    """Import every .dbc under ``dbc_dir``. Returns a summary with any errors."""
    if not dbc.available():
        return {"ok": False, "error": "cantools is not installed", "imported": 0, "failed": 0}
    if not os.path.isdir(dbc_dir):
        return {"ok": False, "error": f"not a directory: {dbc_dir}", "imported": 0, "failed": 0}

    imported = 0
    failed = 0
    errors: list[dict[str, str]] = []
    for root, _dirs, files in os.walk(dbc_dir):
        for fname in sorted(files):
            if not fname.endswith(".dbc"):
                continue
            path = os.path.join(root, fname)
            try:
                text = open(path, encoding="utf-8", errors="replace").read()
                v = guess_vehicle(fname)
                dbc.import_dbc(
                    session, name=os.path.splitext(fname)[0], dbc_text=text,
                    source=source, license=license, make=v["make"],
                    model=v["model"], year=v["year"],
                    notes=f"Imported from {source}",
                )
                imported += 1
            except Exception as exc:  # a single bad file must not abort the batch
                failed += 1
                if len(errors) < 50:
                    errors.append({"file": fname, "error": str(exc)[:200]})
    return {"ok": True, "imported": imported, "failed": failed, "errors": errors}
