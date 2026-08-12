from __future__ import annotations

import threading
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from app.config import Settings, get_settings
from app.serializers import records_to_json
from app.services.files import read_json, write_json_atomic
from app.services.us_selection import UsSelectionError, _connect, get_us_selection

try:
    from psycopg.types.json import Jsonb
except Exception:  # pragma: no cover - exercised only when optional dependency is missing
    Jsonb = None


SNAPSHOT_LIST_TYPES = ("lobster", "cat")
SNAPSHOT_LIMIT = 50
SNAPSHOT_STATE_FILE = "us_selection_snapshot_state.json"
SCHEDULER_TIMEZONE = "America/New_York"
SCHEDULER_POLL_SECONDS = 60
SNAPSHOT_COVERAGE_LIMIT = 60

CAT_EARLY_MAX_DAILY_GAIN_PCT = 2
CAT_EARLY_MAX_5D_GAIN = 0.04
CAT_EARLY_MAX_20D_GAIN = 0.10
CAT_EARLY_MIN_20D_GAIN = -0.20
CAT_EARLY_MAX_BIAS20 = 0.06
CAT_EARLY_MAX_FROM_40D_LOW = 0.18
CAT_EARLY_MAX_FROM_20D_LOW = 0.16
CAT_EARLY_MIN_TO_20D_HIGH = -0.16
CAT_EARLY_MAX_TO_20D_HIGH = -0.03

_STOP_EVENT: threading.Event | None = None
_THREAD: threading.Thread | None = None
_THREAD_LOCK = threading.Lock()
_RUN_LOCK = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _state_path(settings: Settings | None = None) -> Path:
    return (settings or get_settings()).run_dir / SNAPSHOT_STATE_FILE


def _read_state(settings: Settings | None = None) -> dict[str, Any]:
    return read_json(_state_path(settings))


def _write_state(payload: dict[str, Any], settings: Settings | None = None) -> None:
    write_json_atomic(_state_path(settings), payload, ensure_ascii=True)


def _date_text(value: Any) -> str | None:
    if value is None:
        return None
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return pd.Timestamp(parsed).date().isoformat()


def _normalize_date(value: Any) -> str:
    normalized = _date_text(value)
    if not normalized:
        raise UsSelectionError("invalid_snapshot_date")
    return normalized


def _schema_sql_path(settings: Settings | None = None) -> Path:
    return (settings or get_settings()).project_root / "scripts" / "create_us_selection_snapshots.sql"


def ensure_snapshot_schema(conn: Any, settings: Settings | None = None) -> None:
    conn.execute(_schema_sql_path(settings).read_text(encoding="utf-8"))


def _jsonable(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    try:
        missing = pd.isna(value)
    except (TypeError, ValueError):
        missing = False
    if isinstance(missing, bool) and missing:
        return None
    return value


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if pd.notna(number) else None


def _normalized_code(value: Any) -> str:
    return str(value or "").strip().upper()


def _exchange_code(value: Any) -> str:
    return str(value or "").strip().upper()


def _row_key(row: dict[str, Any]) -> tuple[str, str]:
    return _normalized_code(row.get("code")), _exchange_code(row.get("exchange"))


def _raw_reason_tag_set(value: Any) -> set[str]:
    if isinstance(value, list):
        return {str(item).strip() for item in value if str(item).strip()}
    if isinstance(value, str):
        return {part.strip() for part in value.split("|") if part.strip()}
    return set()


def _exceeds(value: Any, maximum: float) -> bool:
    number = _as_number(value)
    return number is not None and number > maximum


def _below(value: Any, minimum: float) -> bool:
    number = _as_number(value)
    return number is not None and number < minimum


def is_cat_early_candidate(row: dict[str, Any]) -> bool:
    if not row.get("pre_explosion_flg") or row.get("pre_explosion_entry_state") != "WATCH":
        return False
    if _exceeds(row.get("pre_explosion_pct_chg"), CAT_EARLY_MAX_DAILY_GAIN_PCT):
        return False
    if _exceeds(row.get("pre_explosion_pct_chg_5d"), CAT_EARLY_MAX_5D_GAIN):
        return False
    if _exceeds(row.get("pre_explosion_pct_chg_20d"), CAT_EARLY_MAX_20D_GAIN):
        return False
    if _below(row.get("pre_explosion_pct_chg_20d"), CAT_EARLY_MIN_20D_GAIN):
        return False
    if _exceeds(row.get("pre_explosion_bias20"), CAT_EARLY_MAX_BIAS20):
        return False
    if _exceeds(row.get("pre_explosion_pct_from_40d_low_close"), CAT_EARLY_MAX_FROM_40D_LOW):
        return False
    if _exceeds(row.get("pre_explosion_close_to_low20"), CAT_EARLY_MAX_FROM_20D_LOW):
        return False
    if _below(row.get("pre_explosion_close_to_high20"), CAT_EARLY_MIN_TO_20D_HIGH):
        return False
    return not _exceeds(row.get("pre_explosion_close_to_high20"), CAT_EARLY_MAX_TO_20D_HIGH)


def cat_early_rank_score(row: dict[str, Any]) -> float:
    tags = _raw_reason_tag_set(row.get("pre_explosion_reason_tags"))
    score = _as_number(row.get("pre_explosion_score")) or 0.0
    if "washout" in tags or "pre_breakout_rest" in tags:
        score += 25
    if "short_structure_ok" in tags or "base_intact" in tags:
        score += 8
    if "within_platform" in tags or "range_recovery" in tags:
        score += 8
    if "near_20d_high" in tags or "near_range_high" in tags:
        score -= 5

    daily_gain = _as_number(row.get("pre_explosion_pct_chg"))
    if daily_gain is not None:
        if -5 <= daily_gain <= 0:
            score += 10
        elif 0 < daily_gain <= 1.5:
            score += 4
        elif daily_gain > 2:
            score -= 10

    score -= max(_as_number(row.get("pre_explosion_pct_chg_5d")) or 0.0, 0.0) * 130
    score -= max(_as_number(row.get("pre_explosion_pct_chg_20d")) or 0.0, 0.0) * 90
    score -= max(_as_number(row.get("pre_explosion_bias20")) or 0.0, 0.0) * 130
    score -= max(_as_number(row.get("pre_explosion_pct_from_40d_low_close")) or 0.0, 0.0) * 80
    score -= max(_as_number(row.get("pre_explosion_close_to_low20")) or 0.0, 0.0) * 35

    close_to_high20 = _as_number(row.get("pre_explosion_close_to_high20"))
    if close_to_high20 is not None:
        if -0.12 <= close_to_high20 <= -0.03:
            score += 8
        elif close_to_high20 > -0.02:
            score -= 8
        elif close_to_high20 < -0.18:
            score -= 6
    return score


def _cat_sort_key(row: dict[str, Any]) -> tuple[float, str, str]:
    return (-cat_early_rank_score(row), _normalized_code(row.get("code")), _exchange_code(row.get("exchange")))


def _build_snapshot_rows(target_date: str) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    payload = get_us_selection(limit=6000, date=target_date)
    if payload.get("error"):
        raise UsSelectionError(str(payload["error"]))
    rows = payload.get("selections") if isinstance(payload.get("selections"), list) else []
    source_dates = {
        "selection_trade_date": payload.get("latest_date"),
        "snapshot_date": target_date,
    }

    lobster_rows = sorted(
        [row for row in rows if isinstance(row, dict) and row.get("lobster_flg")],
        key=lambda row: (
            _as_number(row.get("lobster_rank")) or float("inf"),
            -(_as_number(row.get("lobster_score")) or float("-inf")),
            _normalized_code(row.get("code")),
            _exchange_code(row.get("exchange")),
        ),
    )[:SNAPSHOT_LIMIT]
    cat_rows = sorted(
        [row for row in rows if isinstance(row, dict) and is_cat_early_candidate(row)],
        key=_cat_sort_key,
    )[:SNAPSHOT_LIMIT]

    ranked: dict[str, list[dict[str, Any]]] = {"lobster": [], "cat": []}
    for index, row in enumerate(lobster_rows, start=1):
        ranked["lobster"].append({**row, "snapshot_list_type": "lobster", "snapshot_rank": index, "lobster_rank": index})
    for index, row in enumerate(cat_rows, start=1):
        ranked["cat"].append(
            {
                **row,
                "snapshot_list_type": "cat",
                "snapshot_rank": index,
                "pre_explosion_rank": index,
                "pre_explosion_rank_score": cat_early_rank_score(row),
            }
        )
    return ranked, source_dates


def _snapshot_score(list_type: str, row: dict[str, Any]) -> float | None:
    if list_type == "lobster":
        return _as_number(row.get("lobster_score"))
    if list_type == "cat":
        return _as_number(row.get("pre_explosion_rank_score")) or _as_number(row.get("pre_explosion_score"))
    return None


def _snapshot_signal_date(row: dict[str, Any], target_date: str) -> str:
    return _date_text(row.get("trade_date")) or target_date


def _latest_metric_trade_date() -> str | None:
    settings = get_settings()
    with _connect(settings) as conn:
        with conn.cursor() as cur:
            cur.execute("select max(trade_date) as trade_date from us_stock_daily_metrics")
            row = dict(cur.fetchone() or {})
    return _date_text(row.get("trade_date"))


def _snapshot_counts(cur: Any, target_date: str) -> dict[str, int]:
    cur.execute(
        """
        select list_type, count(*) as rows
        from us_selection_daily_snapshots
        where trade_date = %s
        group by list_type
        """,
        [target_date],
    )
    return {str(row["list_type"]): int(row["rows"] or 0) for row in cur.fetchall()}


def _has_complete_snapshot(cur: Any, target_date: str) -> bool:
    counts = _snapshot_counts(cur, target_date)
    return all(counts.get(list_type, 0) > 0 for list_type in SNAPSHOT_LIST_TYPES)


def _snapshot_finished(result: dict[str, Any]) -> bool:
    return bool(result.get("saved") or result.get("status") == "already_saved")


def _missing_snapshot_list_types(list_types: Any) -> list[str]:
    if isinstance(list_types, str):
        present = {part.strip() for part in list_types.split(",") if part.strip()}
    elif isinstance(list_types, (list, tuple, set)):
        present = {str(part).strip() for part in list_types if str(part).strip()}
    else:
        present = set()
    return [list_type for list_type in SNAPSHOT_LIST_TYPES if list_type not in present]


def _snapshot_coverage_payload(row: dict[str, Any]) -> dict[str, Any]:
    missing_list_types = _missing_snapshot_list_types(row.get("list_types"))
    snapshot_row_count = int(row.get("snapshot_row_count") or 0)
    return {
        "trade_date": _date_text(row.get("trade_date")),
        "metric_rows": int(row.get("metric_rows") or 0),
        "average_trade_rows": int(row.get("average_trade_rows") or 0),
        "snapshot_row_count": snapshot_row_count,
        "snapshot_list_count": int(row.get("snapshot_list_count") or 0),
        "missing_list_types": missing_list_types,
        "complete": not missing_list_types and snapshot_row_count > 0,
    }


def get_snapshot_coverage(*, limit: int = SNAPSHOT_COVERAGE_LIMIT) -> dict[str, Any]:
    settings = get_settings()
    try:
        with _connect(settings, read_only=False) as conn:
            with conn.cursor() as cur:
                ensure_snapshot_schema(conn, settings)
                cur.execute(
                    """
                    with metric_dates as (
                      select
                        trade_date,
                        count(*) as metric_rows,
                        count(*) filter (where average_trade is not null) as average_trade_rows
                      from us_stock_daily_metrics
                      group by trade_date
                      order by trade_date desc
                      limit %s
                    ),
                    snapshot_counts as (
                      select
                        trade_date,
                        count(distinct list_type) as snapshot_list_count,
                        count(*) as snapshot_row_count,
                        array_agg(distinct list_type order by list_type) as list_types
                      from us_selection_daily_snapshots
                      group by trade_date
                    )
                    select
                      m.trade_date,
                      m.metric_rows,
                      m.average_trade_rows,
                      coalesce(s.snapshot_list_count, 0) as snapshot_list_count,
                      coalesce(s.snapshot_row_count, 0) as snapshot_row_count,
                      coalesce(s.list_types, array[]::text[]) as list_types
                    from metric_dates m
                    left join snapshot_counts s
                      on s.trade_date = m.trade_date
                    order by m.trade_date desc
                    """,
                    [max(1, min(int(limit), 1000))],
                )
                rows = [_snapshot_coverage_payload(dict(row)) for row in cur.fetchall()]
        missing_dates = [row["trade_date"] for row in rows if not row["complete"] and row["trade_date"]]
        return {"rows": len(rows), "missing_rows": len(missing_dates), "missing_dates": missing_dates, "dates": rows, "error": None}
    except Exception as exc:
        return {"rows": 0, "missing_rows": 0, "missing_dates": [], "dates": [], "error": str(exc)}


def get_snapshot_dates(*, limit: int = 260) -> dict[str, Any]:
    settings = get_settings()
    try:
        with _connect(settings, read_only=False) as conn:
            with conn.cursor() as cur:
                ensure_snapshot_schema(conn, settings)
                cur.execute(
                    """
                    select trade_date, count(distinct list_type) as list_count, count(*) as row_count
                    from us_selection_daily_snapshots
                    group by trade_date
                    having count(distinct list_type) = 2
                    order by trade_date desc
                    limit %s
                    """,
                    [max(1, min(int(limit), 1000))],
                )
                rows = [dict(row) for row in cur.fetchall()]
        return {
            "rows": len(rows),
            "dates": [{"trade_date": _date_text(row.get("trade_date")), "row_count": int(row.get("row_count") or 0)} for row in rows],
            "error": None,
        }
    except Exception as exc:
        return {"rows": 0, "dates": [], "error": str(exc)}


def get_snapshot_selection(*, trade_date: str) -> dict[str, Any]:
    target_date = _normalize_date(trade_date)
    settings = get_settings()
    try:
        with _connect(settings, read_only=False) as conn:
            with conn.cursor() as cur:
                ensure_snapshot_schema(conn, settings)
                cur.execute(
                    """
                    select list_type, rank, row_data, source_dates, updated_at
                    from us_selection_daily_snapshots
                    where trade_date = %s
                    order by list_type asc, rank asc
                    """,
                    [target_date],
                )
                rows = [dict(row) for row in cur.fetchall()]
        merged_by_key: dict[tuple[str, str], dict[str, Any]] = {}
        latest_updated_at = None
        source_dates: dict[str, Any] = {}
        for row in rows:
            row_data = row.get("row_data") if isinstance(row.get("row_data"), dict) else {}
            key = _row_key(row_data)
            if key == ("", ""):
                continue
            target = merged_by_key.setdefault(key, {**row_data})
            target.update(row_data)
            list_type = str(row.get("list_type") or "")
            if list_type == "lobster":
                target["lobster_flg"] = True
                target["lobster_rank"] = int(row.get("rank") or target.get("lobster_rank") or 0)
            elif list_type == "cat":
                target["pre_explosion_flg"] = True
                target["pre_explosion_rank"] = int(row.get("rank") or target.get("pre_explosion_rank") or 0)
            if isinstance(row.get("source_dates"), dict):
                source_dates.update(row["source_dates"])
            latest_updated_at = row.get("updated_at") or latest_updated_at

        selections = records_to_json(list(merged_by_key.values()))
        return {
            "rows": len(selections),
            "latest_date": target_date if selections else None,
            "snapshot_date": target_date,
            "snapshot_updated_at": _jsonable(latest_updated_at),
            "selections": selections,
            "error": None if selections else "snapshot_not_found",
        }
    except Exception as exc:
        return {
            "rows": 0,
            "latest_date": None,
            "snapshot_date": target_date,
            "snapshot_updated_at": None,
            "selections": [],
            "error": str(exc),
        }


def get_snapshot_readiness(*, trade_date: str | None = None) -> dict[str, Any]:
    target_date = _normalize_date(trade_date or _latest_metric_trade_date())
    settings = get_settings()
    reasons: list[str] = []
    details: dict[str, Any] = {}
    try:
        with _connect(settings) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select
                      count(*) as metric_rows,
                      count(*) filter (where average_trade is not null) as average_trade_rows
                    from us_stock_daily_metrics
                    where trade_date = %s
                    """,
                    [target_date],
                )
                metric_row = dict(cur.fetchone() or {})
                details.update(
                    {
                        "metric_rows": int(metric_row.get("metric_rows") or 0),
                        "average_trade_rows": int(metric_row.get("average_trade_rows") or 0),
                    }
                )
    except Exception as exc:
        reasons.append("us_stock_daily_metrics_unavailable")
        details["metric_error"] = str(exc)

    if details.get("metric_rows", 0) <= 0:
        reasons.append("us_stock_daily_metrics_missing")
    if details.get("average_trade_rows", 0) <= 0:
        reasons.append("us_average_trade_missing")
    return {"ready": not reasons, "trade_date": target_date, "reasons": reasons, "details": details}


def refresh_snapshot(*, trade_date: str | None = None) -> dict[str, Any]:
    if Jsonb is None:
        raise UsSelectionError("psycopg_jsonb_unavailable")
    target_date = _normalize_date(trade_date or _latest_metric_trade_date())
    readiness = get_snapshot_readiness(trade_date=target_date)
    if not readiness["ready"]:
        return {"ok": False, "status": "not_ready", "trade_date": target_date, "reasons": readiness["reasons"], "details": readiness["details"], "saved": False}

    settings = get_settings()
    rows_by_type, source_dates = _build_snapshot_rows(target_date)
    empty_lists = [list_type for list_type, rows in rows_by_type.items() if not rows]
    if empty_lists:
        return {
            "ok": False,
            "status": "not_ready",
            "trade_date": target_date,
            "reasons": [f"{list_type}_snapshot_empty" for list_type in empty_lists],
            "details": {**readiness["details"], "source_dates": source_dates},
            "saved": False,
        }

    with _connect(settings, read_only=False) as conn:
        try:
            ensure_snapshot_schema(conn, settings)
            with conn.cursor() as cur:
                cur.execute("select pg_advisory_xact_lock(hashtext('us_selection_daily_snapshots'))")
                cur.execute("delete from us_selection_daily_snapshots where trade_date = %s", [target_date])
                for list_type, rows in rows_by_type.items():
                    cur.executemany(
                        """
                        insert into us_selection_daily_snapshots (
                          trade_date, list_type, rank, code, exchange, score, signal_date,
                          row_data, source_dates, created_at, updated_at
                        )
                        values (%s, %s, %s, %s, %s, %s, %s, %s, %s, now(), now())
                        """,
                        [
                            (
                                target_date,
                                list_type,
                                int(row.get("snapshot_rank") or index),
                                _normalized_code(row.get("code")),
                                _exchange_code(row.get("exchange")),
                                _snapshot_score(list_type, row),
                                _snapshot_signal_date(row, target_date),
                                Jsonb(row),
                                Jsonb(source_dates),
                            )
                            for index, row in enumerate(rows, start=1)
                        ],
                    )
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    counts = {list_type: len(rows) for list_type, rows in rows_by_type.items()}
    return {"ok": True, "status": "saved", "trade_date": target_date, "counts": counts, "source_dates": source_dates, "saved": True, "error": None}


def maybe_refresh_latest_snapshot() -> dict[str, Any]:
    target_date = _latest_metric_trade_date()
    if not target_date:
        return {"ok": True, "status": "no_metric_trade_date", "saved": False}
    settings = get_settings()
    with _connect(settings, read_only=False) as conn:
        ensure_snapshot_schema(conn, settings)
        with conn.cursor() as cur:
            if _has_complete_snapshot(cur, target_date):
                return {"ok": True, "status": "already_saved", "trade_date": target_date, "saved": False}
    return refresh_snapshot(trade_date=target_date)


def get_snapshot_scheduler_status() -> dict[str, Any]:
    state = _read_state()
    return {
        "enabled": True,
        "timezone": SCHEDULER_TIMEZONE,
        "scheduled_time": get_settings().us_selection_snapshot_time,
        "state_file": str(_state_path()),
        "is_running": bool(_THREAD is not None and _THREAD.is_alive()),
        "state": state,
        "coverage": get_snapshot_coverage(limit=SNAPSHOT_COVERAGE_LIMIT),
    }


def _schedule_parts(raw_value: str) -> tuple[int, int]:
    try:
        hour_text, minute_text = raw_value.strip().split(":", maxsplit=1)
        return min(max(int(hour_text), 0), 23), min(max(int(minute_text), 0), 59)
    except (AttributeError, TypeError, ValueError):
        return 1, 30


def _local_now() -> datetime:
    return datetime.now(timezone.utc).astimezone(ZoneInfo(SCHEDULER_TIMEZONE))


def _target_trade_date(local_date: date) -> date:
    if local_date.weekday() == 0:
        return local_date - timedelta(days=3)
    return local_date - timedelta(days=1)


def _run_scheduled_once_if_due() -> None:
    state = _read_state()
    local_now = _local_now()
    local_date = local_now.date()
    scheduled_hour, scheduled_minute = _schedule_parts(get_settings().us_selection_snapshot_time)
    if (local_now.hour, local_now.minute) < (scheduled_hour, scheduled_minute):
        return
    if local_date.weekday() in {5, 6}:
        return

    target_date = _target_trade_date(local_date).isoformat()
    if state.get("last_saved_trade_date") == target_date and str(state.get("last_status") or "") in {"saved", "already_saved"}:
        return

    next_state = {
        **state,
        "last_checked_at": _now_iso(),
        "last_attempt_local_date": local_date.isoformat(),
        "last_attempt_timezone": SCHEDULER_TIMEZONE,
        "last_attempt_scheduled_time": get_settings().us_selection_snapshot_time,
        "last_target_trade_date": target_date,
    }
    if not _RUN_LOCK.acquire(blocking=False):
        next_state["last_status"] = "skipped"
        next_state["last_reason"] = "snapshot_worker_already_running"
        _write_state(next_state)
        return

    try:
        result = refresh_snapshot(trade_date=target_date)
        next_state.update({"last_attempted_at": _now_iso(), "last_status": result.get("status"), "last_trade_date": result.get("trade_date"), "last_result": result, "last_error": None})
        if _snapshot_finished(result):
            next_state["last_trigger_local_date"] = local_date.isoformat()
            next_state["last_trigger_timezone"] = SCHEDULER_TIMEZONE
            next_state["last_trigger_scheduled_time"] = get_settings().us_selection_snapshot_time
            next_state["retry_pending"] = False
            next_state.pop("last_pending_trade_date", None)
        else:
            next_state["retry_pending"] = True
            next_state["last_pending_trade_date"] = result.get("trade_date")
        if result.get("saved"):
            next_state["last_saved_trade_date"] = result.get("trade_date")
            next_state["last_saved_at"] = _now_iso()
    except Exception as exc:
        next_state.update({"last_attempted_at": _now_iso(), "last_status": "failed", "last_error": str(exc), "retry_pending": True})
    finally:
        _RUN_LOCK.release()
    _write_state(next_state)


def _run_loop(stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        try:
            _run_scheduled_once_if_due()
        except Exception as exc:
            state = _read_state()
            _write_state({**state, "last_checked_at": _now_iso(), "last_error_at": _now_iso(), "last_error": str(exc)})
        stop_event.wait(SCHEDULER_POLL_SECONDS)


def start_snapshot_scheduler() -> None:
    global _STOP_EVENT, _THREAD
    with _THREAD_LOCK:
        if _THREAD is not None and _THREAD.is_alive():
            return
        _STOP_EVENT = threading.Event()
        _THREAD = threading.Thread(target=_run_loop, args=(_STOP_EVENT,), name="us-selection-snapshot", daemon=True)
        _THREAD.start()


def stop_snapshot_scheduler() -> None:
    global _STOP_EVENT, _THREAD
    with _THREAD_LOCK:
        if _STOP_EVENT is not None:
            _STOP_EVENT.set()
        if _THREAD is not None and _THREAD.is_alive():
            _THREAD.join(timeout=2)
        _STOP_EVENT = None
        _THREAD = None
