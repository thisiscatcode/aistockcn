from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa

from app.config import get_settings
from app.serializers import records_to_json, to_jsonable
from app.services.benchmark import BENCHMARK_CODE, BENCHMARK_NAME, benchmark_history_path
from app.services.model import get_latest_picks
from app.services.paper import (
    get_paper_trading_overview,
    get_paper_trading_performance,
    get_paper_trading_targets,
)


def _as_record(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float) and pd.notna(value):
        return float(value)
    if isinstance(value, str):
        try:
            parsed = float(value.strip())
        except ValueError:
            return None
        return parsed if pd.notna(parsed) else None
    return None


def _first_number(*values: Any) -> float | None:
    for value in values:
        numeric = _as_number(value)
        if numeric is not None:
            return numeric
    return None


def _currency(value: Any, fallback: Any = None) -> str:
    raw = str(value or fallback or "").strip().upper()
    if raw in {"", "N/A", "NA", "NONE", "NULL", "CN"}:
        return "CNY"
    return raw


def _safe_read_parquet(path: Path, columns: list[str] | None = None) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_parquet(path, columns=columns)
    except (pa.ArrowException, OSError, ValueError):
        return pd.DataFrame()


def _latest_date(rows: list[dict[str, Any]], key: str) -> str | None:
    dates = pd.to_datetime([row.get(key) for row in rows], errors="coerce")
    if dates.dropna().empty:
        return None
    return pd.Timestamp(dates.max()).date().isoformat()


def _signal_type(row: dict[str, Any]) -> str:
    raw_action = str(row.get("action") or row.get("signal_type") or "").strip().upper()
    buy_qty = _as_number(row.get("buy_order_qty"))
    sell_qty = _as_number(row.get("sell_order_qty"))
    delta_qty = _as_number(row.get("delta_qty"))

    if raw_action.startswith("SKIP"):
        return "SKIP"
    if "BUY" in raw_action or (buy_qty is not None and buy_qty > 0) or (delta_qty is not None and delta_qty > 0):
        return "BUY"
    if "SELL" in raw_action or (sell_qty is not None and sell_qty > 0) or (delta_qty is not None and delta_qty < 0):
        return "SELL"
    if raw_action:
        return raw_action
    return "HOLD"


def _recommended_weight(row: dict[str, Any], total_assets: float | None) -> float | None:
    direct_weight = _first_number(row.get("target_weight"), row.get("recommended_weight"), row.get("weight"))
    if direct_weight is not None:
        return direct_weight

    notional = _as_number(row.get("estimated_order_notional"))
    if notional is not None and total_assets and total_assets > 0:
        return notional / total_assets
    return None


def _top_pick_rows(target_rows: list[dict[str, Any]], pick_rows: list[dict[str, Any]], total_assets: float | None) -> list[dict[str, Any]]:
    source_rows = target_rows if target_rows else pick_rows
    rows: list[dict[str, Any]] = []
    for index, row in enumerate(source_rows[:10], start=1):
        rows.append(
            {
                "rank": row.get("rank") or index,
                "code": row.get("code") or row.get("symbol"),
                "name": row.get("name") or row.get("company"),
                "industry": row.get("industry"),
                "signal_type": _signal_type(row),
                "confidence": row.get("score"),
                "recommended_weight": _recommended_weight(row, total_assets),
                "target_qty": row.get("target_qty"),
                "estimated_order_notional": row.get("estimated_order_notional"),
                "reason": row.get("reason"),
                "source": "paper_target" if target_rows else "model_pick",
            }
        )
    return records_to_json(rows)


def _pending_counts(target_rows: list[dict[str, Any]]) -> tuple[int, int]:
    pending_buy = 0
    pending_sell = 0
    for row in target_rows:
        signal_type = _signal_type(row)
        if signal_type == "BUY":
            pending_buy += 1
        elif signal_type == "SELL":
            pending_sell += 1
    return pending_buy, pending_sell


def _history_equity(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for row in rows:
        total_assets = _as_number(row.get("total_assets"))
        recorded_at = row.get("recorded_at")
        if total_assets is None or not recorded_at:
            continue
        points.append({"date": to_jsonable(recorded_at), "total_assets": total_assets})
    return points


def _today_pnl(points: list[dict[str, Any]], current_total_assets: float | None) -> tuple[float | None, float | None]:
    if not points or current_total_assets is None:
        return None, None

    latest_date = pd.Timestamp(points[-1]["date"]).date()
    previous_candidates = [
        point for point in points if pd.Timestamp(point["date"]).date() < latest_date and _as_number(point.get("total_assets")) is not None
    ]
    if not previous_candidates:
        return None, None

    previous_assets = _as_number(previous_candidates[-1]["total_assets"])
    if previous_assets is None:
        return None, None
    pnl = current_total_assets - previous_assets
    pnl_pct = pnl / previous_assets if previous_assets else None
    return pnl, pnl_pct


def _benchmark_candidates() -> list[Path]:
    settings = get_settings()
    return [
        benchmark_history_path(),
        settings.quant_dir / "indexes" / f"{BENCHMARK_CODE}.parquet",
        settings.quant_dir / "benchmark" / f"{BENCHMARK_CODE}.parquet",
        settings.quant_dir / "benchmarks" / f"{BENCHMARK_CODE}.parquet",
        settings.quant_dir / "daily_kline" / f"{BENCHMARK_CODE}.parquet",
        settings.quant_dir / "daily_kline" / "000300.parquet",
    ]


def _benchmark_by_date(warnings: list[str]) -> dict[str, float]:
    for path in _benchmark_candidates():
        frame = _safe_read_parquet(path)
        if frame.empty:
            continue
        date_column = "date" if "date" in frame.columns else "trade_date" if "trade_date" in frame.columns else None
        price_column = "close" if "close" in frame.columns else "close_price" if "close_price" in frame.columns else None
        if not date_column or not price_column:
            continue
        frame = frame[[date_column, price_column]].copy()
        frame[date_column] = pd.to_datetime(frame[date_column], errors="coerce").dt.date.astype("string")
        frame[price_column] = pd.to_numeric(frame[price_column], errors="coerce")
        frame = frame.dropna(subset=[date_column, price_column])
        if frame.empty:
            continue
        frame = frame.sort_values(date_column)
        first_price = float(frame[price_column].iloc[0])
        if first_price == 0:
            continue
        return {
            str(row[date_column]): float(row[price_column]) / first_price * 100
            for _, row in frame.iterrows()
        }

    warnings.append(f"Benchmark history is unavailable for {BENCHMARK_CODE}.")
    return {}


def _performance_points(history_points: list[dict[str, Any]], warnings: list[str]) -> list[dict[str, Any]]:
    if not history_points:
        warnings.append("Portfolio performance history is unavailable.")
        return []

    first_assets = _as_number(history_points[0].get("total_assets"))
    if not first_assets:
        warnings.append("Portfolio performance history has no valid starting account equity.")
        return []

    benchmark = _benchmark_by_date(warnings)
    points: list[dict[str, Any]] = []
    for point in history_points:
        total_assets = _as_number(point.get("total_assets"))
        date_value = point.get("date")
        if total_assets is None or not date_value:
            continue
        date_key = pd.Timestamp(date_value).date().isoformat()
        points.append(
            {
                "date": date_key,
                "portfolio_value": total_assets / first_assets * 100,
                "benchmark_value": benchmark.get(date_key),
                "account_equity": total_assets,
            }
        )
    return records_to_json(points)


def get_portfolio_overview() -> dict[str, Any]:
    warnings: list[str] = []
    generated_at = datetime.now(tz=UTC).isoformat()

    paper_overview = get_paper_trading_overview()
    performance = get_paper_trading_performance(limit=500)
    targets = get_paper_trading_targets(limit=200)
    picks = get_latest_picks(limit=200)

    live_summary = _as_record(paper_overview.get("live_summary"))
    gateway = _as_record(paper_overview.get("gateway"))
    state = _as_record(paper_overview.get("state"))
    balance_metrics = _as_record(state.get("balance_metrics"))
    plan_summary = _as_record(state.get("plan_summary"))
    snapshots = performance.get("snapshots") if isinstance(performance.get("snapshots"), list) else []
    history_points = _history_equity(snapshots)
    latest_history = history_points[-1] if history_points else {}

    total_assets = _first_number(
        balance_metrics.get("total_assets"),
        latest_history.get("total_assets"),
        live_summary.get("market_value"),
    )
    cash = _as_number(balance_metrics.get("cash"))
    market_value = _first_number(live_summary.get("market_value"), plan_summary.get("current_market_value"))
    total_pnl = _first_number(live_summary.get("total_pnl"), _as_record(snapshots[-1] if snapshots else {}).get("total_pnl"))
    today_pnl, today_pnl_pct = _today_pnl(history_points, total_assets)
    if today_pnl is None:
        warnings.append("today_pnl is unavailable because no previous trading-day account snapshot was found.")

    target_rows = targets.get("targets") if isinstance(targets.get("targets"), list) else []
    pick_rows = picks.get("picks") if isinstance(picks.get("picks"), list) else []
    pending_buy_count, pending_sell_count = _pending_counts(target_rows)
    latest_target_date = _latest_date(target_rows, "signal_date")
    latest_pick_date = picks.get("latest_date")
    latest_signal_date = latest_target_date or latest_pick_date
    new_signals_today = sum(1 for row in pick_rows if row.get("signal_date") == latest_pick_date) if latest_pick_date else 0

    live_error = paper_overview.get("live_error")
    if live_error:
        warnings.append(f"Paper account live snapshot warning: {live_error}")

    return {
        "generated_at": generated_at,
        "account": {
            "currency": _currency(balance_metrics.get("currency"), gateway.get("market")),
            "total_assets": total_assets,
            "cash": cash,
            "market_value": market_value,
            "total_pnl": total_pnl,
            "today_pnl": today_pnl,
            "today_pnl_pct": today_pnl_pct,
            "updated_at": latest_history.get("date") or state.get("last_success_at") or state.get("last_attempt_at"),
        },
        "positions": {
            "holding_count": paper_overview.get("live_positions_count"),
            "pending_buy_count": pending_buy_count,
            "pending_sell_count": pending_sell_count,
            "open_order_count": paper_overview.get("live_orders_count"),
        },
        "signals": {
            "latest_signal_date": latest_signal_date,
            "new_signals_today": new_signals_today,
            "pending_actions": pending_buy_count + pending_sell_count,
        },
        "performance": {
            "benchmark": {
                "code": BENCHMARK_CODE,
                "name": BENCHMARK_NAME,
            },
            "points": _performance_points(history_points, warnings),
        },
        "top_picks": _top_pick_rows(target_rows, pick_rows, total_assets),
        "warnings": warnings,
    }
