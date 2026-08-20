#!/usr/bin/env python3
"""Update the Postgres-backed US selection dataset.

The script is intentionally runnable as a one-shot worker. The API layer starts
it in a Docker container; local operators can also run individual lanes by hand.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover - depends on runtime image
    psycopg = None
    dict_row = None

NY_TZ = ZoneInfo("America/New_York")
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
YAHOO_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
FUTU_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.futunn.com/",
}
STATUS_DEFAULT = "run/us_selection_update_status.json"
CHECKPOINT_DEFAULT = "run/us_selection_update_checkpoint.json"
SCHEMA_DEFAULT = "scripts/create_us_selection.sql"


@dataclass(frozen=True)
class StockQuote:
    close: float
    price_diff: float | None


@dataclass(frozen=True)
class MarketCapDecision:
    value_usd: float | None
    source: str | None
    is_estimated: bool | None
    status: str
    deviation_pct: float | None = None


FINNHUB_INDUSTRY_TRANSLATIONS: dict[str, tuple[str, str]] = {
    "Airlines": ("航空公司", "航空"),
    "Automobiles": ("汽车制造", "汽车"),
    "Beverages": ("饮料", "饮料"),
    "Financial Services": ("金融服务", "金融"),
    "Hotels, Restaurants & Leisure": ("酒店餐饮休闲", "餐饮旅游"),
    "Media": ("媒体内容", "媒体"),
    "Pharmaceuticals": ("制药", "制药"),
    "Real Estate": ("房地产", "地产"),
    "Retail": ("零售", "零售"),
    "Semiconductors": ("半导体", "半导体"),
    "Technology": ("科技", "科技"),
}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return now_utc().isoformat()


def today_ny() -> date:
    return now_utc().astimezone(NY_TZ).date()


def previous_ny_day(value: date | None = None) -> date:
    return (value or today_ny()) - timedelta(days=1)


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value.strip()[:10], "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(f"Invalid date: {value}") from exc


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.{time.monotonic_ns()}.tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def append_log(log_file: Path | None, message: str) -> None:
    line = f"[{now_iso()}] {message}"
    print(line, flush=True)
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with log_file.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")


def http_json(url: str, *, timeout: float = 15.0, headers: dict[str, str] | None = None) -> Any:
    request = Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def http_text(url: str, *, timeout: float = 20.0, headers: dict[str, str] | None = None) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    with urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        text = str(value).strip().replace(",", "")
        if not text or text == "-":
            return None
        return float(text)
    except (TypeError, ValueError):
        return None


def positive_finite_float(value: Any) -> float | None:
    number = as_float(value)
    if number is None or not math.isfinite(number) or number <= 0:
        return None
    return number


def finnhub_market_cap_usd(value_millions: Any, currency: Any) -> float | None:
    if str(currency or "").strip().upper() != "USD":
        return None
    value = positive_finite_float(value_millions)
    return None if value is None else value * 1_000_000


def calculated_market_cap_usd(close: Any, shares_yi: Any) -> float | None:
    price = positive_finite_float(close)
    shares = positive_finite_float(shares_yi)
    if price is None or shares is None:
        return None
    return price * shares * 100_000_000


def resolve_market_cap(
    *,
    provider_value_millions: Any,
    currency: Any,
    close: Any,
    shares_yi: Any,
    max_deviation_pct: float = 20.0,
) -> MarketCapDecision:
    normalized_currency = str(currency or "").strip().upper()
    if normalized_currency != "USD":
        return MarketCapDecision(None, None, None, "rejected_currency")

    provider_value = finnhub_market_cap_usd(provider_value_millions, normalized_currency)
    calculated_value = calculated_market_cap_usd(close, shares_yi)
    if provider_value is not None and calculated_value is not None:
        deviation_pct = abs(provider_value - calculated_value) / calculated_value * 100
        if deviation_pct > max_deviation_pct:
            return MarketCapDecision(None, None, None, "rejected_deviation", round(deviation_pct, 2))
        return MarketCapDecision(provider_value, "finnhub_profile2", False, "validated", round(deviation_pct, 2))
    if provider_value is not None:
        return MarketCapDecision(provider_value, "finnhub_profile2", False, "provider_only")
    if calculated_value is not None:
        return MarketCapDecision(calculated_value, "close_x_outstanding_shares", True, "calculated_fallback")
    return MarketCapDecision(None, None, None, "insufficient_data")


def normalize_finnhub_industry(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.upper() == "N/A":
        return None
    return text


def translate_finnhub_industry(value: Any) -> tuple[str, str] | None:
    industry = normalize_finnhub_industry(value)
    if industry is None:
        return None
    return FINNHUB_INDUSTRY_TRANSLATIONS.get(industry)


def as_int(value: Any) -> int | None:
    number = as_float(value)
    return None if number is None else int(number)


def shares_to_yi(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not text or text == "-":
        return None
    if "亿" in text:
        return as_float(text.replace("亿", ""))
    if "万" in text:
        number = as_float(text.replace("万", ""))
        return None if number is None else number / 10000
    if "千" in text:
        number = as_float(text.replace("千", ""))
        return None if number is None else number / 100000000
    number = as_float(text)
    return None if number is None else number / 100000000


def connect_pg(database_url: str):
    if psycopg is None or dict_row is None:
        raise RuntimeError("psycopg is not installed")
    return psycopg.connect(database_url, row_factory=dict_row)


def ensure_schema(conn: Any, schema_path: Path) -> None:
    conn.execute(schema_path.read_text(encoding="utf-8"))
    conn.commit()


def completed_run_exists(conn: Any, lane: str, target_date: date | None) -> bool:
    if target_date is None:
        return False
    with conn.cursor() as cur:
        cur.execute(
            """
            select 1
            from us_selection_job_runs
            where lane = %s
              and target_date = %s
              and status = 'success'
            limit 1
            """,
            [lane, target_date],
        )
        return cur.fetchone() is not None


def start_run(conn: Any, lane: str, target_date: date | None, container_name: str | None) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into us_selection_job_runs (lane, target_date, status, container_name, started_at, updated_at)
            values (%s, %s, 'running', %s, now(), now())
            returning id
            """,
            [lane, target_date, container_name],
        )
        row = cur.fetchone()
    conn.commit()
    return int(row["id"])


def finish_run(conn: Any, run_id: int, status: str, summary: dict[str, Any]) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            update us_selection_job_runs
            set status = %s,
                completed_at = now(),
                updated_at = now(),
                total_count = %s,
                done_count = %s,
                failed_count = %s,
                skipped_count = %s,
                last_symbol = %s,
                last_error = %s,
                summary = %s::jsonb
            where id = %s
            """,
            [
                status,
                int(summary.get("total_count") or 0),
                int(summary.get("done_count") or 0),
                int(summary.get("failed_count") or 0),
                int(summary.get("skipped_count") or 0),
                summary.get("last_symbol"),
                summary.get("last_error"),
                json.dumps(summary, ensure_ascii=False, default=str),
                run_id,
            ],
        )
    conn.commit()


def update_status(path: Path, payload: dict[str, Any]) -> None:
    write_json(path, {"updated_at": now_iso(), **payload})


def symbol_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [part.strip().upper() for part in raw.split(",") if part.strip()]


def active_symbols(conn: Any, *, symbols: list[str], limit: int | None = None) -> list[str]:
    if symbols:
        return symbols[:limit] if limit else symbols
    sql = """
        select symbol
        from us_stock_master
        where is_active = true
          and del_flg = false
        order by coalesce(daily_updated_at, '1970-01-01'::timestamptz), symbol
    """
    params: list[Any] = []
    if limit:
        sql += " limit %s"
        params.append(limit)
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return [str(row["symbol"]) for row in cur.fetchall()]


def details_symbols(conn: Any, *, symbols: list[str], limit: int) -> list[str]:
    if symbols:
        return symbols[:limit]
    with conn.cursor() as cur:
        cur.execute(
            """
            select m.symbol
            from us_stock_master m
            left join lateral (
              select d.close
              from us_stock_daily_metrics d
              where d.symbol = m.symbol
              order by d.trade_date desc
              limit 1
            ) latest on true
            where m.is_active = true
              and m.del_flg = false
            order by
              case when m.market_cap is null or m.market_cap <= 0 then 0 else 1 end,
              case when m.market_cap_attempted_at is null then 0 else 1 end,
              case when exists (select 1 from us_stock_favorite_stocks f where f.symbol = m.symbol) then 0 else 1 end,
              case when coalesce(nullif(m.currency, ''), 'USD') = 'USD' then 0 else 1 end,
              coalesce(m.market_cap, latest.close * m.circulating_shares_yi * 100000000) desc nulls last,
              m.market_cap_attempted_at asc nulls first,
              m.details_updated_at asc nulls first,
              m.symbol asc
            limit %s
            """,
            [limit],
        )
        return [str(row["symbol"]) for row in cur.fetchall()]


def average_symbols(conn: Any, target_date: date, *, symbols: list[str], limit: int | None = None) -> list[str]:
    if symbols:
        return symbols[:limit] if limit else symbols
    sql = """
        select m.symbol
        from us_stock_master m
        left join us_stock_daily_metrics d
          on d.symbol = m.symbol
         and d.trade_date = %s
        where m.is_active = true
          and m.del_flg = false
          and (d.average_trade is null or d.transaction_count is null)
        order by
          case when exists (select 1 from us_stock_favorite_stocks f where f.symbol = m.symbol) then 0 else 1 end,
          m.symbol
    """
    params: list[Any] = [target_date]
    if limit:
        sql += " limit %s"
        params.append(limit)
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return [str(row["symbol"]) for row in cur.fetchall()]


def upsert_master_symbol(conn: Any, row: dict[str, Any]) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into us_stock_master (
              symbol, market, stock_type, stock_name, stock_name_zh, stock_industry,
              market_cap, pe_ratio, is_active, del_flg, fav_flg, display_num,
              universe_updated_at, updated_at
            ) values (
              %s, %s, %s, %s, %s, %s, %s, %s, coalesce(%s, true), coalesce(%s, false),
              coalesce(%s, false), %s, now(), now()
            )
            on conflict (symbol) do update set
              market = coalesce(excluded.market, us_stock_master.market),
              stock_type = coalesce(excluded.stock_type, us_stock_master.stock_type),
              stock_name = coalesce(excluded.stock_name, us_stock_master.stock_name),
              stock_name_zh = coalesce(excluded.stock_name_zh, us_stock_master.stock_name_zh),
              stock_industry = coalesce(excluded.stock_industry, us_stock_master.stock_industry),
              market_cap = coalesce(excluded.market_cap, us_stock_master.market_cap),
              pe_ratio = coalesce(excluded.pe_ratio, us_stock_master.pe_ratio),
              is_active = excluded.is_active,
              del_flg = excluded.del_flg,
              fav_flg = excluded.fav_flg,
              display_num = coalesce(excluded.display_num, us_stock_master.display_num),
              universe_updated_at = now(),
              updated_at = now()
            """,
            [
                row.get("symbol"),
                row.get("market"),
                row.get("stock_type"),
                row.get("stock_name"),
                row.get("stock_name_zh"),
                row.get("stock_industry"),
                row.get("market_cap"),
                row.get("pe_ratio"),
                row.get("is_active", True),
                row.get("del_flg", False),
                row.get("fav_flg", False),
                row.get("display_num"),
            ],
        )


def upsert_daily_price(conn: Any, symbol: str, trade_date: date, quote: StockQuote, volume: int | None, turnover: float | None) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into us_stock_daily_metrics (
              trade_date, symbol, close, price_diff, volume, turnover, imported_at
            ) values (
              %s, %s, %s, %s, %s, %s, now()
            )
            on conflict (trade_date, symbol) do update set
              close = excluded.close,
              price_diff = excluded.price_diff,
              volume = coalesce(excluded.volume, us_stock_daily_metrics.volume),
              turnover = coalesce(excluded.turnover, us_stock_daily_metrics.turnover),
              imported_at = now()
            """,
            [trade_date, symbol, quote.close, quote.price_diff, volume, turnover],
        )
        cur.execute("update us_stock_master set daily_updated_at = now(), updated_at = now() where symbol = %s", [symbol])


def upsert_average(conn: Any, symbol: str, trade_date: date, volume: int | None, transaction_count: int | None, average_trade: int | None) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into us_stock_daily_metrics (
              trade_date, symbol, volume, average_trade, transaction_count, massive_updated_at, imported_at
            ) values (
              %s, %s, %s, %s, %s, now(), now()
            )
            on conflict (trade_date, symbol) do update set
              volume = coalesce(excluded.volume, us_stock_daily_metrics.volume),
              average_trade = excluded.average_trade,
              transaction_count = excluded.transaction_count,
              massive_updated_at = now(),
              imported_at = now()
            """,
            [trade_date, symbol, volume, average_trade, transaction_count],
        )


def fetch_finnhub_universe(api_key: str, exchange: str) -> list[dict[str, Any]]:
    url = f"https://finnhub.io/api/v1/stock/symbol?exchange={quote(exchange)}&token={quote(api_key)}"
    data = http_json(url, timeout=30)
    return data if isinstance(data, list) else []


def refresh_universe(conn: Any, args: argparse.Namespace, status_path: Path, log_file: Path | None) -> dict[str, Any]:
    api_key = os.getenv("FINNHUB_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("FINNHUB_API_KEY is required for --refresh-universe")

    mic_market_map = {"XNYS": "NYSE", "XNAS": "NASDAQ"}
    allowed_types = {
        "ADR",
        "Common Stock",
        "MLP",
        "NY Reg Shrs",
        "REIT",
        "Royalty Trst",
        "Tracking Stk",
    }
    exchanges = [("US", None)]
    seen: set[str] = set()
    done = 0
    failed = 0

    update_status(status_path, {"status": "running", "stage": "refresh_universe", "done_count": 0, "failed_count": 0})
    for exchange_code, _expected_market in exchanges:
        try:
            rows = fetch_finnhub_universe(api_key, exchange_code)
        except (HTTPError, URLError, TimeoutError, ValueError) as exc:
            append_log(log_file, f"Universe fetch failed for {exchange_code}: {exc}")
            failed += 1
            continue
        for item in rows:
            symbol = str(item.get("symbol") or "").strip().upper()
            if not symbol:
                continue
            mic = str(item.get("mic") or "").strip().upper()
            market = mic_market_map.get(mic)
            stock_type = str(item.get("type") or "").strip()
            if market is None or stock_type not in allowed_types:
                continue
            upsert_master_symbol(
                conn,
                {
                    "symbol": symbol,
                    "market": market,
                    "stock_type": stock_type,
                    "stock_name": item.get("description"),
                    "is_active": True,
                    "del_flg": False,
                },
            )
            seen.add(symbol)
            done += 1
        conn.commit()
        append_log(log_file, f"Universe refreshed for NYSE/NASDAQ stocks: {done} total symbols")

    if seen:
        with conn.cursor() as cur:
            cur.execute(
                """
                update us_stock_master
                set is_active = false,
                    del_flg = true,
                    updated_at = now()
                where symbol <> all(%s)
                """,
                [list(seen)],
            )
        conn.commit()

    refresh_holidays(conn, api_key, log_file)
    return {"total_count": len(seen), "done_count": done, "failed_count": failed, "last_symbol": None}


def refresh_holidays(conn: Any, api_key: str, log_file: Path | None) -> None:
    url = f"https://finnhub.io/api/v1/stock/market-holiday?exchange=US&token={quote(api_key)}"
    try:
        data = http_json(url, timeout=20)
    except Exception as exc:
        append_log(log_file, f"Holiday fetch failed: {exc}")
        return
    rows = data.get("data") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return
    with conn.cursor() as cur:
        for item in rows:
            at_date = item.get("atDate")
            if not at_date:
                continue
            cur.execute(
                """
                insert into us_market_holidays (exchange, at_date, event_name, trading_hour, updated_at)
                values ('US', %s, %s, %s, now())
                on conflict (exchange, at_date) do update set
                  event_name = excluded.event_name,
                  trading_hour = excluded.trading_hour,
                  updated_at = now()
                """,
                [at_date, item.get("eventName"), item.get("tradingHour")],
            )
    conn.commit()
    append_log(log_file, f"Holiday calendar refreshed: {len(rows)} rows")


def full_market_holiday(conn: Any, target_date: date) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            select 1
            from us_market_holidays
            where exchange = 'US'
              and at_date = %s
              and (trading_hour is null or trading_hour = '')
            limit 1
            """,
            [target_date],
        )
        return cur.fetchone() is not None


def fetch_finnhub_quote(symbol: str, api_key: str) -> StockQuote | None:
    url = f"https://finnhub.io/api/v1/quote?symbol={quote(symbol)}&token={quote(api_key)}"
    data = http_json(url, timeout=12)
    close = as_float(data.get("c") if isinstance(data, dict) else None)
    prev_close = as_float(data.get("pc") if isinstance(data, dict) else None)
    if close is None or close <= 0:
        return None
    return StockQuote(close=close, price_diff=None if prev_close is None else close - prev_close)


def fetch_finnhub_profile(symbol: str, api_key: str) -> dict[str, Any] | None:
    url = f"https://finnhub.io/api/v1/stock/profile2?symbol={quote(symbol)}&token={quote(api_key)}"
    data = http_json(url, timeout=12)
    if not isinstance(data, dict) or not data:
        return None

    industry_en = normalize_finnhub_industry(data.get("finnhubIndustry"))
    translated = translate_finnhub_industry(industry_en)
    industry, industry_short = translated if translated else (None, None)
    return {
        "stock_industry_en": industry_en,
        "stock_industry": industry,
        "stock_industry_short": industry_short,
        "currency": str(data.get("currency") or "").strip().upper() or None,
        "market_cap_millions": data.get("marketCapitalization"),
        "share_outstanding_yi": (
            None
            if positive_finite_float(data.get("shareOutstanding")) is None
            else positive_finite_float(data.get("shareOutstanding")) / 100
        ),
    }


def fetch_yahoo_volume(symbol: str) -> int | None:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol)}?interval=1d&range=1d"
    try:
        data = http_json(url, timeout=30, headers={"User-Agent": YAHOO_USER_AGENT})
    except (HTTPError, URLError, TimeoutError, ValueError):
        return None
    try:
        result = data["chart"]["result"][0]
        volume = result["indicators"]["quote"][0].get("volume", [None])[-1]
    except (KeyError, IndexError, TypeError):
        return None
    return as_int(volume)


def circulating_shares_yi(conn: Any, symbol: str) -> float | None:
    with conn.cursor() as cur:
        cur.execute("select circulating_shares_yi from us_stock_master where symbol = %s", [symbol])
        row = cur.fetchone()
    return as_float(row.get("circulating_shares_yi") if row else None)


def update_prices(conn: Any, args: argparse.Namespace, status_path: Path, log_file: Path | None) -> dict[str, Any]:
    api_key = os.getenv("FINNHUB_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("FINNHUB_API_KEY is required for --update-prices")

    target_date = parse_date(args.target_date) or today_ny()
    if target_date.weekday() >= 5 or full_market_holiday(conn, target_date):
        append_log(log_file, f"Price lane skipped for non-trading date {target_date}")
        return {"target_date": target_date.isoformat(), "skipped_count": 1}
    symbols = active_symbols(conn, symbols=symbol_list(args.symbols), limit=args.limit)
    return process_symbol_batches(
        conn,
        symbols,
        status_path,
        log_file,
        stage="update_prices",
        batch_size=args.price_batch_size,
        sleep_seconds=args.price_batch_sleep_seconds,
        worker=lambda symbol: update_one_price(conn, symbol, target_date, api_key),
        target_date=target_date,
        checkpoint_path=Path(args.checkpoint_file),
    )


def update_one_price(conn: Any, symbol: str, target_date: date, api_key: str) -> bool:
    quote_data = fetch_finnhub_quote(symbol, api_key)
    if quote_data is None:
        return False
    volume = fetch_yahoo_volume(symbol)
    if volume is None:
        volume = 0
    shares_yi = circulating_shares_yi(conn, symbol)
    turnover = None
    if volume is not None and shares_yi and shares_yi > 0:
        turnover = round(volume / (shares_yi * 100000000) * 100, 2)
    upsert_daily_price(conn, symbol, target_date, quote_data, volume, turnover)
    conn.commit()
    return True


def fetch_massive_aggregates(symbol: str, api_key: str, target_date: date) -> list[dict[str, Any]]:
    from_date = (target_date - timedelta(days=14)).isoformat()
    to_date = target_date.isoformat()
    url = (
        f"https://api.massive.com/v2/aggs/ticker/{quote(symbol)}/range/1/day/{from_date}/{to_date}"
        f"?adjusted=true&sort=desc&apiKey={quote(api_key)}"
    )
    data = http_json(url, timeout=20)
    rows = data.get("results") if isinstance(data, dict) else None
    return rows if isinstance(rows, list) else []


def update_average_trade(conn: Any, args: argparse.Namespace, status_path: Path, log_file: Path | None) -> dict[str, Any]:
    api_key = os.getenv("MASSIVE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("MASSIVE_API_KEY is required for --update-average-trade")
    target_date = parse_date(args.target_date) or previous_ny_day()
    if target_date.weekday() >= 5 or full_market_holiday(conn, target_date):
        append_log(log_file, f"Average-trade lane skipped for non-trading date {target_date}")
        return {"target_date": target_date.isoformat(), "skipped_count": 1}
    symbols = average_symbols(conn, target_date, symbols=symbol_list(args.symbols), limit=args.limit)
    return process_symbol_batches(
        conn,
        symbols,
        status_path,
        log_file,
        stage="update_average_trade",
        batch_size=args.massive_batch_size,
        sleep_seconds=args.massive_batch_sleep_seconds,
        worker=lambda symbol: update_one_average(conn, symbol, target_date, api_key),
        target_date=target_date,
        checkpoint_path=Path(args.checkpoint_file),
    )


def update_one_average(conn: Any, symbol: str, target_date: date, api_key: str) -> bool:
    rows = fetch_massive_aggregates(symbol, api_key, target_date)
    updated = False
    for item in rows:
        raw_ts = item.get("t")
        if raw_ts is None:
            continue
        trade_date = datetime.fromtimestamp(float(raw_ts) / 1000, tz=timezone.utc).date()
        volume = as_int(item.get("v"))
        transaction_count = as_int(item.get("n"))
        average_trade = None if not volume or not transaction_count else round(volume / transaction_count)
        upsert_average(conn, symbol, trade_date, volume, transaction_count, average_trade)
        updated = updated or trade_date == target_date
    conn.commit()
    return updated


def fetch_futu_details(symbol: str) -> dict[str, Any] | None:
    html = http_text(f"https://www.futunn.com/stock/{quote(symbol)}-US/", timeout=20, headers=FUTU_HEADERS)
    stock_match = re.search(r'"stock_info"\s*:\s*(\{.*?"isETFTheme":\s*(?:true|false))\s*\}', html, re.S)
    if not stock_match:
        return None
    stock_json = stock_match.group(1) + "}"
    try:
        stock_data = json.loads(stock_json)
    except json.JSONDecodeError:
        return None

    keywords: list[tuple[str, str]] = []
    sparks_match = re.search(r'"stock_sparks"\s*:\s*(\{.*?"list"\s*:\s*\[.*?\])\s*\}', html, re.S)
    if sparks_match:
        try:
            sparks = json.loads(sparks_match.group(1) + "}")
            for item in sparks.get("list", []):
                name = str(item.get("plateName") or "").strip()
                code = str(item.get("plateCode") or "futu").strip() or "futu"
                if name:
                    keywords.append((code, name))
        except (json.JSONDecodeError, AttributeError):
            pass

    return {"stock": stock_data, "keywords": keywords}


def update_details(conn: Any, args: argparse.Namespace, status_path: Path, log_file: Path | None) -> dict[str, Any]:
    max_symbols = args.details_batch_size * args.details_max_batches
    if args.limit:
        max_symbols = min(max_symbols, args.limit)
    symbols = details_symbols(conn, symbols=symbol_list(args.symbols), limit=max_symbols)
    api_key = os.getenv("FINNHUB_API_KEY", "").strip()
    if not api_key:
        append_log(log_file, "FINNHUB_API_KEY is not configured; industry fields will not be refreshed")
    return process_symbol_batches(
        conn,
        symbols,
        status_path,
        log_file,
        stage="update_details",
        batch_size=args.details_batch_size,
        sleep_seconds=args.details_sleep_seconds,
        worker=lambda symbol: update_one_detail(conn, symbol, api_key=api_key or None, log_file=log_file),
        target_date=None,
        checkpoint_path=Path(args.checkpoint_file),
    )


def update_one_detail(conn: Any, symbol: str, *, api_key: str | None = None, log_file: Path | None = None) -> bool:
    updated = False
    details = None
    try:
        details = fetch_futu_details(symbol)
    except (HTTPError, URLError, TimeoutError, ValueError) as exc:
        append_log(log_file, f"{symbol}: Futunn detail fetch failed: {exc}")

    profile = None
    if api_key:
        try:
            profile = fetch_finnhub_profile(symbol, api_key)
        except (HTTPError, URLError, TimeoutError, ValueError) as exc:
            append_log(log_file, f"{symbol}: Finnhub profile fetch failed: {exc}")

    with conn.cursor() as cur:
        if details:
            stock = details["stock"]
            name = str(stock.get("enName") or stock.get("name") or "").strip() or None
            zh_name = str(stock.get("name") or "").strip() or None
            if zh_name and not re.search(r"[\u3400-\u9fff\uf900-\ufaff]", zh_name):
                zh_name = None
            cur.execute(
                """
                update us_stock_master
                set stock_name = coalesce(%s, stock_name),
                    stock_name_zh = coalesce(%s, stock_name_zh),
                    circulating_shares_yi = coalesce(%s, circulating_shares_yi),
                    earnings_per_share = coalesce(%s, earnings_per_share),
                    pe_ratio = coalesce(%s, pe_ratio),
                    details_updated_at = now(),
                    updated_at = now()
                where symbol = %s
                """,
                [
                    name,
                    zh_name,
                    shares_to_yi(stock.get("outstandingShares")),
                    as_float(stock.get("epsTtm")),
                    as_float(stock.get("peTtm")),
                    symbol,
                ],
            )
            cur.execute("delete from us_stock_key_map where symbol = %s", [symbol])
            for place_num, (key_code, key_name) in enumerate(details["keywords"], start=1):
                cur.execute(
                    """
                    insert into us_stock_keywords (key_code, key_name, created_at, updated_at)
                    values (%s, %s, now(), now())
                    on conflict (key_name) do update set
                      key_code = excluded.key_code,
                      updated_at = now()
                    """,
                    [key_code, key_name],
                )
                cur.execute(
                    """
                    insert into us_stock_key_map (symbol, key_code, key_name, place_num, created_at, updated_at)
                    values (%s, %s, %s, %s, now(), now())
                    on conflict (symbol, key_name) do update set
                      key_code = excluded.key_code,
                      place_num = excluded.place_num,
                      updated_at = now()
                    """,
                    [symbol, key_code, key_name, place_num],
                )
            updated = True

        if profile:
            if profile["stock_industry_en"] and not profile["stock_industry"]:
                append_log(log_file, f"{symbol}: unmapped Finnhub industry {profile['stock_industry_en']}")
            cur.execute(
                """
                update us_stock_master
                set stock_industry_en = coalesce(%s, stock_industry_en),
                    stock_industry = coalesce(%s, stock_industry),
                    stock_industry_short = coalesce(%s, stock_industry_short),
                    circulating_shares_yi = coalesce(circulating_shares_yi, %s),
                    currency = coalesce(%s, currency),
                    details_updated_at = now(),
                    updated_at = now()
                where symbol = %s
                """,
                [
                    profile["stock_industry_en"],
                    profile["stock_industry"],
                    profile["stock_industry_short"],
                    profile["share_outstanding_yi"],
                    profile["currency"],
                    symbol,
                ],
            )
            updated = True

        cur.execute(
            """
            select
              m.market_cap,
              m.circulating_shares_yi,
              coalesce(nullif(m.currency, ''), 'USD') as currency,
              latest.trade_date,
              latest.close
            from us_stock_master m
            left join lateral (
              select trade_date, close
              from us_stock_daily_metrics
              where symbol = m.symbol
              order by trade_date desc
              limit 1
            ) latest on true
            where m.symbol = %s
            """,
            [symbol],
        )
        market_context = dict(cur.fetchone() or {})
        decision = resolve_market_cap(
            provider_value_millions=profile.get("market_cap_millions") if profile else None,
            currency=profile.get("currency") if profile and profile.get("currency") else market_context.get("currency"),
            close=market_context.get("close"),
            shares_yi=market_context.get("circulating_shares_yi") or (profile.get("share_outstanding_yi") if profile else None),
        )
        if decision.value_usd is not None:
            market_cap_as_of = today_ny() if decision.source == "finnhub_profile2" else market_context.get("trade_date")
            cur.execute(
                """
                update us_stock_master
                set market_cap = %s,
                    market_cap_source = %s,
                    market_cap_as_of = %s,
                    market_cap_is_estimated = %s,
                    market_cap_validation_status = %s,
                    market_cap_attempted_at = now(),
                    updated_at = now()
                where symbol = %s
                """,
                [
                    decision.value_usd,
                    decision.source,
                    market_cap_as_of,
                    decision.is_estimated,
                    decision.status,
                    symbol,
                ],
            )
            updated = True
        else:
            cur.execute(
                """
                update us_stock_master
                set market_cap_validation_status = %s,
                    market_cap_attempted_at = now(),
                    updated_at = now()
                where symbol = %s
                """,
                [decision.status, symbol],
            )
            updated = True
            if decision.status.startswith("rejected_"):
                detail = f" deviation={decision.deviation_pct:.2f}%" if decision.deviation_pct is not None else ""
                append_log(log_file, f"{symbol}: market cap {decision.status}; existing value preserved{detail}")

    if updated:
        conn.commit()
    return updated


def process_symbol_batches(
    conn: Any,
    symbols: list[str],
    status_path: Path,
    log_file: Path | None,
    *,
    stage: str,
    batch_size: int,
    sleep_seconds: float,
    worker: Any,
    target_date: date | None,
    checkpoint_path: Path,
) -> dict[str, Any]:
    done = 0
    failed = 0
    skipped = 0
    last_symbol = None
    last_error = None
    total = len(symbols)
    update_status(
        status_path,
        {
            "status": "running",
            "stage": stage,
            "target_date": target_date.isoformat() if target_date else None,
            "total_codes": total,
            "done_count": 0,
            "failed_count": 0,
            "skipped_count": 0,
            "progress_pct": 0,
        },
    )
    for index, symbol in enumerate(symbols, start=1):
        last_symbol = symbol
        try:
            ok = bool(worker(symbol))
            if ok:
                done += 1
            else:
                skipped += 1
        except Exception as exc:  # keep batch moving; individual providers are flaky
            failed += 1
            last_error = f"{symbol}: {exc}"
            append_log(log_file, last_error)

        write_json(
            checkpoint_path,
            {
                "updated_at": now_iso(),
                "stage": stage,
                "target_date": target_date.isoformat() if target_date else None,
                "last_symbol": last_symbol,
                "done_count": done,
                "failed_count": failed,
                "skipped_count": skipped,
                "total_codes": total,
            },
        )
        update_status(
            status_path,
            {
                "status": "running",
                "stage": stage,
                "target_date": target_date.isoformat() if target_date else None,
                "total_codes": total,
                "done_count": done,
                "failed_count": failed,
                "skipped_count": skipped,
                "remaining_count": max(total - index, 0),
                "progress_pct": round((index / total) * 100, 2) if total else 100,
                "last_code": last_symbol,
                "last_error": last_error,
            },
        )
        if index % max(batch_size, 1) == 0 and index < total and sleep_seconds > 0:
            append_log(log_file, f"{stage}: processed {index}/{total}, sleeping {sleep_seconds}s")
            time.sleep(sleep_seconds)

    return {
        "target_date": target_date.isoformat() if target_date else None,
        "total_count": total,
        "done_count": done,
        "failed_count": failed,
        "skipped_count": skipped,
        "last_symbol": last_symbol,
        "last_error": last_error,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Update US selection Postgres tables.")
    parser.add_argument("--database-url", default=os.getenv("APP_DB_URL") or os.getenv("PAPER_DB_URL"))
    parser.add_argument("--schema-sql", default=SCHEMA_DEFAULT)
    parser.add_argument("--status-file", default=STATUS_DEFAULT)
    parser.add_argument("--checkpoint-file", default=CHECKPOINT_DEFAULT)
    parser.add_argument("--log-file", default=None)
    parser.add_argument("--summary-json", default=None)
    parser.add_argument("--target-date", default=None)
    parser.add_argument("--symbols", default=None)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--container-name", default=os.getenv("HOSTNAME"))
    parser.add_argument("--skip-completed", action="store_true")

    parser.add_argument("--refresh-universe", action="store_true")
    parser.add_argument("--update-prices", action="store_true")
    parser.add_argument("--update-average-trade", action="store_true")
    parser.add_argument("--update-details", action="store_true")
    parser.add_argument("--full", action="store_true")

    parser.add_argument("--price-batch-size", type=int, default=int(os.getenv("US_SELECTION_PRICE_BATCH_SIZE", "55")))
    parser.add_argument("--price-batch-sleep-seconds", type=float, default=float(os.getenv("US_SELECTION_PRICE_BATCH_SLEEP_SECONDS", "60")))
    parser.add_argument("--massive-batch-size", type=int, default=int(os.getenv("US_SELECTION_MASSIVE_BATCH_SIZE", "5")))
    parser.add_argument("--massive-batch-sleep-seconds", type=float, default=float(os.getenv("US_SELECTION_MASSIVE_BATCH_SLEEP_SECONDS", "60")))
    parser.add_argument("--details-batch-size", type=int, default=int(os.getenv("US_SELECTION_DETAILS_BATCH_SIZE", "12")))
    parser.add_argument("--details-max-batches", type=int, default=int(os.getenv("US_SELECTION_DETAILS_MAX_BATCHES", "60")))
    parser.add_argument("--details-sleep-seconds", type=float, default=float(os.getenv("US_SELECTION_DETAILS_SLEEP_SECONDS", "5")))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.database_url:
        print("APP_DB_URL or PAPER_DB_URL must be set, or pass --database-url.", file=sys.stderr)
        return 2
    schema_path = Path(args.schema_sql)
    status_path = Path(args.status_file)
    checkpoint_path = Path(args.checkpoint_file)
    log_file = Path(args.log_file) if args.log_file else None
    if not schema_path.exists():
        print(f"{schema_path} does not exist.", file=sys.stderr)
        return 2

    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    lanes: list[tuple[str, date | None, Any]] = []
    target_date = parse_date(args.target_date)
    if args.full:
        lanes.extend(
            [
                ("universe", None, refresh_universe),
                ("price", target_date or today_ny(), update_prices),
                ("average-trade", target_date or previous_ny_day(), update_average_trade),
                ("details", None, update_details),
            ]
        )
    else:
        if args.refresh_universe:
            lanes.append(("universe", None, refresh_universe))
        if args.update_prices:
            lanes.append(("price", target_date or today_ny(), update_prices))
        if args.update_average_trade:
            lanes.append(("average-trade", target_date or previous_ny_day(), update_average_trade))
        if args.update_details:
            lanes.append(("details", None, update_details))
    if not lanes:
        print("Pass at least one lane flag, or --full.", file=sys.stderr)
        return 2

    summaries: list[dict[str, Any]] = []
    status = "success"
    with connect_pg(args.database_url) as conn:
        ensure_schema(conn, schema_path)
        for lane, lane_target_date, handler in lanes:
            if args.skip_completed and completed_run_exists(conn, lane, lane_target_date):
                append_log(log_file, f"{lane} skipped: already completed for {lane_target_date}")
                summaries.append({"lane": lane, "target_date": lane_target_date, "skipped_count": 1})
                continue
            run_id = start_run(conn, lane, lane_target_date, args.container_name)
            update_status(
                status_path,
                {
                    "status": "running",
                    "stage": lane,
                    "lane": lane,
                    "target_date": lane_target_date.isoformat() if lane_target_date else None,
                    "started_at": now_iso(),
                    "last_error": None,
                },
            )
            try:
                append_log(log_file, f"Starting lane {lane} target={lane_target_date or '-'}")
                summary = handler(conn, args, status_path, log_file)
                summary = {"lane": lane, "target_date": lane_target_date.isoformat() if lane_target_date else None, **summary}
                finish_run(conn, run_id, "success", summary)
                summaries.append(summary)
                append_log(log_file, f"Finished lane {lane}: {summary}")
            except Exception as exc:
                status = "failed"
                summary = {"lane": lane, "target_date": lane_target_date.isoformat() if lane_target_date else None, "last_error": str(exc)}
                finish_run(conn, run_id, "failed", summary)
                update_status(status_path, {"status": "failed", "stage": lane, "last_error": str(exc), "completed_at": now_iso()})
                append_log(log_file, f"Lane {lane} failed: {exc}")
                raise

    payload = {"ok": status == "success", "status": status, "generated_at": now_iso(), "lanes": summaries}
    update_status(status_path, {"status": status, "stage": "completed", "completed_at": now_iso(), "summary": payload})
    if args.summary_json:
        write_json(Path(args.summary_json), payload)
    return 0 if status == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
