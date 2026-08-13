from __future__ import annotations

from fastapi import APIRouter

from app.services.model import get_lobster_picks, get_model_overview, get_latest_picks
from app.serializers import to_jsonable
from app.services.model_registry import get_active_deployment, list_activation_events, list_model_versions

router = APIRouter(prefix="/api/model", tags=["model"])


@router.get("/latest")
def model_latest(profile: str | None = None) -> dict[str, object]:
    return get_model_overview(profile_name=profile)


@router.get("/picks")
def model_picks(limit: int = 25, profile: str | None = None) -> dict[str, object]:
    return get_latest_picks(limit=limit, profile_name=profile)


@router.get("/lobster-picks")
def model_lobster_picks(limit: int = 100) -> dict[str, object]:
    return get_lobster_picks(limit=limit)


@router.get("/registry")
def model_registry(market: str = "CN") -> dict[str, object]:
    return to_jsonable({"market": market.upper(), "models": list_model_versions(market, sync=True)})


@router.get("/deployment")
def model_deployment(market: str = "CN") -> dict[str, object]:
    return to_jsonable({"deployment": get_active_deployment(market, sync=False)})


@router.get("/activation-events")
def model_activation_events(market: str = "CN", limit: int = 50) -> dict[str, object]:
    return to_jsonable({"market": market.upper(), "events": list_activation_events(market, limit=limit)})
