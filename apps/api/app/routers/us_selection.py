from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Query

from app.config import get_settings
from app.services.us_selection import (
    UsSelectionError,
    get_us_selection,
    get_us_stock_detail,
    get_us_stock_signal_visualizer,
    save_us_favorite_stocks,
)
from app.services.us_selection_snapshots import (
    get_snapshot_coverage,
    get_snapshot_dates,
    get_snapshot_scheduler_status,
    get_snapshot_selection,
    refresh_snapshot,
)

router = APIRouter(prefix="/api/fei-selection-us", tags=["fei-selection-us"])


def _require_admin_key(x_panel_admin_key: str | None = Header(default=None)) -> None:
    expected = get_settings().panel_admin_key
    if not expected or x_panel_admin_key != expected:
        raise HTTPException(status_code=403, detail={"code": "forbidden", "message": "Admin control key rejected."})


@router.get("")
def us_selection(
    limit: int = Query(default=6000, ge=1, le=10000),
    date: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
) -> dict[str, object]:
    if date:
        return get_snapshot_selection(trade_date=date)
    return get_us_selection(limit=limit, date=date)


@router.get("/snapshot-dates")
def us_selection_snapshot_dates(limit: int = Query(default=260, ge=1, le=1000)) -> dict[str, object]:
    return get_snapshot_dates(limit=limit)


@router.get("/snapshots/status")
def us_selection_snapshot_status() -> dict[str, object]:
    return get_snapshot_scheduler_status()


@router.get("/snapshots/coverage")
def us_selection_snapshot_coverage(limit: int = Query(default=60, ge=1, le=1000)) -> dict[str, object]:
    return get_snapshot_coverage(limit=limit)


@router.post("/snapshots/refresh")
def us_selection_snapshot_refresh(
    date: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    x_panel_admin_key: str | None = Header(default=None),
) -> dict[str, object]:
    _require_admin_key(x_panel_admin_key)
    try:
        return refresh_snapshot(trade_date=date)
    except UsSelectionError as exc:
        raise HTTPException(status_code=400, detail={"code": str(exc), "message": str(exc)}) from exc


@router.get("/stocks/{code}")
def us_selection_stock_detail(
    code: str,
    limit: int = Query(default=260, ge=1, le=1000),
) -> dict[str, object]:
    return get_us_stock_detail(code=code, limit=limit)


@router.get("/stocks/{code}/signal-visualizer")
def us_selection_stock_signal_visualizer(
    code: str,
    limit: int = Query(default=63, ge=1, le=1000),
) -> dict[str, object]:
    return get_us_stock_signal_visualizer(code=code, limit=limit)


@router.put("/favorites")
def us_selection_favorites(
    payload: dict[str, object],
    x_panel_admin_key: str | None = Header(default=None),
) -> dict[str, object]:
    _require_admin_key(x_panel_admin_key)
    try:
        return save_us_favorite_stocks(payload)
    except UsSelectionError as exc:
        raise HTTPException(status_code=400, detail={"code": str(exc), "message": str(exc)}) from exc
