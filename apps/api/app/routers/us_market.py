from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.services.us_market import (
    UsMarketError,
    get_us_market_session,
    get_us_market_summary,
    get_us_model_status,
    get_us_overview,
    get_us_paper_status,
    get_us_picks,
    get_us_pipeline_status,
    get_us_stock,
    list_us_stocks,
)

router = APIRouter(prefix="/api/us", tags=["us-market"])


def _not_found_or_bad_request(exc: UsMarketError) -> HTTPException:
    code = str(exc)
    return HTTPException(status_code=404 if code == "stock_not_found" else 400, detail={"code": code})


@router.get("/overview")
def overview() -> dict[str, object]:
    return get_us_overview()


@router.get("/session")
def session() -> dict[str, object]:
    return get_us_market_session()


@router.get("/data/summary")
def data_summary() -> dict[str, object]:
    return get_us_market_summary()


@router.get("/data/stocks")
def stocks(
    search: str = Query(default="", max_length=80),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, object]:
    return list_us_stocks(search=search, limit=limit, offset=offset)


@router.get("/data/stocks/{symbol}")
def stock(symbol: str, history_limit: int = Query(default=260, ge=1, le=1000)) -> dict[str, object]:
    try:
        return get_us_stock(symbol=symbol, history_limit=history_limit)
    except UsMarketError as exc:
        raise _not_found_or_bad_request(exc) from exc


@router.get("/models")
def models() -> dict[str, object]:
    return get_us_model_status()


@router.get("/picks")
def picks(
    limit: int = Query(default=25, ge=1, le=100),
    list_type: str = Query(default="cat", pattern="^(cat|lobster)$"),
) -> dict[str, object]:
    try:
        return get_us_picks(limit=limit, list_type=list_type)
    except UsMarketError as exc:
        raise _not_found_or_bad_request(exc) from exc


@router.get("/paper/status")
def paper_status() -> dict[str, object]:
    return get_us_paper_status()


@router.get("/status")
def status() -> dict[str, object]:
    return get_us_pipeline_status()


@router.get("/pipeline/status")
def pipeline_status() -> dict[str, object]:
    return get_us_pipeline_status()
