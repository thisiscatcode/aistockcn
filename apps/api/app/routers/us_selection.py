from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Query

from app.config import get_settings
from app.services.us_selection import UsSelectionError, get_us_selection, get_us_stock_detail, save_us_favorite_stocks

router = APIRouter(prefix="/api/fei-selection-us", tags=["fei-selection-us"])


def _require_admin_key(x_panel_admin_key: str | None = Header(default=None)) -> None:
    expected = get_settings().panel_admin_key
    if not expected or x_panel_admin_key != expected:
        raise HTTPException(status_code=403, detail={"code": "forbidden", "message": "Admin control key rejected."})


@router.get("")
def us_selection(limit: int = Query(default=6000, ge=1, le=10000)) -> dict[str, object]:
    return get_us_selection(limit=limit)


@router.get("/stocks/{code}")
def us_selection_stock_detail(
    code: str,
    limit: int = Query(default=260, ge=1, le=1000),
) -> dict[str, object]:
    return get_us_stock_detail(code=code, limit=limit)


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
