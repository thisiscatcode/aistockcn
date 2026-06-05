from __future__ import annotations

from fastapi import APIRouter, Query

from app.services.pre_explosion import get_pre_explosion_watchlist

router = APIRouter(prefix="/api/pre-explosion", tags=["pre-explosion"])


@router.get("")
def pre_explosion(limit: int = Query(default=500, ge=1, le=2000)) -> dict[str, object]:
    return get_pre_explosion_watchlist(limit=limit)
