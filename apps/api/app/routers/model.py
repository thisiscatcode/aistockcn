from __future__ import annotations

from fastapi import APIRouter

from app.services.model import get_model_overview, get_latest_picks

router = APIRouter(prefix="/api/model", tags=["model"])


@router.get("/latest")
def model_latest(profile: str | None = None) -> dict[str, object]:
    return get_model_overview(profile_name=profile)


@router.get("/picks")
def model_picks(limit: int = 25, profile: str | None = None) -> dict[str, object]:
    return get_latest_picks(limit=limit, profile_name=profile)
