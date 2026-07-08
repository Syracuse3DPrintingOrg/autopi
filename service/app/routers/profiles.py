"""Vehicle test profiles: CRUD plus which one is active.

A profile is the saved shape of a vehicle under test: year, make, model, one
or more VINs, and a config blob (CAN interfaces, linked CAN databases, and
any transmit lists a caller wants to keep with the vehicle). See
``services/profiles.py`` for the storage details.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..services import profiles as profiles_svc

router = APIRouter(prefix="/profiles", tags=["profiles"])


class ProfileIn(BaseModel):
    name: str = ""
    year: int | None = None
    make: str = ""
    model: str = ""
    vin: str = ""
    vins: list[str] | None = None
    config: dict = {}


class ProfileUpdateIn(BaseModel):
    name: str | None = None
    year: int | None = None
    make: str | None = None
    model: str | None = None
    vin: str | None = None
    vins: list[str] | None = None
    config: dict | None = None


class ActiveIn(BaseModel):
    profile_id: int | None = None


@router.get("")
def list_profiles():
    return {"profiles": profiles_svc.list_profiles(), "active_id": profiles_svc.get_active_profile_id()}


@router.get("/active")
def active_profile():
    active_id = profiles_svc.get_active_profile_id()
    profile = profiles_svc.get_profile(active_id) if active_id is not None else None
    return {"active_id": active_id, "profile": profile}


@router.get("/{profile_id}")
def get_profile(profile_id: int):
    profile = profiles_svc.get_profile(profile_id)
    if profile is None:
        raise HTTPException(404, "No such profile")
    return profile


@router.post("")
def create_profile(body: ProfileIn):
    return profiles_svc.create_profile(
        name=body.name, year=body.year, make=body.make, model=body.model,
        vin=body.vin, config=body.config, vins=body.vins)


@router.put("/{profile_id}")
def update_profile(profile_id: int, body: ProfileUpdateIn):
    updated = profiles_svc.update_profile(profile_id, **body.model_dump(exclude_unset=True))
    if updated is None:
        raise HTTPException(404, "No such profile")
    return updated


@router.delete("/{profile_id}")
def delete_profile(profile_id: int):
    if not profiles_svc.delete_profile(profile_id):
        raise HTTPException(404, "No such profile")
    return {"ok": True}


@router.post("/active")
def set_active_profile(body: ActiveIn):
    try:
        profile = profiles_svc.set_active_profile(body.profile_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    return {"active_id": body.profile_id, "profile": profile}
