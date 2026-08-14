from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from app.config import Settings, get_settings
from app.serializers import records_to_json
from app.services.model_registry import get_active_deployment, get_latest_model_for_profile

try:
    import psycopg
    from psycopg.rows import dict_row
except Exception:  # pragma: no cover - runtime dependency availability is environment-specific
    psycopg = None
    dict_row = None


US_MARKET = "US"
US_CURRENCY = "USD"
US_TIMEZONE = "America/New_York"
US_BENCHMARK = {"symbol": "SPY", "name": "SPDR S&P 500 ETF Trust"}
US_MODEL_PROFILE = "us_5d_v1"
US_MODEL_REQUIRED_DATES = 504
US_MODEL_REQUIRED_SYMBOLS = 100

US_MODEL_DATA_SCHEMA_SQL = """
create table if not exists us_stock_daily_bars (
  trade_date date not null,
  symbol text not null references us_stock_master(symbol) on delete cascade,
  open numeric not null,
  high numeric not null,
  low numeric not null,
  close numeric not null,
  volume numeric not null,
  vwap numeric,
  transaction_count numeric,
  provider text not null,
  adjustment_state text not null check (adjustment_state in ('adjusted', 'unadjusted')),
  provider_timestamp bigint,
  ingestion_run_id text not null,
  source_payload_sha256 text not null,
  imported_at timestamptz not null default now(),
  primary key (trade_date, symbol, provider, adjustment_state)
);
create index if not exists us_stock_daily_bars_symbol_date_idx on us_stock_daily_bars(symbol, trade_date desc);
create index if not exists us_stock_daily_bars_lineage_idx on us_stock_daily_bars(ingestion_run_id, imported_at);
create table if not exists us_market_ingestion_runs (
  id text primary key,
  provider text not null,
  adjustment_state text not null,
  date_from date not null,
  date_to date not null,
  status text not null check (status in ('running', 'completed', 'partial', 'failed')),
  requested_symbols integer not null default 0,
  completed_symbols integer not null default 0,
  failed_symbols integer not null default 0,
  row_count bigint not null default 0,
  checkpoint jsonb not null default '{}'::jsonb,
  last_error text,
  started_at timestamptz not null default now(),
  completed_at timestamptz
);
"""


class UsMarketError(RuntimeError):
    pass


def _connect(settings: Settings | None = None):
    settings = settings or get_settings()
    if not settings.paper_db_url:
        raise UsMarketError("PAPER_DB_URL is not configured")
    if psycopg is None or dict_row is None:
        raise UsMarketError("psycopg is not installed")
    return psycopg.connect(
        settings.paper_db_url,
        row_factory=dict_row,
        connect_timeout=5,
        options="-c default_transaction_read_only=on",
    )


def init_us_model_data_schema(settings: Settings | None = None) -> None:
    resolved = settings or get_settings()
    if not resolved.paper_db_url or psycopg is None:
        raise UsMarketError("US model database is not configured")
    with psycopg.connect(resolved.paper_db_url, connect_timeout=8) as conn:
        with conn.cursor() as cur:
            cur.execute(US_MODEL_DATA_SCHEMA_SQL)
        conn.commit()


def _context(*, as_of: Any = None) -> dict[str, Any]:
    return {
        "market": US_MARKET,
        "currency": US_CURRENCY,
        "timezone": US_TIMEZONE,
        "benchmark": US_BENCHMARK,
        "as_of": str(as_of) if as_of else datetime.now(UTC).isoformat(),
    }


def _json_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for row in rows:
        normalized.append({key: float(value) if isinstance(value, Decimal) else value for key, value in row.items()})
    return records_to_json(normalized)


def _normalize_symbol(value: Any) -> str:
    symbol = str(value or "").strip().upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,14}", symbol):
        raise UsMarketError("invalid_symbol")
    return symbol


def _coverage(cur: Any) -> dict[str, Any]:
    cur.execute(
        """
        with active as (
          select count(*)::integer as count
          from us_stock_master
          where is_active = true and del_flg = false
        ), latest as (
          select max(trade_date) as trade_date
          from us_stock_daily_metrics
        )
        select
          active.count as active_symbols,
          latest.trade_date as latest_trade_date,
          (select min(trade_date) from us_stock_daily_metrics) as first_trade_date,
          (select count(distinct trade_date)::integer from us_stock_daily_metrics) as trading_dates,
          (select count(*)::bigint from us_stock_daily_metrics) as total_bars,
          (select count(distinct symbol)::integer from us_stock_daily_metrics d where d.trade_date = latest.trade_date) as latest_symbols
        from active cross join latest
        """
    )
    row = dict(cur.fetchone() or {})
    active = int(row.get("active_symbols") or 0)
    latest = int(row.get("latest_symbols") or 0)
    row["latest_coverage_pct"] = round((latest / active) * 100, 2) if active else 0.0
    return _json_rows([row])[0]


def _adjusted_bar_coverage(cur: Any) -> dict[str, Any]:
    cur.execute(
        """
        with eligible as (
          select b.symbol, count(distinct b.trade_date)::integer as trading_dates
          from us_stock_daily_bars b
          join us_stock_master m on m.symbol = b.symbol
          where b.provider = 'MASSIVE'
            and b.adjustment_state = 'adjusted'
            and m.is_active = true
            and m.del_flg = false
          group by b.symbol
        ), summary as (
          select
            min(trade_date) as first_trade_date,
            max(trade_date) as latest_trade_date,
            count(distinct trade_date)::integer as trading_dates,
            count(*)::bigint as total_bars
          from us_stock_daily_bars
          where provider = 'MASSIVE' and adjustment_state = 'adjusted'
        )
        select
          summary.*,
          (select count(*)::integer from eligible where trading_dates >= %s) as symbols_with_history,
          (select count(*)::integer from eligible) as available_symbols
        from summary
        """,
        [US_MODEL_REQUIRED_DATES],
    )
    return _json_rows([dict(cur.fetchone() or {})])[0]


def get_us_market_summary() -> dict[str, Any]:
    with _connect() as conn, conn.cursor() as cur:
        coverage = _coverage(cur)
        cur.execute(
            """
            select coalesce(market, 'UNKNOWN') as exchange, count(*)::integer as symbols
            from us_stock_master
            where is_active = true and del_flg = false
            group by market
            order by symbols desc, exchange
            """
        )
        exchanges = _json_rows([dict(row) for row in cur.fetchall()])
        cur.execute(
            """
            select
              count(*) filter (where details_updated_at is not null)::integer as details_ready,
              count(*) filter (where stock_industry is not null and stock_industry <> '')::integer as industry_ready,
              count(*) filter (where market_cap is not null and market_cap > 0)::integer as market_cap_ready
            from us_stock_master
            where is_active = true and del_flg = false
            """
        )
        fundamentals = _json_rows([dict(cur.fetchone() or {})])[0]
    return {
        **_context(as_of=coverage.get("latest_trade_date")),
        "coverage": coverage,
        "exchanges": exchanges,
        "fundamentals": fundamentals,
        "data_freshness": {
            "prices": coverage.get("latest_trade_date"),
            "history_status": "ready" if int(coverage.get("trading_dates") or 0) >= US_MODEL_REQUIRED_DATES else "backfill_required",
        },
    }


def list_us_stocks(*, search: str = "", limit: int = 50, offset: int = 0) -> dict[str, Any]:
    safe_limit = max(1, min(int(limit), 200))
    safe_offset = max(0, int(offset))
    query = str(search or "").strip()
    pattern = f"%{query}%"
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            select count(*)::integer as total
            from us_stock_master m
            where m.is_active = true and m.del_flg = false
              and (%s = '' or m.symbol ilike %s or m.stock_name ilike %s or m.stock_name_zh ilike %s)
            """,
            [query, pattern, pattern, pattern],
        )
        total = int((cur.fetchone() or {}).get("total") or 0)
        cur.execute(
            """
            select
              m.symbol,
              m.market as exchange,
              coalesce(nullif(m.stock_name, ''), m.symbol) as name,
              m.stock_name_zh as name_zh,
              m.stock_industry_en as industry,
              m.market_cap,
              coalesce(nullif(m.currency, ''), 'USD') as currency,
              d.trade_date,
              d.close,
              d.price_diff,
              d.volume,
              d.turnover
            from us_stock_master m
            left join lateral (
              select trade_date, close, price_diff, volume, turnover
              from us_stock_daily_metrics
              where symbol = m.symbol
              order by trade_date desc
              limit 1
            ) d on true
            where m.is_active = true and m.del_flg = false
              and (%s = '' or m.symbol ilike %s or m.stock_name ilike %s or m.stock_name_zh ilike %s)
            order by
              case when upper(m.symbol) = upper(%s) then 0 else 1 end,
              m.market_cap desc nulls last,
              m.symbol
            limit %s offset %s
            """,
            [query, pattern, pattern, pattern, query, safe_limit, safe_offset],
        )
        stocks = _json_rows([dict(row) for row in cur.fetchall()])
    latest = max((row.get("trade_date") for row in stocks if row.get("trade_date")), default=None)
    return {
        **_context(as_of=latest),
        "stocks": stocks,
        "rows": len(stocks),
        "total": total,
        "limit": safe_limit,
        "offset": safe_offset,
        "search": query,
        "data_freshness": {"prices": latest},
    }


def get_us_stock(*, symbol: str, history_limit: int = 260) -> dict[str, Any]:
    normalized = _normalize_symbol(symbol)
    safe_limit = max(1, min(int(history_limit), 1000))
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            select
              symbol, market as exchange, stock_name as name, stock_name_zh as name_zh,
              stock_type, stock_industry_en as industry, stock_industry as industry_zh,
              market_cap, circulating_shares_yi, earnings_per_share, pe_ratio, ipo_date,
              coalesce(nullif(currency, ''), 'USD') as currency,
              daily_updated_at, details_updated_at
            from us_stock_master
            where symbol = %s and is_active = true and del_flg = false
            """,
            [normalized],
        )
        stock = cur.fetchone()
        if not stock:
            raise UsMarketError("stock_not_found")
        cur.execute(
            """
            select trade_date, close, price_diff, volume, turnover, average_trade, transaction_count
            from us_stock_daily_metrics
            where symbol = %s
            order by trade_date desc
            limit %s
            """,
            [normalized, safe_limit],
        )
        history = _json_rows([dict(row) for row in cur.fetchall()])
    return {
        **_context(as_of=history[0].get("trade_date") if history else None),
        "stock": _json_rows([dict(stock)])[0],
        "history": history,
        "rows": len(history),
        "data_freshness": {"prices": history[0].get("trade_date") if history else None},
    }


def get_us_picks(*, limit: int = 25, list_type: str = "cat") -> dict[str, Any]:
    safe_limit = max(1, min(int(limit), 100))
    normalized_type = str(list_type or "cat").strip().lower()
    if normalized_type not in {"cat", "lobster"}:
        raise UsMarketError("invalid_list_type")
    with _connect() as conn, conn.cursor() as cur:
        cur.execute("select max(trade_date) as trade_date from us_selection_daily_snapshots where list_type = %s", [normalized_type])
        latest_date = (cur.fetchone() or {}).get("trade_date")
        rows: list[dict[str, Any]] = []
        if latest_date:
            cur.execute(
                """
                select
                  s.rank, s.code as symbol, s.exchange, s.score, s.signal_date,
                  coalesce(nullif(m.stock_name, ''), s.code) as name,
                  m.stock_industry_en as industry,
                  coalesce(nullif(m.currency, ''), 'USD') as currency,
                  s.row_data
                from us_selection_daily_snapshots s
                left join us_stock_master m on m.symbol = s.code
                where s.trade_date = %s and s.list_type = %s
                order by s.rank
                limit %s
                """,
                [latest_date, normalized_type, safe_limit],
            )
            rows = _json_rows([dict(row) for row in cur.fetchall()])
    return {
        **_context(as_of=latest_date),
        "selection_type": normalized_type,
        "selection_method": "rules_based",
        "model_profile": None,
        "picks": rows,
        "rows": len(rows),
        "data_freshness": {"selection": str(latest_date) if latest_date else None},
    }


def get_us_model_status() -> dict[str, Any]:
    with _connect() as conn, conn.cursor() as cur:
        coverage = _adjusted_bar_coverage(cur)
    trading_dates = int(coverage.get("trading_dates") or 0)
    symbols_with_history = int(coverage.get("symbols_with_history") or coverage.get("latest_symbols") or 0)
    history_ready = trading_dates >= US_MODEL_REQUIRED_DATES and symbols_with_history >= US_MODEL_REQUIRED_SYMBOLS
    candidate = None
    deployment = None
    try:
        candidate = get_latest_model_for_profile("US", US_MODEL_PROFILE, sync=False)
        deployment = get_active_deployment("US", sync=False)
    except Exception:
        pass
    validation_status = str((candidate or {}).get("validation_status") or "pending")
    training_ready = candidate is not None
    walk_forward_ready = validation_status == "passed"
    active = bool(deployment and candidate and deployment.get("model_id") == candidate.get("id"))
    blockers: list[str] = []
    if trading_dates < US_MODEL_REQUIRED_DATES:
        blockers.append(f"Requires {US_MODEL_REQUIRED_DATES} adjusted trading dates; {trading_dates} are available.")
    if symbols_with_history < US_MODEL_REQUIRED_SYMBOLS:
        blockers.append(
            f"Requires {US_MODEL_REQUIRED_SYMBOLS} symbols with complete adjusted history; {symbols_with_history} are available."
        )
    if not training_ready:
        blockers.append("The US 5-day model has not been trained yet.")
    elif not walk_forward_ready:
        blockers.append(f"The latest US model validation status is {validation_status}.")
    return {
        **_context(as_of=coverage.get("latest_trade_date")),
        "profile": {
            "name": US_MODEL_PROFILE,
            "label": "US 5D Model",
            "horizon_trading_days": 5,
            "benchmark": US_BENCHMARK,
            "status": "insufficient_history" if not history_ready else "not_trained" if not training_ready else validation_status,
            "model_version": (candidate or {}).get("model_version"),
            "training_date": (candidate or {}).get("training_date"),
            "active": active,
        },
        "gate": {
            "ready": history_ready and walk_forward_ready and active,
            "required_trading_dates": US_MODEL_REQUIRED_DATES,
            "available_trading_dates": trading_dates,
            "required_symbols_with_history": US_MODEL_REQUIRED_SYMBOLS,
            "available_symbols_with_history": symbols_with_history,
            "history_ready": history_ready,
            "training_ready": training_ready,
            "walk_forward_ready": walk_forward_ready,
            "blockers": blockers,
        },
        "metrics": (candidate or {}).get("validation_metrics"),
        "deployment": deployment,
        "data_freshness": {"prices": coverage.get("latest_trade_date")},
    }


def get_us_paper_status() -> dict[str, Any]:
    model = get_us_model_status()
    return {
        **_context(as_of=model.get("as_of")),
        "status": "gated",
        "enabled": False,
        "account": None,
        "positions": [],
        "orders": [],
        "gate": model["gate"],
        "message": "US paper trading remains disabled until data quality and walk-forward validation pass.",
    }


def get_us_pipeline_status() -> dict[str, Any]:
    with _connect() as conn, conn.cursor() as cur:
        coverage = _coverage(cur)
        cur.execute(
            """
            select lane, target_date, status, started_at, completed_at,
                   total_count, done_count, failed_count, skipped_count,
                   last_symbol, last_error
            from us_selection_job_runs
            order by started_at desc
            limit 20
            """
        )
        runs = _json_rows([dict(row) for row in cur.fetchall()])
    running = next((run for run in runs if run.get("status") == "running"), None)
    return {
        **_context(as_of=coverage.get("latest_trade_date")),
        "status": "running" if running else "idle",
        "is_running": running is not None,
        "current_run": running,
        "recent_runs": runs,
        "coverage": coverage,
        "scheduler": {
            "timezone": US_TIMEZONE,
            "lanes": ["price", "average-trade", "details", "universe", "snapshots"],
        },
        "data_freshness": {"prices": coverage.get("latest_trade_date")},
    }


def get_us_overview() -> dict[str, Any]:
    summary = get_us_market_summary()
    picks = get_us_picks(limit=5)
    model = get_us_model_status()
    pipeline = get_us_pipeline_status()
    return {
        **_context(as_of=summary.get("as_of")),
        "summary": summary,
        "top_picks": picks["picks"],
        "selection": {
            "method": picks["selection_method"],
            "date": picks["data_freshness"]["selection"],
        },
        "model": model,
        "pipeline": {
            "status": pipeline["status"],
            "is_running": pipeline["is_running"],
            "current_run": pipeline["current_run"],
        },
        "paper": {
            "status": "gated",
            "enabled": False,
            "message": "US paper trading will unlock only after model validation passes.",
        },
        "data_freshness": summary["data_freshness"],
    }
