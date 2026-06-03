from __future__ import annotations

from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from app.config import Settings, get_settings
from app.serializers import records_to_json, to_jsonable
from app.services.paper import _enrich_position_metadata

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
            fills = _fills(conn, settings, symbol=normalized_symbol, limit=None, ascending=True)
            ledger, daily = build_symbol_ledger(fills)
            orders = get_paper_db_orders(symbol=normalized_symbol, limit=200)["orders"]
        latest = ledger[-1] if ledger else {}
        realized_pnl = _num(position.get("realized_pnl")) if position else _num(latest.get("cumulative_realized_pnl"))
        unrealized_pnl = _num(position.get("unrealized_pnl")) if position else 0.0
        quantity = _num(position.get("quantity")) if position else _num(latest.get("position_quantity_after"))
        avg_cost = _num(position.get("avg_cost")) if position else _num(latest.get("avg_cost_after"))
        summary = {
            "symbol": normalized_symbol,
            "display_symbol": _display_symbol(normalized_symbol, settings.futu_gateway_market),
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
            fills = _fills(conn, settings, symbol=normalized_symbol, limit=None, ascending=True)
        ledger, daily = build_symbol_ledger(fills)
        visible = list(reversed(ledger))[:limit]
        return {
            "symbol": normalized_symbol,
            "rows": len(ledger),
            "ledger": records_to_json(visible),
            "daily": records_to_json(daily),
            "error": None,
        }
    except Exception as exc:
        return {"symbol": normalized_symbol, "rows": 0, "ledger": [], "daily": [], "error": str(exc)}
