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
    case
      when d.close is null or d.price_diff is null or d.close - d.price_diff <= 0 then null
      else (d.price_diff / (d.close - d.price_diff)) * 100
    end as pct_chg,
    case
      when d.close is null or d.volume is null then null
      else d.close * d.volume
    end as amount,
    row_number() over (
      partition by d.symbol
      order by d.trade_date desc
    ) as rn
  from us_stock_daily_metrics d
  where (%s::date is null or d.trade_date <= %s::date)
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
    max(close) filter (where rn = 6) as close_5d_base,
    max(close) filter (where rn = 21) as close_20d_base,
    avg(close) filter (where rn <= 20) as close_ma20,
    max(close) filter (where rn <= 20) as high20_close,
    min(close) filter (where rn <= 20) as low20_close,
    max(close) filter (where rn <= 40) as high40_close,
    min(close) filter (where rn <= 40) as low40_close,
    max(pct_chg) filter (where rn <= 20) as max_pct_chg_20d,
    max(volume) filter (where rn = 1) as volume_1,
    max(volume) filter (where rn = 2) as volume_2,
    max(volume) filter (where rn = 3) as volume_3,
    max(amount) filter (where rn = 1) as amount_1,
    avg(amount) filter (where rn <= 20) as amount_ma20,
    max(amount) filter (where rn <= 20) as max_amount_20d,
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
    avg(turnover) filter (where rn <= 5) as turnover_ma5,
    count(turnover) filter (where rn <= 4) as turnover_latest4_count
  from ranked
  where rn <= 40
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
    end as lobster_gain_pct,
    p.amount_1 as pre_explosion_amount,
    p.turnover_ma5 as pre_explosion_turnover_ma5,
    case when p.high20_close is null or p.high20_close = 0 or p.close is null then null else (p.close / p.high20_close) - 1 end as pre_explosion_close_to_high20,
    case when p.low20_close is null or p.low20_close = 0 or p.close is null then null else (p.close / p.low20_close) - 1 end as pre_explosion_close_to_low20,
    case when p.high40_close is null or p.high40_close = 0 or p.close is null then null else (p.close / p.high40_close) - 1 end as pre_explosion_close_to_high40,
    case when p.low40_close is null or p.low40_close = 0 or p.close is null then null else (p.close / p.low40_close) - 1 end as pre_explosion_close_to_low40,
    case when p.low40_close is null or p.low40_close = 0 or p.close is null then null else (p.close / p.low40_close) - 1 end as pre_explosion_pct_from_40d_low_close,
    case when p.amount_ma20 is null or p.amount_ma20 = 0 then null else p.amount_1 / p.amount_ma20 end as pre_explosion_amount_ratio20,
    case when p.close is null or p.price_diff_1 is null or p.close - p.price_diff_1 <= 0 then null else (p.price_diff_1 / (p.close - p.price_diff_1)) * 100 end as pre_explosion_pct_chg,
    case when p.close is null or p.close_5d_base is null or p.close_5d_base = 0 then null else (p.close / p.close_5d_base) - 1 end as pre_explosion_pct_chg_5d,
    case when p.close is null or p.close_20d_base is null or p.close_20d_base = 0 then null else (p.close / p.close_20d_base) - 1 end as pre_explosion_pct_chg_20d,
    case when p.close is null or p.close_ma20 is null or p.close_ma20 = 0 then null else (p.close / p.close_ma20) - 1 end as pre_explosion_bias20,
    p.max_pct_chg_20d,
    case when p.amount_ma20 is null or p.amount_ma20 = 0 then null else p.max_amount_20d / p.amount_ma20 end as max_amount_ratio20_20d
  from us_stock_master m
  left join pivoted p on p.symbol = m.symbol
  left join first_seen f on f.symbol = m.symbol
  left join keyworded k on k.symbol = m.symbol
  left join us_stock_favorite_stocks fs on fs.symbol = m.symbol
  where m.is_active = true
    and m.del_flg = false
),
cat_flags as (
  select
    scored.*,
    (
      scored.pre_explosion_amount is not null
      and scored.pre_explosion_close_to_high20 is not null
      and scored.pre_explosion_close_to_low20 is not null
      and scored.pre_explosion_bias20 is not null
      and (
        coalesce(scored.max_pct_chg_20d >= 4, false)
        or coalesce(scored.max_amount_ratio20_20d >= 1.5, false)
      )
      and (
        (
          scored.pre_explosion_amount >= 50000000
          and coalesce(scored.pre_explosion_turnover_ma5, 1) >= 0.5
          and scored.pre_explosion_close_to_high20 >= -0.15
          and scored.pre_explosion_close_to_low20 >= 0.05
          and scored.pre_explosion_bias20 >= -0.08
        )
        or (
          scored.close <= 5
          and scored.pre_explosion_amount >= 5000000
          and coalesce(scored.pre_explosion_turnover_ma5, 1) >= 0.2
          and scored.pre_explosion_close_to_high20 >= -0.15
        )
      )
    ) as cat_candidate,
    (
      scored.pre_explosion_amount >= 50000000
      and coalesce(scored.pre_explosion_turnover_ma5, 1) >= 0.5
      and scored.pre_explosion_close_to_high20 >= -0.15
      and scored.pre_explosion_close_to_low20 >= 0.05
      and scored.pre_explosion_bias20 >= -0.08
    ) as cat_platform_candidate
  from scored
),
cat_scored as (
  select
    cat_flags.*,
    cat_flags.cat_candidate as pre_explosion_flg,
    case
      when not cat_flags.cat_candidate then null
      when coalesce(cat_flags.pre_explosion_pct_chg_5d >= 0.25, false)
        or coalesce(cat_flags.pre_explosion_pct_chg_20d >= 0.60, false)
        or coalesce(cat_flags.pre_explosion_bias20 >= 0.25, false)
      then 'EXTENDED'
      when (coalesce(cat_flags.pre_explosion_pct_chg >= 3, false)
          and coalesce(cat_flags.pre_explosion_amount_ratio20 >= 1.2, false)
          and coalesce(cat_flags.pre_explosion_close_to_high20 >= -0.08, false))
        or (coalesce(cat_flags.pre_explosion_close_to_high20 >= -0.005, false)
          and coalesce(cat_flags.pre_explosion_amount_ratio20 >= 1.0, false))
      then 'TRIGGER'
      else 'WATCH'
    end as pre_explosion_entry_state,
    case when cat_flags.cat_candidate then
      case when cat_flags.cat_platform_candidate then 'platform_washout' else 'low_price_reversal' end
    else null end as pre_explosion_setup_type,
    case when cat_flags.cat_candidate then least(100, greatest(0,
      40
      + case when cat_flags.cat_platform_candidate and cat_flags.pre_explosion_amount >= 50000000 then 12 else 0 end
      + case when cat_flags.cat_platform_candidate and coalesce(cat_flags.pre_explosion_turnover_ma5, 0) >= 0.5 then 10 else 0 end
      + case when cat_flags.pre_explosion_close_to_high20 >= -0.05 then 16 when cat_flags.pre_explosion_close_to_high20 >= -0.15 then 8 else 0 end
      + case when cat_flags.pre_explosion_close_to_low20 >= 0.15 then 10 when cat_flags.pre_explosion_close_to_low20 >= 0.05 then 6 else 0 end
      + case when cat_flags.pre_explosion_bias20 >= 0.02 then 8 when cat_flags.pre_explosion_bias20 >= -0.08 then 4 else 0 end
      + case when coalesce(cat_flags.max_pct_chg_20d >= 4, false) then 8 else 0 end
      + case when coalesce(cat_flags.max_amount_ratio20_20d >= 1.5, false) then 8 else 0 end
      + case when coalesce(cat_flags.pre_explosion_pct_chg between -8 and 0, false) then 6 else 0 end
      + case when not cat_flags.cat_platform_candidate and cat_flags.close <= 5 then 8 else 0 end
    )) else null end as pre_explosion_score,
    case when cat_flags.cat_candidate then array_remove(array[
      case when cat_flags.cat_platform_candidate then 'platform' else 'low_price' end,
      case when cat_flags.cat_platform_candidate and cat_flags.pre_explosion_amount >= 50000000 then 'high_amount' end,
      case when cat_flags.cat_platform_candidate and coalesce(cat_flags.pre_explosion_turnover_ma5, 0) >= 0.5 then 'active_turnover' end,
      case when cat_flags.pre_explosion_close_to_high20 >= -0.05 then 'near_20d_high' else 'within_platform' end,
      case when cat_flags.pre_explosion_close_to_low20 >= 0.15 then 'held_above_low' else 'platform_low_held' end,
      case when cat_flags.pre_explosion_bias20 >= 0.02 then 'above_ma20' else 'ma20_supported' end,
      case when coalesce(cat_flags.max_pct_chg_20d >= 4, false) then 'prior_strong_day' end,
      case when coalesce(cat_flags.max_amount_ratio20_20d >= 1.5, false) then 'prior_volume_expansion' end,
      case when coalesce(cat_flags.pre_explosion_pct_chg between -8 and 0, false) then 'washout' end,
      case when not cat_flags.cat_platform_candidate then 'cheap_price' end,
      case when not cat_flags.cat_platform_candidate then 'liquid_enough' end,
      case when not cat_flags.cat_platform_candidate and coalesce(cat_flags.pre_explosion_pct_chg_20d >= -0.08, false) then 'base_intact' end
    ], null) else array[]::text[] end as pre_explosion_reason_tags
  from cat_flags
),
lobster_ranked as (
  select
    code,
    row_number() over (
      order by lobster_score desc nulls last, volume_1 desc nulls last, code asc
    ) as lobster_rank
  from cat_scored
  where lobster_flg
)
select
  cat_scored.*,
  lobster_ranked.lobster_rank,
  coalesce(average_trade_over_pct >= 30, false) as green_flg,
  coalesce(turnover_compare_pct >= 250, false) as yellow_flg,
  coalesce(turnover_compare_pct <= -40, false) as blue_flg
from cat_scored
left join lobster_ranked on lobster_ranked.code = cat_scored.code
order by code asc
limit %s
"""

US_SELECTION_DATES_SQL = """
select
  trade_date,
  count(*) as row_count
from us_stock_daily_metrics
group by trade_date
order by trade_date desc
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

US_STOCK_SIGNAL_VISUALIZER_SQL = """
with recent_metrics as (
  select
    trade_date,
    close,
    price_diff,
    volume,
    case
      when close is null or volume is null then null
      else close * volume
    end as amount,
    turnover,
    average_trade
  from us_stock_daily_metrics
  where symbol = %s
  order by trade_date desc
  limit %s
),
snapshot_ranks as (
  select
    trade_date,
    max(rank) filter (where list_type = 'cat') as cat_rank,
    max(score) filter (where list_type = 'cat') as cat_score,
    max(rank) filter (where list_type = 'lobster') as lobster_rank,
    max(score) filter (where list_type = 'lobster') as lobster_score
  from us_selection_daily_snapshots
  where code = %s
  group by trade_date
)
select
  m.trade_date,
  m.close,
  m.volume,
  m.amount,
  m.turnover,
  m.average_trade,
  r.cat_rank,
  r.cat_score,
  r.lobster_rank,
  r.lobster_score,
  null::numeric as quant_rank,
  null::numeric as quant_score
from recent_metrics m
left join snapshot_ranks r
  on r.trade_date = m.trade_date
order by m.trade_date asc
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


def _normalize_date(value: Any) -> str | None:
    if value is None or value == "":
        return None
    date_value = str(value).strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_value):
        raise UsSelectionError("invalid_date")
    return date_value


def get_us_selection(*, limit: int = 6000, date: str | None = None) -> dict[str, Any]:
    settings = get_settings()
    try:
        target_date = _normalize_date(date)
        with _connect(settings) as conn:
            with conn.cursor() as cur:
                cur.execute(US_SELECTION_SQL, [target_date, target_date, limit])
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


def get_us_selection_dates(*, limit: int = 260) -> dict[str, Any]:
    settings = get_settings()
    try:
        safe_limit = max(1, min(int(limit), 1000))
        with _connect(settings) as conn:
            with conn.cursor() as cur:
                cur.execute(US_SELECTION_DATES_SQL, [safe_limit])
                rows = [dict(row) for row in cur.fetchall()]
        dates = records_to_json([_numeric_jsonable(row) for row in rows])
        return {
            "rows": len(dates),
            "dates": dates,
            "error": None,
        }
    except Exception as exc:
        return {
            "rows": 0,
            "dates": [],
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


def get_us_stock_signal_visualizer(*, code: str, limit: int = 63) -> dict[str, Any]:
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

                cur.execute(US_STOCK_SIGNAL_VISUALIZER_SQL, [symbol, limit, symbol])
                rows = [dict(row) for row in cur.fetchall()]

        return {
            "stock": records_to_json([_numeric_jsonable(dict(stock))])[0],
            "rows": len(rows),
            "data": records_to_json([_numeric_jsonable(row) for row in rows]),
            "error": None,
        }
    except Exception as exc:
        return {
            "stock": None,
            "rows": 0,
            "data": [],
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
