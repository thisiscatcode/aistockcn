from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from app.config import Settings, get_settings
from app.serializers import records_to_json

try:
    import psycopg
    from psycopg.rows import dict_row
except Exception:  # pragma: no cover - optional dependency availability is environment-specific
    psycopg = None
    dict_row = None


class UsSelectionError(RuntimeError):
    pass


US_SELECTION_SQL = """
with ranked as (
  select
    d.trade_date,
    d.symbol,
    d.close,
    d.price_diff,
    d.volume,
    d.average_trade,
    d.transaction_count,
    d.turnover,
    row_number() over (
      partition by d.symbol
      order by d.trade_date desc
    ) as rn
  from us_stock_daily_metrics d
),
first_seen as (
  select symbol, min(trade_date) as first_trade_date
  from us_stock_daily_metrics
  group by symbol
),
pivoted as (
  select
    symbol,
    max(trade_date) filter (where rn = 1) as trade_date,
    max(close) filter (where rn = 1) as close,
    max(price_diff) filter (where rn = 1) as price_diff_1,
    max(close) filter (where rn = 4) as close_3d_base,
    max(close) filter (where rn = 11) as close_10d_base,
    max(close) filter (where rn = 21) as close_20d_base,
    max(volume) filter (where rn = 1) as volume_1,
    max(volume) filter (where rn = 2) as volume_2,
    max(volume) filter (where rn = 3) as volume_3,
    max(transaction_count) filter (where rn = 1) as transaction_count_1,
    max(average_trade) filter (where rn = 1) as average_trade_1,
    max(average_trade) filter (where rn = 2) as average_trade_2,
    max(average_trade) filter (where rn = 3) as average_trade_3,
    max(average_trade) filter (where rn = 4) as average_trade_4,
    max(average_trade) filter (where rn = 5) as average_trade_5,
    max(average_trade) filter (where rn = 6) as average_trade_6,
    count(average_trade) filter (where rn <= 4) as average_trade_latest4_count,
    max(turnover) filter (where rn = 1) as turnover_1,
    max(turnover) filter (where rn = 2) as turnover_2,
    max(turnover) filter (where rn = 3) as turnover_3,
    count(turnover) filter (where rn <= 4) as turnover_latest4_count
  from ranked
  where rn <= 21
  group by symbol
),
keyworded as (
  select
    symbol,
    array_agg(key_name order by place_num asc, key_name asc) as keywords
  from us_stock_key_map
  group by symbol
),
scored as (
  select
    m.symbol as code,
    m.market as exchange,
    coalesce(nullif(m.stock_name_zh, ''), nullif(m.stock_name, ''), m.symbol) as name,
    m.stock_name,
    m.stock_name_zh,
    m.stock_type,
    m.stock_industry as industry_name,
    m.stock_industry_en,
    m.stock_industry_short,
    coalesce(nullif(m.stock_industry_short, ''), nullif(m.stock_industry, '')) as industry_short_name,
    m.circulating_shares_yi as float_shares_yi,
    m.earnings_per_share,
    m.pe_ratio,
    coalesce(m.ipo_date, f.first_trade_date) as first_trade_date,
    p.trade_date,
    p.close,
    p.volume_1,
    p.volume_2,
    p.volume_3,
    p.transaction_count_1,
    p.average_trade_1,
    p.average_trade_2,
    p.average_trade_3,
    p.average_trade_4,
    p.average_trade_5,
    p.average_trade_6,
    p.turnover_1,
    p.turnover_2,
    p.turnover_3,
    case
      when p.close is null or p.close_3d_base is null or p.close_3d_base = 0 then null
      else ((p.close / p.close_3d_base) - 1) * 100
    end as pct_3d,
    case
      when p.close is null or p.close_10d_base is null or p.close_10d_base = 0 then null
      else ((p.close / p.close_10d_base) - 1) * 100
    end as pct_10d,
    case
      when p.close is null or p.close_20d_base is null or p.close_20d_base = 0 then null
      else ((p.close / p.close_20d_base) - 1) * 100
    end as pct_20d,
    case
      when p.average_trade_1 is null
        or p.average_trade_2 is null
        or p.average_trade_3 is null
        or p.average_trade_4 is null
        or p.average_trade_5 is null
        or p.average_trade_6 is null
        or ((p.average_trade_2 + p.average_trade_3 + p.average_trade_4 + p.average_trade_5 + p.average_trade_6) / 5) <= 0
      then null
      else round(
        (
          (p.average_trade_1 - ((p.average_trade_2 + p.average_trade_3 + p.average_trade_4 + p.average_trade_5 + p.average_trade_6) / 5))
          / ((p.average_trade_2 + p.average_trade_3 + p.average_trade_4 + p.average_trade_5 + p.average_trade_6) / 5)
        ) * 100,
        0
      )
    end as average_trade_over_pct,
    case
      when p.turnover_1 is null or p.turnover_2 is null or p.turnover_2 = 0 then null
      else round(((p.turnover_1 - p.turnover_2) / p.turnover_2) * 100, 0)
    end as turnover_compare_pct,
    coalesce(k.keywords, array[]::text[]) as keywords,
    (fs.symbol is not null) as fav_flg,
    fs.display_num,
    case
      when p.close is null
        or p.price_diff_1 is null
        or p.close - p.price_diff_1 <= 0
        or p.volume_1 is null
        or p.volume_2 is null
        or p.volume_3 is null
        or not (p.volume_3 < p.volume_2 and p.volume_2 < p.volume_1)
        or not (p.turnover_1 is null or p.turnover_1 <= 10)
        or (p.price_diff_1 / (p.close - p.price_diff_1)) * 100 <= 0
        or (p.price_diff_1 / (p.close - p.price_diff_1)) * 100 > 10
      then false
      else true
    end as lobster_flg,
    case
      when p.turnover_1 is not null then p.turnover_1
      when m.circulating_shares_yi is not null and m.circulating_shares_yi > 0 and p.volume_1 is not null
      then (p.volume_1 / (m.circulating_shares_yi * 100000000)) * 100
      else null
    end as lobster_score,
    case
      when p.close is null or p.price_diff_1 is null or p.close - p.price_diff_1 <= 0 then null
      else (p.price_diff_1 / (p.close - p.price_diff_1)) * 100
    end as lobster_gain_pct
  from us_stock_master m
  left join pivoted p on p.symbol = m.symbol
  left join first_seen f on f.symbol = m.symbol
  left join keyworded k on k.symbol = m.symbol
  left join us_stock_favorite_stocks fs on fs.symbol = m.symbol
  where m.is_active = true
    and m.del_flg = false
),
lobster_ranked as (
  select
    code,
    row_number() over (
      order by lobster_score desc nulls last, volume_1 desc nulls last, code asc
    ) as lobster_rank
  from scored
  where lobster_flg
)
select
  scored.*,
  lobster_ranked.lobster_rank,
  coalesce(average_trade_over_pct >= 30, false) as green_flg,
  coalesce(turnover_compare_pct >= 250, false) as yellow_flg,
  coalesce(turnover_compare_pct <= -40, false) as blue_flg
from scored
left join lobster_ranked on lobster_ranked.code = scored.code
order by code asc
limit %s
"""

US_STOCK_DETAIL_HISTORY_SQL = """
select
  trade_date,
  close,
  price_diff,
  volume,
  average_trade,
  transaction_count,
  turnover
from us_stock_daily_metrics
where symbol = %s
order by trade_date desc
limit %s
"""


def _connect(settings: Settings, *, read_only: bool = True):
    if not settings.paper_db_url:
        raise UsSelectionError("PAPER_DB_URL is not configured")
    if psycopg is None or dict_row is None:
        raise UsSelectionError("psycopg is not installed")
    options = "-c default_transaction_read_only=on" if read_only else None
    kwargs: dict[str, Any] = {
        "row_factory": dict_row,
        "connect_timeout": 5,
    }
    if options:
        kwargs["options"] = options
    return psycopg.connect(settings.paper_db_url, **kwargs)


def _numeric_jsonable(row: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in row.items():
        result[key] = float(value) if isinstance(value, Decimal) else value
    return result


def get_us_selection(*, limit: int = 6000) -> dict[str, Any]:
    settings = get_settings()
    try:
        with _connect(settings) as conn:
            with conn.cursor() as cur:
                cur.execute(US_SELECTION_SQL, [limit])
                rows = [dict(row) for row in cur.fetchall()]
        selections = records_to_json([_numeric_jsonable(row) for row in rows])
        latest_date = max((row.get("trade_date") for row in selections if row.get("trade_date")), default=None)
        return {
            "rows": len(selections),
            "latest_date": latest_date,
            "selections": selections,
            "error": None,
        }
    except Exception as exc:
        return {
            "rows": 0,
            "latest_date": None,
            "selections": [],
            "error": str(exc),
        }


def _normalize_symbol(value: Any) -> str:
    symbol = str(value or "").strip().upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,14}", symbol):
        raise UsSelectionError("invalid_symbol")
    return symbol


def get_us_stock_detail(*, code: str, limit: int = 260) -> dict[str, Any]:
    settings = get_settings()
    try:
        symbol = _normalize_symbol(code)
        limit = max(1, min(int(limit), 1000))

        with _connect(settings) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select
                      symbol as code,
                      market as exchange,
                      coalesce(nullif(stock_name_zh, ''), nullif(stock_name, ''), symbol) as name,
                      stock_name,
                      stock_name_zh,
                      stock_type,
                      stock_industry as industry_name,
                      stock_industry as stock_industry,
                      stock_industry_en,
                      stock_industry_short,
                      coalesce(nullif(stock_industry_short, ''), nullif(stock_industry, '')) as industry_short_name,
                      circulating_shares_yi as float_shares_yi,
                      earnings_per_share,
                      pe_ratio,
                      ipo_date as first_trade_date,
                      currency,
                      daily_updated_at,
                      details_updated_at
                    from us_stock_master
                    where symbol = %s
                      and is_active = true
                      and del_flg = false
                    """,
                    [symbol],
                )
                stock = cur.fetchone()
                if not stock:
                    raise UsSelectionError("stock_not_found")

                cur.execute(
                    """
                    select key_name
                    from us_stock_key_map
                    where symbol = %s
                    order by place_num asc, key_name asc
                    """,
                    [symbol],
                )
                keywords = [row["key_name"] for row in cur.fetchall()]

                cur.execute(US_STOCK_DETAIL_HISTORY_SQL, [symbol, limit])
                history = [dict(row) for row in cur.fetchall()]

        return {
            "stock": records_to_json([_numeric_jsonable(dict(stock))])[0],
            "keywords": keywords,
            "history": records_to_json([_numeric_jsonable(row) for row in history]),
            "shareholder_research": [],
            "rows": len(history),
            "error": None,
        }
    except Exception as exc:
        return {
            "stock": None,
            "keywords": [],
            "history": [],
            "shareholder_research": [],
            "rows": 0,
            "error": str(exc),
        }


def save_us_favorite_stocks(payload: dict[str, object]) -> dict[str, Any]:
    raw_favorites = payload.get("favorites")
    if not isinstance(raw_favorites, list):
        raise UsSelectionError("invalid_favorites")

    symbols: list[str] = []
    seen: set[str] = set()
    for item in raw_favorites:
        symbol = ""
        if isinstance(item, str):
            symbol = item
        elif isinstance(item, dict):
            symbol = str(item.get("symbol") or item.get("code") or "")
        symbol = symbol.strip().upper()
        if not symbol:
            raise UsSelectionError("invalid_favorite_item")
        if symbol in seen:
            raise UsSelectionError("duplicate_favorite")
        seen.add(symbol)
        symbols.append(symbol)

    settings = get_settings()
    with _connect(settings, read_only=False) as conn:
        with conn.cursor() as cur:
            if symbols:
                cur.execute(
                    "select symbol from us_stock_master where symbol = any(%s)",
                    [symbols],
                )
                existing = {str(row["symbol"]).upper() for row in cur.fetchall()}
                missing = [symbol for symbol in symbols if symbol not in existing]
                if missing:
                    raise UsSelectionError("stock_not_found")
            cur.execute("delete from us_stock_favorite_stocks")
            for index, symbol in enumerate(symbols, start=1):
                cur.execute(
                    """
                    insert into us_stock_favorite_stocks (symbol, display_num, created_at, updated_at)
                    values (%s, %s, now(), now())
                    on conflict (symbol) do update set
                      display_num = excluded.display_num,
                      updated_at = now()
                    """,
                    [symbol, index],
                )
        conn.commit()
    return {"ok": True, "rows": len(symbols)}
