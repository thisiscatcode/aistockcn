"""Shared conservative execution assumptions for paper trading and backtests."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any


REALISTIC_BACKTEST_METHOD_VERSION = "realistic_execution_v1"


@dataclass(frozen=True)
class ExecutionModel:
    name: str = "conservative_v1"
    trade_start_time: str = "09:35"
    buy_limit_bps: float = 100.0
    sell_limit_bps: float = 100.0
    backtest_slippage_bps: float = 50.0
    min_buy_amount: float = 20_000_000.0
    max_order_participation_rate: float = 0.005
    price_limit_buffer_bps: float = 50.0


DEFAULT_EXECUTION_MODEL = ExecutionModel()


def execution_model_with_limit_bps(
    *,
    buy_limit_bps: float | None = None,
    sell_limit_bps: float | None = None,
    base: ExecutionModel = DEFAULT_EXECUTION_MODEL,
) -> ExecutionModel:
    return replace(
        base,
        buy_limit_bps=max(float(buy_limit_bps), 0.0) if buy_limit_bps is not None else base.buy_limit_bps,
        sell_limit_bps=max(float(sell_limit_bps), 0.0) if sell_limit_bps is not None else base.sell_limit_bps,
    )


def execution_model_snapshot(model: ExecutionModel = DEFAULT_EXECUTION_MODEL) -> dict[str, float | str]:
    return asdict(model)


def to_float(value: Any, default: float = 0.0) -> float:
    if value in (None, "", "N/A"):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number


def normalize_symbol(value: Any) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return digits[-6:].zfill(6) if digits else ""


def is_st_name(name: Any) -> bool:
    normalized = str(name or "").upper().replace(" ", "")
    return "ST" in normalized


def board_price_limit_rate(symbol: Any, name: Any = None) -> float:
    code = normalize_symbol(symbol)
    if is_st_name(name):
        return 0.05
    if code.startswith(("300", "301", "688", "689")):
        return 0.20
    if code.startswith(("4", "8", "9")):
        return 0.30
    return 0.10


def previous_close_from_row(row: dict[str, Any]) -> float:
    close = to_float(row.get("close"))
    change = to_float(row.get("change"), default=float("nan"))
    if close > 0 and change == change:
        previous_close = close - change
        if previous_close > 0:
            return previous_close
    pct_chg = to_float(row.get("pct_chg"), default=float("nan"))
    if close > 0 and pct_chg == pct_chg and abs(1.0 + pct_chg / 100.0) > 1e-9:
        previous_close = close / (1.0 + pct_chg / 100.0)
        if previous_close > 0:
            return previous_close
    return 0.0


def marketable_limit_price(latest_price: float, side: str, model: ExecutionModel = DEFAULT_EXECUTION_MODEL) -> float:
    price = max(float(latest_price), 0.0)
    if price <= 0:
        return 0.0
    normalized_side = str(side or "").upper()
    bps = model.buy_limit_bps if normalized_side == "BUY" else model.sell_limit_bps
    multiplier = 1.0 + bps / 10_000.0 if normalized_side == "BUY" else 1.0 - bps / 10_000.0
    return round(price * multiplier, 2)


def slippage_price(base_price: float, side: str, model: ExecutionModel = DEFAULT_EXECUTION_MODEL) -> float:
    price = max(float(base_price), 0.0)
    if price <= 0:
        return 0.0
    multiplier = 1.0 + model.backtest_slippage_bps / 10_000.0 if str(side or "").upper() == "BUY" else 1.0 - model.backtest_slippage_bps / 10_000.0
    return round(price * multiplier, 2)


def liquidity_cap_notional(amount: Any, model: ExecutionModel = DEFAULT_EXECUTION_MODEL) -> float:
    return max(to_float(amount), 0.0) * max(float(model.max_order_participation_rate), 0.0)


def near_price_limit(
    *,
    side: str,
    price: float,
    previous_close: float,
    symbol: Any,
    name: Any = None,
    model: ExecutionModel = DEFAULT_EXECUTION_MODEL,
) -> bool:
    reference = max(float(previous_close), 0.0)
    observed = max(float(price), 0.0)
    if reference <= 0 or observed <= 0:
        return False
    limit_rate = board_price_limit_rate(symbol, name)
    buffer_rate = max(float(model.price_limit_buffer_bps), 0.0) / 10_000.0
    if str(side or "").upper() == "BUY":
        return observed >= reference * (1.0 + max(limit_rate - buffer_rate, 0.0))
    return observed <= reference * (1.0 - max(limit_rate - buffer_rate, 0.0))


def buy_liquidity_skip_reason(
    *,
    amount: Any,
    order_notional: float,
    model: ExecutionModel = DEFAULT_EXECUTION_MODEL,
) -> str | None:
    daily_amount = max(to_float(amount), 0.0)
    notional = max(float(order_notional), 0.0)
    if daily_amount <= 0:
        return "SKIP_NO_REFERENCE_DATA"
    if daily_amount < model.min_buy_amount:
        return "SKIP_LOW_LIQUIDITY"
    if notional > liquidity_cap_notional(daily_amount, model):
        return "SKIP_LIQUIDITY_CAP"
    return None
