from __future__ import annotations

import json
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import pandas as pd

from app.config import Settings, get_settings
from app.serializers import records_to_json, to_jsonable
from app.services.paper import _enrich_position_metadata, _stock_name_lookup

try:
    import psycopg
    from psycopg.rows import dict_row
except Exception:  # pragma: no cover - exercised only when optional dependency is missing
    psycopg = None
    dict_row = None


class PaperDbError(RuntimeError):
    pass


def _normalize_symbol(value: Any) -> str:
    text = str(value or "").strip().upper()
    if not text:
        return ""
    if "." in text:
        parts = [part for part in text.split(".") if part]
        for part in parts:
            if part.isdigit():
                return part.zfill(6)
        return parts[-1]
    return text.zfill(6) if text.isdigit() else text


def _display_symbol(symbol: Any, market: Any = "CN") -> str:
    normalized = _normalize_symbol(symbol)
    if not normalized:
        return ""
    if str(market or "").upper() == "CN":
        exchange = "SH" if normalized.startswith(("5", "6", "9")) else "SZ"
        return f"{normalized}.{exchange}"
    return normalized


def _num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _stock_meta(symbol: Any, settings: Settings) -> dict[str, str]:
    normalized = _normalize_symbol(symbol)
    if not normalized:
        return {}
    return _stock_name_lookup(settings).get(normalized, {})


def _enrich_symbol_rows(rows: list[dict[str, Any]], settings: Settings) -> list[dict[str, Any]]:
    lookup = _stock_name_lookup(settings)
    enriched: list[dict[str, Any]] = []
    for row in rows:
        symbol = _normalize_symbol(row.get("symbol") or row.get("code"))
        meta = lookup.get(symbol, {})
        enriched.append(
            {
                **row,
                "symbol": symbol or row.get("symbol"),
                "display_symbol": meta.get("display_symbol") or row.get("display_symbol") or _display_symbol(symbol, row.get("market") or settings.futu_gateway_market),
                "name": row.get("name") or row.get("stock_name") or meta.get("name") or None,
                "exchange": row.get("exchange") or meta.get("exchange") or row.get("market"),
            }
        )
    return enriched


def _deep_jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _deep_jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_deep_jsonable(item) for item in value]
    return to_jsonable(value)


def _diluted_cost(avg_cost: Any, realized_pnl: Any, quantity: Any) -> float | None:
    qty = _num(quantity)
    if qty == 0:
        return None
    return _num(avg_cost) - (_num(realized_pnl) / qty)


def _pnl_pct(pnl: Any, denominator: Any) -> float | None:
    base = abs(_num(denominator))
    if base == 0:
        return None
    return (_num(pnl) / base) * 100


@contextmanager
def _connect(settings: Settings | None = None) -> Iterator[Any]:
    resolved = settings or get_settings()
    if not resolved.paper_db_url:
        raise PaperDbError("PAPER_DB_URL is not configured")
    if psycopg is None or dict_row is None:
        raise PaperDbError("psycopg is not installed")
    with psycopg.connect(
        resolved.paper_db_url,
        row_factory=dict_row,
        connect_timeout=5,
        options="-c default_transaction_read_only=on",
    ) as conn:
        yield conn


def _date_filters(
    column: str,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
) -> tuple[list[str], list[Any]]:
    filters: list[str] = []
    params: list[Any] = []
    if start_date:
        filters.append(f"{column} >= %s")
        params.append(start_date)
    if end_date:
        if len(end_date.strip()) == 10:
            filters.append(f"{column} < (%s::timestamp + interval '1 day')")
        else:
            filters.append(f"{column} <= %s")
        params.append(end_date)
    return filters, params


def _query_rows(conn: Any, sql: str, params: list[Any]) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return [dict(row) for row in cur.fetchall()]


def get_paper_db_health() -> dict[str, Any]:
    settings = get_settings()
    try:
        with _connect(settings) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select
                      (select count(*) from agent_fills where agent_id = %s and market = %s) as fills,
                      (select count(*) from agent_order_snapshots where agent_id = %s and market = %s) as orders,
                      (select count(*) from agent_positions where agent_id = %s and market = %s) as positions
                    """,
                    [
                        settings.futu_gateway_agent_id,
                        settings.futu_gateway_market,
                        settings.futu_gateway_agent_id,
                        settings.futu_gateway_market,
                        settings.futu_gateway_agent_id,
                        settings.futu_gateway_market,
                    ],
                )
                row = dict(cur.fetchone() or {})
        return {"healthy": True, "error": None, **records_to_json([row])[0]}
    except Exception as exc:
        return {"healthy": False, "error": str(exc), "fills": 0, "orders": 0, "positions": 0}


def _position_rows(conn: Any, settings: Settings, *, include_closed: bool = False) -> list[dict[str, Any]]:
    where = ["agent_id = %s", "market = %s"]
    params: list[Any] = [settings.futu_gateway_agent_id, settings.futu_gateway_market]
    if not include_closed:
        where.append("quantity > 0")
    rows = _query_rows(
        conn,
        f"""
        select
          symbol, market, quantity, avg_cost, realized_pnl, last_price, market_value,
          unrealized_pnl, created_at, updated_at
        from agent_positions
        where {" and ".join(where)}
        order by market_value desc, symbol asc
        """,
        params,
    )
    for row in rows:
        row["display_symbol"] = _display_symbol(row.get("symbol"), row.get("market"))
        row["diluted_cost"] = _diluted_cost(row.get("avg_cost"), row.get("realized_pnl"), row.get("quantity"))
        row["total_pnl"] = _num(row.get("realized_pnl")) + _num(row.get("unrealized_pnl"))
        row["today_pnl"] = 0.0
        row["today_pnl_pct"] = 0.0
    return _enrich_position_metadata(rows, settings)


def get_paper_db_orders(
    *,
    symbol: str | None = None,
    status: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    settings = get_settings()
    try:
        with _connect(settings) as conn:
            where = ["agent_id = %s", "market = %s"]
            params: list[Any] = [settings.futu_gateway_agent_id, settings.futu_gateway_market]
            normalized_symbol = _normalize_symbol(symbol)
            if normalized_symbol:
                where.append("symbol = %s")
                params.append(normalized_symbol)
            if status:
                where.append("upper(order_status) = %s")
                params.append(status.strip().upper())
            filters, filter_params = _date_filters("created_at", start_date=start_date, end_date=end_date)
            where.extend(filters)
            params.extend(filter_params)
            params.append(limit)
            rows = _query_rows(
                conn,
                f"""
                select
                  broker_order_id, account_id, market, symbol, side, order_type, order_status,
                  quantity, price, dealt_qty, dealt_avg_price, remark, created_at, updated_at
                from agent_order_snapshots
                where {" and ".join(where)}
                order by updated_at desc, created_at desc
                limit %s
                """,
                params,
            )
        rows = _enrich_symbol_rows(rows, settings)
        return {"rows": len(rows), "orders": records_to_json(rows), "error": None}
    except Exception as exc:
        return {"rows": 0, "orders": [], "error": str(exc)}


def get_paper_db_fills(
    *,
    symbol: str | None = None,
    side: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 500,
) -> dict[str, Any]:
    settings = get_settings()
    try:
        with _connect(settings) as conn:
            rows = _fills(conn, settings, symbol=symbol, side=side, start_date=start_date, end_date=end_date, limit=limit)
        rows = _enrich_symbol_rows(rows, settings)
        return {"rows": len(rows), "fills": records_to_json(rows), "error": None}
    except Exception as exc:
        return {"rows": 0, "fills": [], "error": str(exc)}


def _fills(
    conn: Any,
    settings: Settings,
    *,
    symbol: str | None = None,
    side: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int | None = None,
    ascending: bool = False,
) -> list[dict[str, Any]]:
    where = ["agent_id = %s", "market = %s"]
    params: list[Any] = [settings.futu_gateway_agent_id, settings.futu_gateway_market]
    normalized_symbol = _normalize_symbol(symbol)
    if normalized_symbol:
        where.append("symbol = %s")
        params.append(normalized_symbol)
    if side:
        where.append("upper(side) = %s")
        params.append(side.strip().upper())
    filters, filter_params = _date_filters("created_at", start_date=start_date, end_date=end_date)
    where.extend(filters)
    params.extend(filter_params)
    direction = "asc" if ascending else "desc"
    limit_sql = ""
    if limit is not None:
        limit_sql = "limit %s"
        params.append(limit)
    return _query_rows(
        conn,
        f"""
        select
          created_at, broker_order_id, fill_key, market, symbol, side, quantity,
          price, notional
        from agent_fills
        where {" and ".join(where)}
        order by created_at {direction}, id {direction}
        {limit_sql}
        """,
        params,
    )


def build_symbol_ledger(fills: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    quantity = 0.0
    cost_basis = 0.0
    cumulative_realized = 0.0
    ledger: list[dict[str, Any]] = []
    daily: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "trade_date": "",
            "buy_qty": 0.0,
            "sell_qty": 0.0,
            "buy_notional": 0.0,
            "sell_notional": 0.0,
            "realized_pnl": 0.0,
            "fills": 0,
        }
    )

    for fill in fills:
        side = str(fill.get("side") or "").upper()
        fill_qty = _num(fill.get("quantity"))
        price = _num(fill.get("price"))
        notional = _num(fill.get("notional")) or fill_qty * price
        avg_before = cost_basis / quantity if quantity else 0.0
        realized = 0.0

        if side == "BUY":
            quantity += fill_qty
            cost_basis += notional
        elif side == "SELL":
            matched_qty = min(quantity, fill_qty)
            realized = (price - avg_before) * matched_qty
            cumulative_realized += realized
            quantity -= matched_qty
            cost_basis -= avg_before * matched_qty
            if quantity <= 1e-9:
                quantity = 0.0
                cost_basis = 0.0

        avg_after = cost_basis / quantity if quantity else 0.0
        created_at = fill.get("created_at")
        trade_date = str(created_at.date() if hasattr(created_at, "date") else str(created_at)[:10])
        day = daily[trade_date]
        day["trade_date"] = trade_date
        day["fills"] += 1
        if side == "BUY":
            day["buy_qty"] += fill_qty
            day["buy_notional"] += notional
        elif side == "SELL":
            day["sell_qty"] += fill_qty
            day["sell_notional"] += notional
            day["realized_pnl"] += realized

        ledger.append(
            {
                **fill,
                "avg_cost_before": avg_before,
                "realized_pnl": realized,
                "cumulative_realized_pnl": cumulative_realized,
                "position_quantity_after": quantity,
                "avg_cost_after": avg_after,
                "cost_basis_after": cost_basis,
            }
        )

    daily_rows = sorted(daily.values(), key=lambda row: str(row.get("trade_date") or ""), reverse=True)
    return ledger, daily_rows


def _safe_jsonl_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                text = line.strip()
                if not text:
                    continue
                try:
                    value = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict):
                    rows.append(value)
    except OSError:
        return []
    return rows


def _date_key(value: Any) -> str:
    if value in (None, "", "NaT"):
        return ""
    try:
        parsed = pd.to_datetime(value, errors="coerce")
    except (TypeError, ValueError):
        return str(value)[:10]
    if pd.isna(parsed):
        return str(value)[:10]
    return str(pd.Timestamp(parsed).date())


def _symbol_orders(row: dict[str, Any], symbol: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    placed = [order for order in row.get("placed_orders") or [] if _normalize_symbol(order.get("symbol")) == symbol]
    skipped = [order for order in row.get("skipped_orders") or [] if _normalize_symbol(order.get("symbol")) == symbol]
    cancelled = [order for order in row.get("cancelled_orders") or [] if _normalize_symbol(order.get("symbol")) == symbol]
    return placed, skipped, cancelled


def _target_snapshot_by_symbol(row: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = row.get("target_snapshot")
    if not isinstance(rows, list):
        return {}
    by_symbol: dict[str, dict[str, Any]] = {}
    for item in rows:
        if not isinstance(item, dict):
            continue
        symbol = _normalize_symbol(item.get("code") or item.get("symbol"))
        if symbol and symbol not in by_symbol:
            by_symbol[symbol] = item
    return by_symbol


def _format_metric(value: Any, *, percent: bool = False) -> str | None:
    number = _num(value)
    if number == 0 and value in (None, "", "NaN"):
        return None
    if percent:
        return f"{number * 100:.2f}%"
    return f"{number:.4g}"


def _snapshot_reason(snapshot: dict[str, Any], plan: dict[str, Any], rank: int | None) -> str:
    parts = [
        f"Included in paper target snapshot at rank {rank or snapshot.get('rank')} for {plan.get('profile_label') or plan.get('profile_name') or 'active model'}."
    ]
    score = _format_metric(snapshot.get("score"))
    close = _format_metric(snapshot.get("close"))
    if score:
        parts.append(f"Model score {score}.")
    if close:
        parts.append(f"Signal close {close}.")
    metric_bits: list[str] = []
    for key, label, percent in [
        ("bias_20", "20D bias", True),
        ("pct_chg_5d", "5D change", True),
        ("pct_chg_20d", "20D change", True),
        ("close_to_high_20d", "distance to 20D high", True),
        ("close_to_low_20d", "distance from 20D low", True),
        ("turnover", "turnover", False),
        ("turnover_ma5", "5D turnover avg", False),
        ("amount", "amount", False),
        ("pe_ttm", "PE TTM", False),
        ("pb", "PB", False),
    ]:
        formatted = _format_metric(snapshot.get(key), percent=percent)
        if formatted:
            metric_bits.append(f"{label} {formatted}")
    if metric_bits:
        parts.append("Key stored features: " + "; ".join(metric_bits[:8]) + ".")
    action = str(snapshot.get("action") or "").strip()
    if action:
        parts.append(f"Planner action {action}.")
    return " ".join(parts)


def _signal_snapshots(settings: Settings) -> list[dict[str, Any]]:
    by_signal_date: dict[str, dict[str, Any]] = {}
    for row in _safe_jsonl_rows(settings.paper_trading_history_path):
        signal_date = _date_key(row.get("score_signal_date"))
        plan = row.get("plan_summary") if isinstance(row.get("plan_summary"), dict) else None
        if not signal_date or not plan:
            continue
        current = by_signal_date.get(signal_date)
        if current is None:
            by_signal_date[signal_date] = row
            continue
        current_orders = len(current.get("placed_orders") or []) + len(current.get("skipped_orders") or [])
        row_orders = len(row.get("placed_orders") or []) + len(row.get("skipped_orders") or [])
        current_success = str(current.get("status") or "").lower() == "success"
        row_success = str(row.get("status") or "").lower() == "success"
        if (row_success and not current_success) or (row_success == current_success and row_orders > current_orders):
            by_signal_date[signal_date] = row
    return [by_signal_date[key] for key in sorted(by_signal_date)]


def _signal_snapshots_from_db(settings: Settings) -> list[dict[str, Any]]:
    with _connect(settings) as conn:
        rows = _query_rows(
            conn,
            """
            with latest_runs as (
              select
                r.*,
                row_number() over (
                  partition by r.agent_id, r.market, r.score_signal_date
                  order by r.recorded_at desc, r.id desc
                ) as rn
              from paper_rebalance_runs r
              where r.agent_id = %s
                and r.market = %s
                and r.score_signal_date is not null
            )
            select
              r.id,
              r.score_signal_date::text as score_signal_date,
              r.recorded_at,
              r.status,
              r.message,
              r.plan_summary,
              r.placed_orders,
              r.skipped_orders,
              r.cancelled_orders,
              coalesce(
                jsonb_agg(
                  jsonb_build_object(
                    'signal_date', t.score_signal_date::text,
                    'rank', t.rank,
                    'code', t.code,
                    'exchange', t.exchange,
                    'name', t.name,
                    'industry', t.industry,
                    'score', t.score,
                    'open', t.open,
                    'close', t.close,
                    'amount', t.amount,
                    'pct_chg', t.pct_chg,
                    'pct_chg_5d', t.pct_chg_5d,
                    'pct_chg_20d', t.pct_chg_20d,
                    'turnover', t.turnover,
                    'turnover_ma5', t.turnover_ma5,
                    'volume_ma5', t.volume_ma5,
                    'volatility_20d', t.volatility_20d,
                    'bias_20', t.bias_20,
                    'close_to_high_20d', t.close_to_high_20d,
                    'close_to_low_20d', t.close_to_low_20d,
                    'float_market_cap', t.float_market_cap,
                    'pe_ttm', t.pe_ttm,
                    'pb', t.pb,
                    'target_weight', t.target_weight,
                    'target_qty', t.target_qty,
                    'current_qty', t.current_qty,
                    'delta_qty', t.delta_qty,
                    'buy_order_qty', t.buy_order_qty,
                    'sell_order_qty', t.sell_order_qty,
                    'action', t.action,
                    'reason', t.reason,
                    'estimated_order_notional', t.estimated_order_notional,
                    'estimated_order_fee', t.estimated_order_fee,
                    'sent_order_id', t.sent_order_id,
                    'sent_status', t.sent_status,
                    'sent_price', t.sent_price,
                    'sent_error', t.sent_error
                  )
                  order by t.rank nulls last, t.score desc nulls last, t.code
                ) filter (where t.id is not null),
                '[]'::jsonb
              ) as target_snapshot
            from latest_runs r
            left join paper_rebalance_targets t on t.run_id = r.id
            where r.rn = 1
            group by
              r.id, r.score_signal_date, r.recorded_at, r.status, r.message,
              r.plan_summary, r.placed_orders, r.skipped_orders, r.cancelled_orders
            order by r.score_signal_date asc, r.recorded_at asc
            """,
            [settings.futu_gateway_agent_id, settings.futu_gateway_market],
        )
    return records_to_json(rows)


def _selection_signal_snapshots(settings: Settings) -> tuple[list[dict[str, Any]], str, str | None]:
    try:
        snapshots = _signal_snapshots_from_db(settings)
        if snapshots:
            return snapshots, "postgres", None
    except Exception as exc:
        fallback = _signal_snapshots(settings)
        return fallback, "jsonl_fallback", str(exc)
    return _signal_snapshots(settings), "jsonl_fallback", None


def _latest_score_row(symbol: str, settings: Settings) -> dict[str, Any] | None:
    path = settings.models_dir / "inference_scores_latest.parquet"
    if not path.exists():
        return None
    try:
        frame = pd.read_parquet(path)
    except Exception:
        return None
    if frame.empty or "code" not in frame.columns:
        return None
    frame = frame.copy()
    frame["code"] = frame["code"].astype(str).str.zfill(6)
    rows = frame[frame["code"].eq(symbol)]
    if rows.empty:
        return None
    row = rows.sort_values("date").tail(1).to_dict(orient="records")[0]
    return records_to_json([row])[0]


def get_paper_db_stock_selection_history(symbol: str) -> dict[str, Any]:
    settings = get_settings()
    normalized_symbol = _normalize_symbol(symbol)
    meta = _stock_meta(normalized_symbol, settings)
    snapshots, source, source_error = _selection_signal_snapshots(settings)
    latest_score = _latest_score_row(normalized_symbol, settings)
    events: list[dict[str, Any]] = []
    previous_on_list = False
    streak = 0
    last_rank: int | None = None
    last_listed_date: str | None = None

    for row in snapshots:
        signal_date = _date_key(row.get("score_signal_date"))
        plan = row.get("plan_summary") if isinstance(row.get("plan_summary"), dict) else {}
        snapshot_by_symbol = _target_snapshot_by_symbol(row)
        symbol_snapshot = snapshot_by_symbol.get(normalized_symbol)
        targets = [_normalize_symbol(item) for item in plan.get("target_symbols") or []]
        on_list = normalized_symbol in targets
        rank = int(_num(symbol_snapshot.get("rank"))) if symbol_snapshot and _num(symbol_snapshot.get("rank")) > 0 else targets.index(normalized_symbol) + 1 if on_list else None
        placed, skipped, cancelled = _symbol_orders(row, normalized_symbol)
        orders = placed + skipped + cancelled
        order_sides = sorted({str(order.get("side") or "").upper() for order in orders if str(order.get("side") or "").strip()})

        if on_list:
            streak = streak + 1 if previous_on_list else 1
            event_type = "STILL_LISTED" if previous_on_list else "LISTED"
            if symbol_snapshot:
                reason = _snapshot_reason(symbol_snapshot, plan, rank)
            else:
                reason = (
                    f"Included in paper target_symbols at rank {rank} for "
                    f"{plan.get('profile_label') or plan.get('profile_name') or 'active model'}."
                )
            if not symbol_snapshot and latest_score and _date_key(latest_score.get("date")) == signal_date:
                reason += f" Latest stored score {latest_score.get('score')} at close {latest_score.get('close')}."
            elif not symbol_snapshot and "score" not in row:
                reason += " Historical per-feature model reasons were not persisted for this date."
            events.append(
                {
                    "signal_date": signal_date,
                    "recorded_at": row.get("recorded_at"),
                    "event": event_type,
                    "event_label": "首次/重新上榜" if event_type == "LISTED" else "連續上榜",
                    "status": "ON_LIST",
                    "rank": rank,
                    "previous_rank": last_rank,
                    "streak": streak,
                    "target_count": plan.get("target_count"),
                    "profile_name": plan.get("profile_name"),
                    "profile_label": plan.get("profile_label"),
                    "rebalance_due": plan.get("rebalance_due"),
                    "buy_order_count": plan.get("buy_order_count"),
                    "sell_order_count": plan.get("sell_order_count"),
                    "order_sides": order_sides,
                    "placed_orders": records_to_json(placed),
                    "skipped_orders": records_to_json(skipped),
                    "target_snapshot": records_to_json([symbol_snapshot])[0] if symbol_snapshot else None,
                    "score": (symbol_snapshot or {}).get("score"),
                    "close": (symbol_snapshot or {}).get("close"),
                    "bias_20": (symbol_snapshot or {}).get("bias_20"),
                    "pct_chg_5d": (symbol_snapshot or {}).get("pct_chg_5d"),
                    "pct_chg_20d": (symbol_snapshot or {}).get("pct_chg_20d"),
                    "reason": reason,
                    "target_symbols": targets,
                }
            )
            last_rank = rank
            last_listed_date = signal_date
        elif previous_on_list:
            streak = 0
            reason = "Dropped because this signal date's paper target_symbols no longer included the stock."
            if order_sides:
                reason += f" Related paper order side(s): {', '.join(order_sides)}."
            else:
                reason += " No symbol-specific order was recorded in sync history for the drop event."
            events.append(
                {
                    "signal_date": signal_date,
                    "recorded_at": row.get("recorded_at"),
                    "event": "DROPPED",
                    "event_label": "下榜",
                    "status": "OFF_LIST",
                    "rank": None,
                    "previous_rank": last_rank,
                    "streak": 0,
                    "last_listed_date": last_listed_date,
                    "target_count": plan.get("target_count"),
                    "profile_name": plan.get("profile_name"),
                    "profile_label": plan.get("profile_label"),
                    "rebalance_due": plan.get("rebalance_due"),
                    "buy_order_count": plan.get("buy_order_count"),
                    "sell_order_count": plan.get("sell_order_count"),
                    "order_sides": order_sides,
                    "placed_orders": records_to_json(placed),
                    "skipped_orders": records_to_json(skipped),
                    "target_snapshot": None,
                    "reason": reason,
                    "target_symbols": targets,
                }
            )
            last_rank = None

        previous_on_list = on_list

    latest_event = events[-1] if events else None
    return {
        "symbol": normalized_symbol,
        "display_symbol": meta.get("display_symbol") or _display_symbol(normalized_symbol, settings.futu_gateway_market),
        "name": meta.get("name") or None,
        "rows": len(events),
        "latest_event": latest_event,
        "events": records_to_json(list(reversed(events))),
        "latest_score": latest_score,
        "source": source,
        "source_error": source_error,
        "error": None,
    }


def _trade_date(fill: dict[str, Any]) -> str:
    created_at = fill.get("created_at")
    return str(created_at.date() if hasattr(created_at, "date") else str(created_at)[:10])


def _apply_fill_to_position(position: dict[str, Any], fill: dict[str, Any]) -> dict[str, Any]:
    side = str(fill.get("side") or "").upper()
    fill_qty = _num(fill.get("quantity"))
    price = _num(fill.get("price"))
    notional = _num(fill.get("notional")) or fill_qty * price
    quantity = _num(position.get("quantity"))
    cost_basis = _num(position.get("cost_basis"))
    realized_pnl = _num(position.get("realized_pnl"))
    avg_before = cost_basis / quantity if quantity else 0.0

    if side == "BUY":
        quantity += fill_qty
        cost_basis += notional
    elif side == "SELL":
        matched_qty = min(quantity, fill_qty)
        realized_pnl += (price - avg_before) * matched_qty
        quantity -= matched_qty
        cost_basis -= avg_before * matched_qty
        if quantity <= 1e-9:
            quantity = 0.0
            cost_basis = 0.0

    avg_cost = cost_basis / quantity if quantity else 0.0
    return {
        **position,
        "quantity": quantity,
        "cost_basis": cost_basis,
        "avg_cost": avg_cost,
        "realized_pnl": realized_pnl,
        "diluted_cost": _diluted_cost(avg_cost, realized_pnl, quantity),
        "last_trade_price": price,
        "updated_at": fill.get("created_at"),
    }


def build_daily_position_history(
    fills: list[dict[str, Any]],
    *,
    market: str = "CN",
    limit: int | None = 20,
) -> list[dict[str, Any]]:
    positions: dict[str, dict[str, Any]] = {}
    days: dict[str, dict[str, Any]] = {}
    daily_symbol_pnl: dict[str, dict[str, float]] = defaultdict(dict)

    for fill in fills:
        symbol = _normalize_symbol(fill.get("symbol"))
        if not symbol:
            continue
        date = _trade_date(fill)
        day = days.setdefault(
            date,
            {
                "trade_date": date,
                "fills": [],
                "positions": [],
                "buy_qty": 0.0,
                "sell_qty": 0.0,
                "buy_notional": 0.0,
                "sell_notional": 0.0,
                "realized_pnl": 0.0,
            },
        )
        day["fills"].append(fill)
        current = positions.get(
            symbol,
            {
                "symbol": symbol,
                "market": market,
                "display_symbol": _display_symbol(symbol, market),
                "quantity": 0.0,
                "cost_basis": 0.0,
                "avg_cost": 0.0,
                "realized_pnl": 0.0,
                "diluted_cost": None,
                "last_trade_price": None,
                "updated_at": None,
            },
        )
        side = str(fill.get("side") or "").upper()
        fill_qty = _num(fill.get("quantity"))
        price = _num(fill.get("price"))
        notional = _num(fill.get("notional")) or fill_qty * price
        avg_before = _num(current.get("cost_basis")) / _num(current.get("quantity")) if _num(current.get("quantity")) else 0.0
        if side == "BUY":
            day["buy_qty"] += fill_qty
            day["buy_notional"] += notional
        elif side == "SELL":
            matched_qty = min(_num(current.get("quantity")), fill_qty)
            realized = (price - avg_before) * matched_qty
            day["sell_qty"] += fill_qty
            day["sell_notional"] += notional
            day["realized_pnl"] += realized
            daily_symbol_pnl[date][symbol] = daily_symbol_pnl[date].get(symbol, 0.0) + realized
        positions[symbol] = _apply_fill_to_position(current, fill)
        for position in positions.values():
            position["today_pnl"] = daily_symbol_pnl[date].get(str(position.get("symbol") or ""), 0.0)
            position["today_pnl_pct"] = _pnl_pct(position.get("today_pnl"), position.get("cost_basis"))
            if position.get("last_trade_price") is not None:
                position["last_price"] = position.get("last_trade_price")
                position["market_value"] = _num(position.get("quantity")) * _num(position.get("last_trade_price"))
        day["positions"] = [
            {**row}
            for row in sorted(
                positions.values(),
                key=lambda item: (abs(_num(item.get("cost_basis"))), str(item.get("symbol") or "")),
                reverse=True,
            )
            if abs(_num(row.get("quantity"))) > 1e-9
        ]

    keys = sorted(days.keys(), reverse=True)
    if limit is not None:
        keys = keys[:limit]
    rows = [days[key] for key in keys]
    for row in rows:
        row["fills_rows"] = len(row.get("fills") or [])
        row["positions_rows"] = len(row.get("positions") or [])
    return rows


def _normalize_date_param(value: str | None) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return datetime.strptime(text[:10], "%Y-%m-%d").date().isoformat()


def get_paper_db_daily_history(*, limit: int = 20, start_date: str | None = None, end_date: str | None = None) -> dict[str, Any]:
    settings = get_settings()
    try:
        normalized_start = _normalize_date_param(start_date)
        normalized_end = _normalize_date_param(end_date)
        if normalized_start and normalized_end and normalized_start > normalized_end:
            return {"rows": 0, "daily": [], "error": "start_date must be before or equal to end_date"}
        with _connect(settings) as conn:
            fills = _fills(conn, settings, limit=None, ascending=True)
        daily = build_daily_position_history(
            fills,
            market=settings.futu_gateway_market,
            limit=None if normalized_start or normalized_end else limit,
        )
        if normalized_start or normalized_end:
            daily = [
                row
                for row in daily
                if (not normalized_start or str(row.get("trade_date") or "") >= normalized_start)
                and (not normalized_end or str(row.get("trade_date") or "") <= normalized_end)
            ][:limit]
        return {"rows": len(daily), "daily": _deep_jsonable(daily), "error": None}
    except ValueError:
        return {"rows": 0, "daily": [], "error": "invalid date"}
    except Exception as exc:
        return {"rows": 0, "daily": [], "error": str(exc)}


def get_paper_db_daily_detail(trade_date: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        normalized_date = datetime.strptime(str(trade_date or "").strip()[:10], "%Y-%m-%d").date().isoformat()
    except ValueError:
        return {"trade_date": trade_date, "day": None, "error": "invalid trade date"}
    try:
        with _connect(settings) as conn:
            fills = _fills(conn, settings, limit=None, ascending=True)
        daily = build_daily_position_history(fills, market=settings.futu_gateway_market, limit=None)
        day = next((row for row in daily if row.get("trade_date") == normalized_date), None)
        return {"trade_date": normalized_date, "day": _deep_jsonable(day) if day else None, "error": None}
    except Exception as exc:
        return {"trade_date": normalized_date, "day": None, "error": str(exc)}


def get_paper_db_holdings(*, position_limit: int = 500, order_limit: int = 200) -> dict[str, Any]:
    settings = get_settings()
    generated_at = datetime.now(timezone.utc).isoformat()
    try:
        with _connect(settings) as conn:
            positions = _position_rows(conn, settings)[:position_limit]
            orders = get_paper_db_orders(limit=order_limit)["orders"]
            fills = _fills(conn, settings, limit=None, ascending=True)
        latest_daily = build_daily_position_history(fills, market=settings.futu_gateway_market, limit=1)
        latest_positions_by_symbol = {
            str(row.get("symbol") or ""): row
            for row in (latest_daily[0].get("positions") if latest_daily else []) or []
            if isinstance(row, dict)
        }
        for row in positions:
            daily_position = latest_positions_by_symbol.get(str(row.get("symbol") or ""))
            if daily_position:
                row["today_pnl"] = daily_position.get("today_pnl")
                row["today_pnl_pct"] = daily_position.get("today_pnl_pct")
        realized_pnl = sum(_num(row.get("realized_pnl")) for row in positions)
        unrealized_pnl = sum(_num(row.get("unrealized_pnl")) for row in positions)
        market_value = sum(_num(row.get("market_value")) for row in positions)
        summary = {
            "market_value": market_value,
            "realized_pnl": realized_pnl,
            "unrealized_pnl": unrealized_pnl,
            "total_pnl": realized_pnl + unrealized_pnl,
            "open_positions": len(positions),
            "currency": None,
            "cash": None,
            "buying_power": None,
            "total_assets": None,
        }
        return {
            "generated_at": generated_at,
            "source": "postgres",
            "summary": records_to_json([summary])[0],
            "balance": [],
            "positions_rows": len(positions),
            "raw_positions_rows": len(positions),
            "positions": records_to_json(positions),
            "orders_rows": len(orders),
            "orders": orders,
            "error": None,
        }
    except Exception as exc:
        return {
            "generated_at": generated_at,
            "source": "postgres",
            "summary": {},
            "balance": [],
            "positions_rows": 0,
            "raw_positions_rows": 0,
            "positions": [],
            "orders_rows": 0,
            "orders": [],
            "error": str(exc),
        }


def get_paper_db_stock(symbol: str) -> dict[str, Any]:
    settings = get_settings()
    normalized_symbol = _normalize_symbol(symbol)
    try:
        with _connect(settings) as conn:
            positions = [row for row in _position_rows(conn, settings, include_closed=True) if row.get("symbol") == normalized_symbol]
            position = positions[0] if positions else None
            fills = _enrich_symbol_rows(_fills(conn, settings, symbol=normalized_symbol, limit=None, ascending=True), settings)
            ledger, daily = build_symbol_ledger(fills)
            orders = get_paper_db_orders(symbol=normalized_symbol, limit=200)["orders"]
        latest = ledger[-1] if ledger else {}
        meta = _stock_meta(normalized_symbol, settings)
        realized_pnl = _num(position.get("realized_pnl")) if position else _num(latest.get("cumulative_realized_pnl"))
        unrealized_pnl = _num(position.get("unrealized_pnl")) if position else 0.0
        quantity = _num(position.get("quantity")) if position else _num(latest.get("position_quantity_after"))
        avg_cost = _num(position.get("avg_cost")) if position else _num(latest.get("avg_cost_after"))
        summary = {
            "symbol": normalized_symbol,
            "display_symbol": meta.get("display_symbol") or _display_symbol(normalized_symbol, settings.futu_gateway_market),
            "name": (position or {}).get("name") or meta.get("name") or None,
            "exchange": (position or {}).get("exchange") or meta.get("exchange") or settings.futu_gateway_market,
            "quantity": quantity,
            "avg_cost": avg_cost,
            "diluted_cost": _diluted_cost(avg_cost, realized_pnl, quantity),
            "last_price": position.get("last_price") if position else None,
            "market_value": position.get("market_value") if position else None,
            "realized_pnl": realized_pnl,
            "unrealized_pnl": unrealized_pnl,
            "total_pnl": realized_pnl + unrealized_pnl,
            "fills_count": len(fills),
            "orders_count": len(orders),
        }
        return {
            "symbol": normalized_symbol,
            "summary": records_to_json([summary])[0],
            "position": records_to_json([position])[0] if position else None,
            "daily": records_to_json(daily),
            "recent_orders": orders[:25],
            "recent_fills": records_to_json(list(reversed(fills))[:25]),
            "error": None,
        }
    except Exception as exc:
        return {
            "symbol": normalized_symbol,
            "summary": {},
            "position": None,
            "daily": [],
            "recent_orders": [],
            "recent_fills": [],
            "error": str(exc),
        }


def get_paper_db_stock_ledger(symbol: str, *, limit: int = 1000) -> dict[str, Any]:
    settings = get_settings()
    normalized_symbol = _normalize_symbol(symbol)
    try:
        with _connect(settings) as conn:
            fills = _enrich_symbol_rows(_fills(conn, settings, symbol=normalized_symbol, limit=None, ascending=True), settings)
        ledger, daily = build_symbol_ledger(fills)
        visible = list(reversed(ledger))[:limit]
        meta = _stock_meta(normalized_symbol, settings)
        return {
            "symbol": normalized_symbol,
            "display_symbol": meta.get("display_symbol") or _display_symbol(normalized_symbol, settings.futu_gateway_market),
            "name": meta.get("name") or None,
            "rows": len(ledger),
            "ledger": records_to_json(visible),
            "daily": records_to_json(daily),
            "error": None,
        }
    except Exception as exc:
        return {"symbol": normalized_symbol, "rows": 0, "ledger": [], "daily": [], "error": str(exc)}
