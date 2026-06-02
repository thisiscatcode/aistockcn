from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from app.config import Settings, get_settings
from app.serializers import records_to_json
from app.services.fei_db_sync import get_published_trade_date

try:
    import psycopg
    from psycopg.rows import dict_row
except Exception:  # pragma: no cover - exercised only when optional dependency is missing
    psycopg = None
    dict_row = None


class FeiSelectionError(RuntimeError):
    pass


SELECTION_SQL = """
with ranked as (
  select
    m.trade_date,
    m.code,
    m.exchange,
    m.close,
    m.volume,
    m.amount,
    m.average_trade,
    m.turnover,
    row_number() over (
      partition by m.code, m.exchange
      order by m.trade_date desc
    ) as rn
  from stock_daily_metrics m
  where (%s::date is null or m.trade_date <= %s::date)
),
first_seen as (
  select
    code,
    exchange,
    min(trade_date) as first_trade_date
  from stock_daily_metrics
  group by code, exchange
),
pivoted as (
  select
    code,
    exchange,
    max(trade_date) filter (where rn = 1) as trade_date,
    max(close) filter (where rn = 1) as close,
    max(close) filter (where rn = 4) as close_3d_base,
    max(close) filter (where rn = 11) as close_10d_base,
    max(close) filter (where rn = 21) as close_20d_base,
    max(volume) filter (where rn = 1) as volume_1,
    max(volume) filter (where rn = 2) as volume_2,
    max(volume) filter (where rn = 3) as volume_3,
    max(amount) filter (where rn = 1) as amount_1,
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
  group by code, exchange
),
keyworded as (
  select
    code,
    exchange,
    array_agg(key_name order by place_num asc, key_name asc) as keywords
  from stock_key_map
  group by code, exchange
),
shareholder_latest as (
  select distinct on (code, exchange)
    code,
    exchange,
    report_date as shareholder_report_date,
    holder_total_num as shareholder_total_num,
    hold_focus as shareholder_hold_focus
  from stock_shareholder_research
  order by code, exchange, report_date desc
),
scored as (
  select
    p.*,
    sm.name,
    sm.float_shares,
    sm.float_shares_yi,
    sm.industry_code,
    sm.industry_name,
    sm.industry_short_name,
    sm.earnings_per_share,
    sh.shareholder_report_date,
    sh.shareholder_total_num,
    sh.shareholder_hold_focus,
    case
      when p.close is null
        or p.close_3d_base is null
        or p.close_3d_base <= 0
        or p.volume_1 is null
        or p.volume_2 is null
        or p.volume_3 is null
        or not (p.volume_3 < p.volume_2 and p.volume_2 < p.volume_1)
        or p.turnover_1 is null
        or p.turnover_2 is null
        or p.turnover_3 is null
        or not (p.turnover_1 <= 10 and p.turnover_2 <= 10 and p.turnover_3 <= 10)
        or ((p.close / p.close_3d_base) - 1) * 100 <= 0
        or ((p.close / p.close_3d_base) - 1) * 100 > 10
      then false
      else true
    end as lobster_flg,
    case
      when p.close is null
        or p.close <= 0
        or p.amount_1 is null
        or sm.float_shares is null
        or sm.float_shares <= 0
      then null
      else (p.amount_1 / (p.close * sm.float_shares)) * 100
    end as lobster_score,
    case
      when p.close is null or p.close_3d_base is null or p.close_3d_base <= 0 then null
      else ((p.close / p.close_3d_base) - 1) * 100
    end as lobster_gain_pct
  from pivoted p
  left join stock_master sm
    on sm.code = p.code
   and sm.exchange = p.exchange
  left join shareholder_latest sh
    on sh.code = p.code
   and sh.exchange = p.exchange
),
signaled as (
  select
    s.*,
    case
      when s.average_trade_1 is null
        or s.average_trade_2 is null
        or s.average_trade_3 is null
        or s.average_trade_4 is null
        or s.average_trade_5 is null
        or s.average_trade_6 is null
        or ((s.average_trade_2 + s.average_trade_3 + s.average_trade_4 + s.average_trade_5 + s.average_trade_6) / 5) <= 0
      then null
      else round(
        (
          (
            s.average_trade_1 - ((s.average_trade_2 + s.average_trade_3 + s.average_trade_4 + s.average_trade_5 + s.average_trade_6) / 5)
          )
          / ((s.average_trade_2 + s.average_trade_3 + s.average_trade_4 + s.average_trade_5 + s.average_trade_6) / 5)
        ) * 100,
        0
      )
    end as average_trade_over_pct,
    case
      when s.turnover_1 is null
        or s.turnover_2 is null
        or s.turnover_2 = 0
      then null
      else round(((s.turnover_1 - s.turnover_2) / s.turnover_2) * 100, 0)
    end as turnover_compare_pct
  from scored s
),
selection_ready as (
  select
    s.*,
    coalesce(s.average_trade_over_pct >= 30, false) as green_flg,
    coalesce(s.turnover_compare_pct >= 250, false) as yellow_flg,
    coalesce(s.turnover_compare_pct <= -40, false) as blue_flg
  from signaled s
  where s.average_trade_latest4_count > 0
    and s.turnover_latest4_count > 0
),
lobster_ranked as (
  select
    code,
    exchange,
    lobster_score,
    lobster_gain_pct,
    row_number() over (
      order by lobster_score desc nulls last, amount_1 desc nulls last, code asc, exchange asc
    ) as lobster_rank
  from selection_ready
  where lobster_flg
)
select
  s.code,
  s.exchange,
  s.name,
  s.close,
  s.volume_1,
  s.volume_2,
  s.volume_3,
  s.amount_1,
  s.average_trade_1,
  s.average_trade_2,
  s.average_trade_3,
  s.average_trade_4,
  s.average_trade_5,
  s.turnover_1,
  s.turnover_2,
  s.turnover_3,
  case
    when s.close is null or s.close_3d_base is null or s.close_3d_base = 0 then null
    else ((s.close / s.close_3d_base) - 1) * 100
  end as pct_3d,
  case
    when s.close is null or s.close_10d_base is null or s.close_10d_base = 0 then null
    else ((s.close / s.close_10d_base) - 1) * 100
  end as pct_10d,
  case
    when s.close is null or s.close_20d_base is null or s.close_20d_base = 0 then null
    else ((s.close / s.close_20d_base) - 1) * 100
  end as pct_20d,
  s.float_shares_yi,
  s.shareholder_report_date,
  s.shareholder_total_num,
  s.shareholder_hold_focus,
  s.industry_code,
  s.industry_name,
  s.industry_short_name,
  s.earnings_per_share,
  coalesce(k.keywords, array[]::text[]) as keywords,
  (fs.code is not null) as fav_flg,
  fs.display_num,
  s.trade_date,
  first_seen.first_trade_date,
  s.lobster_flg,
  lr.lobster_rank,
  lr.lobster_score,
  lr.lobster_gain_pct,
  s.green_flg,
  s.yellow_flg,
  s.blue_flg,
  s.average_trade_over_pct,
  s.turnover_compare_pct
from selection_ready s
left join first_seen
  on first_seen.code = s.code
 and first_seen.exchange = s.exchange
left join keyworded k
  on k.code = s.code
 and k.exchange = s.exchange
left join stock_favorite_stocks fs
  on fs.code = s.code
 and fs.exchange = s.exchange
left join lobster_ranked lr
  on lr.code = s.code
 and lr.exchange = s.exchange
order by s.code asc, s.exchange asc
limit %s
"""

STOCK_DETAIL_HISTORY_SQL = """
select
  trade_date,
  close,
  volume,
  average_trade,
  turnover
from stock_daily_metrics
where code = %s
  and exchange = %s
  and (%s::date is null or trade_date <= %s::date)
order by trade_date desc
limit %s
"""

STOCK_DETAIL_SHAREHOLDER_SQL = """
select
  report_date,
  holder_total_num,
  total_num_ratio,
  avg_free_shares,
  avg_freeshares_ratio,
  hold_focus
from stock_shareholder_research
where code = %s
  and exchange = %s
order by report_date desc
limit %s
"""


def _connect(settings: Settings, *, read_only: bool = True):
    if not settings.paper_db_url:
        raise FeiSelectionError("PAPER_DB_URL is not configured")
    if psycopg is None or dict_row is None:
        raise FeiSelectionError("psycopg is not installed")
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


def get_fei_selection(*, limit: int = 6000) -> dict[str, Any]:
    settings = get_settings()
    try:
        published_trade_date = get_published_trade_date()
        with _connect(settings) as conn:
            with conn.cursor() as cur:
                cur.execute(SELECTION_SQL, [published_trade_date, published_trade_date, limit])
                rows = [dict(row) for row in cur.fetchall()]
        selections = records_to_json([_numeric_jsonable(row) for row in rows])
        latest_date = max((row.get("trade_date") for row in selections if row.get("trade_date")), default=None)
        return {
            "rows": len(selections),
            "latest_date": latest_date,
            "published_trade_date": published_trade_date,
            "selections": selections,
            "error": None,
        }
    except Exception as exc:
        return {
            "rows": 0,
            "latest_date": None,
            "published_trade_date": None,
            "selections": [],
            "error": str(exc),
        }


def _normalize_code(value: Any) -> str:
    code = str(value or "").strip()
    if not re.fullmatch(r"\d{6}", code):
        raise FeiSelectionError("invalid_code")
    return code


def _normalize_exchange(value: Any) -> str | None:
    if value is None:
        return None
    exchange = str(value or "").strip().lower()
    if not exchange:
        return None
    if exchange not in {"sh", "sz"}:
        raise FeiSelectionError("invalid_exchange")
    return exchange


def get_fei_stock_detail(*, code: str, exchange: str | None = None, limit: int = 260) -> dict[str, Any]:
    settings = get_settings()
    try:
        normalized_code = _normalize_code(code)
        normalized_exchange = _normalize_exchange(exchange)
        limit = max(1, min(int(limit), 1000))
        published_trade_date = get_published_trade_date()

        with _connect(settings) as conn:
            with conn.cursor() as cur:
                if normalized_exchange:
                    cur.execute(
                        """
                        select *
                        from stock_master
                        where code = %s
                          and exchange = %s
                        """,
                        [normalized_code, normalized_exchange],
                    )
                else:
                    cur.execute(
                        """
                        select *
                        from stock_master
                        where code = %s
                        order by exchange asc
                        """,
                        [normalized_code],
                    )
                matches = [dict(row) for row in cur.fetchall()]
                if not matches:
                    raise FeiSelectionError("stock_not_found")
                if len(matches) > 1:
                    raise FeiSelectionError("ambiguous_exchange")

                stock = matches[0]
                resolved_exchange = str(stock.get("exchange") or "")

                cur.execute(
                    """
                    select key_name
                    from stock_key_map
                    where code = %s
                      and exchange = %s
                    order by place_num asc, key_name asc
                    """,
                    [normalized_code, resolved_exchange],
                )
                keywords = [row["key_name"] for row in cur.fetchall()]

                cur.execute(
                    STOCK_DETAIL_HISTORY_SQL,
                    [normalized_code, resolved_exchange, published_trade_date, published_trade_date, limit],
                )
                history = [dict(row) for row in cur.fetchall()]

                cur.execute(STOCK_DETAIL_SHAREHOLDER_SQL, [normalized_code, resolved_exchange, 10])
                shareholder_research = [dict(row) for row in cur.fetchall()]

        return {
            "stock": records_to_json([_numeric_jsonable(stock)])[0],
            "keywords": keywords,
            "history": records_to_json([_numeric_jsonable(row) for row in history]),
            "shareholder_research": records_to_json([_numeric_jsonable(row) for row in shareholder_research]),
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


def _normalize_stock_ref(payload: dict[str, Any]) -> tuple[str, str]:
    code = str(payload.get("code") or "").strip()
    exchange = str(payload.get("exchange") or "").strip().lower()
    if not re.fullmatch(r"\d{6}", code):
        raise FeiSelectionError("invalid_code")
    if exchange not in {"sh", "sz"}:
        raise FeiSelectionError("invalid_exchange")
    return code, exchange


def _normalize_favorite_payload(payload: dict[str, Any]) -> tuple[str, str, bool]:
    code, exchange = _normalize_stock_ref(payload)
    favorite = payload.get("favorite")
    if not isinstance(favorite, bool):
        raise FeiSelectionError("invalid_favorite")
    return code, exchange, favorite


def _normalize_favorites(payload: dict[str, Any]) -> list[tuple[str, str]]:
    favorites = payload.get("favorites")
    if not isinstance(favorites, list):
        raise FeiSelectionError("invalid_favorites")

    refs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in favorites:
        if not isinstance(item, dict):
            raise FeiSelectionError("invalid_favorite_item")
        ref = _normalize_stock_ref(item)
        if ref in seen:
            raise FeiSelectionError("duplicate_favorite")
        seen.add(ref)
        refs.append(ref)
    return refs


def _validate_stock_refs(cur: Any, refs: list[tuple[str, str]]) -> None:
    if not refs:
        return
    values_sql = ", ".join(["(%s, %s)"] * len(refs))
    params = [value for ref in refs for value in ref]
    cur.execute(
        f"""
        with requested(code, exchange) as (
          values {values_sql}
        )
        select r.code, r.exchange
        from requested r
        left join stock_master sm
          on sm.code = r.code
         and sm.exchange = r.exchange
        where sm.code is null
        limit 1
        """,
        params,
    )
    if cur.fetchone():
        raise FeiSelectionError("stock_not_found")


def _renumber_favorites(cur: Any) -> None:
    cur.execute(
        """
        with ordered as (
          select
            code,
            exchange,
            row_number() over (
              order by display_num asc nulls last, updated_at desc, code asc, exchange asc
            ) as next_display_num
          from stock_favorite_stocks
        )
        update stock_favorite_stocks fs
           set display_num = ordered.next_display_num,
               updated_at = now()
        from ordered
        where fs.code = ordered.code
          and fs.exchange = ordered.exchange
        """
    )


def update_favorite_stock(payload: dict[str, Any]) -> dict[str, Any]:
    code, exchange, favorite = _normalize_favorite_payload(payload)
    settings = get_settings()
    with _connect(settings, read_only=False) as conn:
        try:
            with conn.cursor() as cur:
                _validate_stock_refs(cur, [(code, exchange)])
                cur.execute("select pg_advisory_xact_lock(hashtext('stock_favorite_stocks'))")
                if favorite:
                    cur.execute(
                        """
                        delete from stock_favorite_stocks
                        where code = %s
                          and exchange = %s
                        """,
                        [code, exchange],
                    )
                    cur.execute(
                        """
                        update stock_favorite_stocks
                           set display_num = display_num + 1
                         where display_num is not null
                        """
                    )
                    cur.execute(
                        """
                        insert into stock_favorite_stocks (code, exchange, display_num, created_at, updated_at)
                        values (%s, %s, 1, now(), now())
                        """,
                        [code, exchange],
                    )
                else:
                    cur.execute(
                        """
                        delete from stock_favorite_stocks
                        where code = %s
                          and exchange = %s
                        """,
                        [code, exchange],
                    )
                _renumber_favorites(cur)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return {"ok": True, "code": code, "exchange": exchange, "favorite": favorite, "error": None}


def replace_favorite_stocks(payload: dict[str, Any]) -> dict[str, Any]:
    refs = _normalize_favorites(payload)
    settings = get_settings()
    with _connect(settings, read_only=False) as conn:
        try:
            with conn.cursor() as cur:
                _validate_stock_refs(cur, refs)
                cur.execute("select pg_advisory_xact_lock(hashtext('stock_favorite_stocks'))")
                cur.execute("delete from stock_favorite_stocks")
                if refs:
                    cur.executemany(
                        """
                        insert into stock_favorite_stocks (code, exchange, display_num, created_at, updated_at)
                        values (%s, %s, %s, now(), now())
                        """,
                        [(code, exchange, index + 1) for index, (code, exchange) in enumerate(refs)],
                    )
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    return {
        "ok": True,
        "rows": len(refs),
        "favorites": [
            {"code": code, "exchange": exchange, "display_num": index + 1}
            for index, (code, exchange) in enumerate(refs)
        ],
        "error": None,
    }


def save_favorite_stocks(payload: dict[str, Any]) -> dict[str, Any]:
    if "favorites" in payload:
        return replace_favorite_stocks(payload)
    return update_favorite_stock(payload)
