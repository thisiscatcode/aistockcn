from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Query

from app.config import get_settings
from app.services.benchmark import get_benchmark_history_status, refresh_benchmark_history
from app.services.overview import get_portfolio_overview

router = APIRouter(prefix="/api/overview", tags=["overview"])


def _require_admin_key(x_panel_admin_key: str | None = Header(default=None)) -> None:
    expected = get_settings().panel_admin_key
    if not expected or x_panel_admin_key != expected:
        raise HTTPException(status_code=403, detail={"code": "forbidden", "message": "Admin control key rejected."})


@router.get("/portfolio")
def portfolio_overview() -> dict[str, object]:
    return get_portfolio_overview()


@router.get("/benchmark")
def benchmark_status() -> dict[str, object]:
    return get_benchmark_history_status()


@router.post("/benchmark/refresh")
def benchmark_refresh(
    start_date: str | None = Query(default=None, description="Optional start date, YYYYMMDD or YYYY-MM-DD."),
    end_date: str | None = Query(default=None, description="Optional end date, YYYYMMDD or YYYY-MM-DD."),
    overwrite: bool = Query(default=False),
    x_panel_admin_key: str | None = Header(default=None),
) -> dict[str, object]:
    _require_admin_key(x_panel_admin_key)
    try:
        return refresh_benchmark_history(start_date=start_date, end_date=end_date, overwrite=overwrite)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
