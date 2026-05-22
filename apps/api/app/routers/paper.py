from __future__ import annotations

from fastapi import APIRouter, Query

from app.services.paper import (
    get_paper_trading_daily_history,
    get_paper_trading_holdings,
    get_paper_trading_history,
    get_paper_trading_orders,
    get_paper_trading_overview,
    get_paper_trading_performance,
    get_paper_trading_positions,
    get_paper_trading_status,
    get_paper_trading_targets,
)
from app.services.paper_db import (
    get_paper_db_daily_detail,
    get_paper_db_daily_history,
    get_paper_db_fills,
    get_paper_db_health,
    get_paper_db_holdings,
    get_paper_db_orders,
    get_paper_db_stock,
    get_paper_db_stock_ledger,
)

router = APIRouter(prefix="/api/paper", tags=["paper"])


@router.get("/status")
def paper_status() -> dict[str, object]:
    return get_paper_trading_status()


@router.get("/overview")
def paper_overview() -> dict[str, object]:
    return get_paper_trading_overview()


@router.get("/db/health")
def paper_db_health() -> dict[str, object]:
    return get_paper_db_health()


@router.get("/db/holdings")
def paper_db_holdings(
    position_limit: int = Query(default=500, ge=1, le=1000),
    order_limit: int = Query(default=200, ge=1, le=500),
) -> dict[str, object]:
    return get_paper_db_holdings(position_limit=position_limit, order_limit=order_limit)


@router.get("/db/daily-history")
def paper_db_daily_history(limit: int = Query(default=20, ge=1, le=120)) -> dict[str, object]:
    return get_paper_db_daily_history(limit=limit)


@router.get("/db/daily-history/{trade_date}")
def paper_db_daily_detail(trade_date: str) -> dict[str, object]:
    return get_paper_db_daily_detail(trade_date)


@router.get("/db/orders")
def paper_db_orders(
    symbol: str | None = Query(default=None),
    status: str | None = Query(default=None),
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
) -> dict[str, object]:
    return get_paper_db_orders(symbol=symbol, status=status, start_date=start_date, end_date=end_date, limit=limit)


@router.get("/db/fills")
def paper_db_fills(
    symbol: str | None = Query(default=None),
    side: str | None = Query(default=None),
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=2000),
) -> dict[str, object]:
    return get_paper_db_fills(symbol=symbol, side=side, start_date=start_date, end_date=end_date, limit=limit)


@router.get("/db/stocks/{symbol}")
def paper_db_stock(symbol: str) -> dict[str, object]:
    return get_paper_db_stock(symbol)


@router.get("/db/stocks/{symbol}/ledger")
def paper_db_stock_ledger(symbol: str, limit: int = Query(default=1000, ge=1, le=5000)) -> dict[str, object]:
    return get_paper_db_stock_ledger(symbol, limit=limit)


@router.get("/holdings")
def paper_holdings(
    position_limit: int = Query(default=500, ge=1, le=1000),
    order_limit: int = Query(default=200, ge=1, le=500),
) -> dict[str, object]:
    return get_paper_trading_holdings(position_limit=position_limit, order_limit=order_limit)


@router.get("/daily-history")
def paper_daily_history(limit: int = Query(default=20, ge=1, le=60)) -> dict[str, object]:
    return get_paper_trading_daily_history(limit=limit)


@router.get("/targets")
def paper_targets(limit: int = Query(default=25, ge=1, le=200)) -> dict[str, object]:
    return get_paper_trading_targets(limit=limit)


@router.get("/positions")
def paper_positions(limit: int = Query(default=50, ge=1, le=200)) -> dict[str, object]:
    return get_paper_trading_positions(limit=limit)


@router.get("/orders")
def paper_orders(limit: int = Query(default=50, ge=1, le=200)) -> dict[str, object]:
    return get_paper_trading_orders(limit=limit)


@router.get("/history")
def paper_history(limit: int = Query(default=50, ge=1, le=200)) -> dict[str, object]:
    return get_paper_trading_history(limit=limit)


@router.get("/performance")
def paper_performance(limit: int = Query(default=240, ge=1, le=500)) -> dict[str, object]:
    return get_paper_trading_performance(limit=limit)
