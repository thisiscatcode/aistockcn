from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.config import Settings, get_settings
from app.serializers import records_to_json

try:
    import psycopg
    from psycopg.rows import dict_row
except Exception:  # pragma: no cover - exercised only when optional dependency is missing
    psycopg = None
    dict_row = None


class FeiKeywordError(RuntimeError):
    pass


KEYWORD_LIST_SQL = """
select
  k.id,
  k.key_code,
  k.key_name,
  k.fav_flg,
  k.display_num,
  k.created_at,
  k.updated_at,
  count(m.code) as mapped_stock_count
from stock_keywords k
left join stock_key_map m
  on m.key_name = k.key_name
group by
  k.id,
  k.key_code,
  k.key_name,
  k.fav_flg,
  k.display_num,
  k.created_at,
  k.updated_at
order by
  k.fav_flg desc,
  k.display_num asc nulls last,
  k.key_name asc
"""

FAVORITE_KEYWORD_SQL = """
select
  id,
  key_code,
  key_name,
  fav_flg,
  display_num,
  created_at,
  updated_at
from stock_keywords
where fav_flg = true
order by display_num asc nulls last, key_name asc
"""


def _connect(settings: Settings):
    if not settings.paper_db_url:
        raise FeiKeywordError("PAPER_DB_URL is not configured")
    if psycopg is None or dict_row is None:
        raise FeiKeywordError("psycopg is not installed")
    return psycopg.connect(settings.paper_db_url, row_factory=dict_row, connect_timeout=5)


def _jsonable(row: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in row.items():
        result[key] = float(value) if isinstance(value, Decimal) else value
    return result


def normalize_keyword_ids(raw_ids: Any) -> list[int]:
    if not isinstance(raw_ids, list):
        raise FeiKeywordError("invalid_keyword_ids")
    keyword_ids: list[int] = []
    seen: set[int] = set()
    for raw_id in raw_ids:
        if isinstance(raw_id, bool) or not isinstance(raw_id, int) or raw_id < 1:
            raise FeiKeywordError("invalid_keyword_ids")
        if raw_id in seen:
            raise FeiKeywordError("duplicate_keyword_id")
        seen.add(raw_id)
        keyword_ids.append(raw_id)
    return keyword_ids


def list_keywords(*, favorites_only: bool = False) -> dict[str, Any]:
    settings = get_settings()
    try:
        with _connect(settings) as conn:
            with conn.cursor() as cur:
                cur.execute(FAVORITE_KEYWORD_SQL if favorites_only else KEYWORD_LIST_SQL)
                rows = [dict(row) for row in cur.fetchall()]
        keywords = records_to_json([_jsonable(row) for row in rows])
        return {"rows": len(keywords), "keywords": keywords, "error": None}
    except Exception as exc:
        return {"rows": 0, "keywords": [], "error": str(exc)}


def replace_favorite_keywords(raw_keyword_ids: Any) -> dict[str, Any]:
    keyword_ids = normalize_keyword_ids(raw_keyword_ids)
    settings = get_settings()
    with _connect(settings) as conn:
        try:
            with conn.cursor() as cur:
                cur.execute("select id from stock_keywords order by id for update")
                existing_ids = {int(row["id"]) for row in cur.fetchall()}
                if any(keyword_id not in existing_ids for keyword_id in keyword_ids):
                    raise FeiKeywordError("keyword_not_found")
                cur.execute(
                    """
                    update stock_keywords
                    set fav_flg = false,
                        display_num = null,
                        updated_at = now()
                    where fav_flg = true
                       or display_num is not null
                    """
                )
                for display_num, keyword_id in enumerate(keyword_ids, start=1):
                    cur.execute(
                        """
                        update stock_keywords
                        set fav_flg = true,
                            display_num = %s,
                            updated_at = now()
                        where id = %s
                        """,
                        [display_num, keyword_id],
                    )
                cur.execute(KEYWORD_LIST_SQL)
                rows = [dict(row) for row in cur.fetchall()]
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    keywords = records_to_json([_jsonable(row) for row in rows])
    return {"ok": True, "rows": len(keywords), "keywords": keywords, "error": None}
