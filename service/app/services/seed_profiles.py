"""Seed a couple of starter vehicle profiles on first run.

Mirrors ``services/seed.py``: seeding only happens when the profiles table is
empty, so it never overwrites a live install's saved vehicles. The two seed
profiles are Stellantis Uconnect 5 infotainment platforms (Atlantis High and
Atlantis Mid), useful starting points for building out infotainment CAN
actions and layouts without having to type in year/make/model by hand.
"""
from __future__ import annotations

from ..db import Profile, session_scope

_ATLANTIS_YEAR = 2024
_ATLANTIS_MAKE = "Stellantis"

_SEED_PROFILES = [
    {
        "name": "Atlantis High",
        "year": _ATLANTIS_YEAR,
        "make": _ATLANTIS_MAKE,
        "model": "Atlantis High",
        "vin": "",
        "config": {
            "can_interfaces": ["can0", "can1"],
            "can_database_ids": [],
            "vins": [],
            "tx_lists": [],
            "notes": (
                "Uconnect 5 infotainment platform, the higher trim head unit "
                "(larger display, extra infotainment domain traffic). Start "
                "here for the infotainment CAN bus; wire can0/can1 to the "
                "gateway before sending frames."
            ),
        },
    },
    {
        "name": "Atlantis Mid",
        "year": _ATLANTIS_YEAR,
        "make": _ATLANTIS_MAKE,
        "model": "Atlantis Mid",
        "vin": "",
        "config": {
            "can_interfaces": ["can0", "can1"],
            "can_database_ids": [],
            "vins": [],
            "tx_lists": [],
            "notes": (
                "Uconnect 5 infotainment platform, the mid trim head unit. "
                "Shares the Atlantis infotainment CAN layout with Atlantis "
                "High at a smaller display size; start here for the "
                "infotainment CAN bus."
            ),
        },
    },
]


def seed_profiles_if_empty() -> bool:
    """Seed the Atlantis High and Atlantis Mid profiles on a fresh install.

    Skips entirely if any profile already exists, so a configured device (or
    a device with the user's own vehicles saved) is never touched.
    """
    with session_scope() as s:
        if s.query(Profile).first() is not None:
            return False
        for spec in _SEED_PROFILES:
            s.add(Profile(**spec))
    return True
