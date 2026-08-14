from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.services.market_capabilities import MarketCapabilityError, get_market_capabilities


router = APIRouter(prefix="/api/markets", tags=["markets"])


@router.get("/{market}/capabilities")
def market_capabilities(market: str) -> dict[str, object]:
    try:
        return get_market_capabilities(market)
    except MarketCapabilityError as exc:
        raise HTTPException(status_code=404, detail={"code": str(exc)}) from exc
