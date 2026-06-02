from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from app.config import Settings, get_settings
from app.services.files import read_json, write_json_atomic

try:
    import psycopg
    from psycopg.rows import dict_row
except Exception:  # pragma: no cover - optional dependency availability is environment-specific
    psycopg = None
    dict_row = None


FEI_DB_SYNC_STATE_FILE = "fei_db_sync_state.json"
KLINE_IMPORT_TIMEOUT_SECONDS = 30 * 60
STCN_ATTEMPT_TIMEOUT_SECONDS = 15 * 60
STCN_POLL_SECONDS = 5 * 60

_STOP_EVENT: threading.Event | None = None
_THREAD: threading.Thread | None = None
_THREAD_LOCK = threading.Lock()
_STCN_WORKER_LOCK = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _state_path(settings: Settings | None = None) -> Path:
    active_settings = settings or get_settings()
    return active_settings.run_dir / FEI_DB_SYNC_STATE_FILE


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


def _latest_kline_trade_date(kline_dir: Path) -> str | None:
    latest: pd.Timestamp | None = None
    for path in sorted(kline_dir.glob("*.parquet")):
        try:
            frame = pd.read_parquet(path, columns=["date"])
        except Exception:
            continue
        if frame.empty:
            continue
        max_date = pd.to_datetime(frame["date"], errors="coerce").max()
        if pd.isna(max_date):
            continue
        ts = pd.Timestamp(max_date).normalize()
        if latest is None or ts > latest:
            latest = ts
    return latest.date().isoformat() if latest is not None else None


def _db_max_trade_date(settings: Settings, *, before_date: str | None = None) -> str | None:
    if psycopg is None or dict_row is None or not settings.paper_db_url:
        return None
    sql = "select max(trade_date) as trade_date from stock_daily_metrics"
    params: list[Any] = []
    if before_date:
        sql += " where trade_date < %s"
        params.append(before_date)
    try:
        with psycopg.connect(
            settings.paper_db_url,
            row_factory=dict_row,
            connect_timeout=5,
            options="-c default_transaction_read_only=on",
        ) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                row = cur.fetchone() or {}
                return _date_text(row.get("trade_date"))
    except Exception:
        return None


def _read_summary(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}


def _run_script(command: list[str], *, cwd: Path, timeout: int) -> tuple[int, str]:
    env = os.environ.copy()
    result = subprocess.run(
        command,
        cwd=str(cwd),
        env=env,
        capture_output=True,
        check=False,
        text=True,
        timeout=timeout,
    )
    output = "\n".join(part for part in [result.stdout.strip(), result.stderr.strip()] if part)
    return result.returncode, output


def _maybe_publish(state: dict[str, Any]) -> dict[str, Any]:
    target_date = state.get("target_trade_date")
    if (
        target_date
        and state.get("kline_imported_date") == target_date
        and state.get("stcn_imported_date") == target_date
        and state.get("published_trade_date") != target_date
    ):
        state["published_trade_date"] = target_date
        state["published_at"] = _now_iso()
    return state


def get_published_trade_date() -> str | None:
    return _date_text(_read_state().get("published_trade_date"))


def get_fei_db_sync_status() -> dict[str, Any]:
    state = _read_state()
    target_date = _date_text(state.get("target_trade_date"))
    stcn_running = bool(_STCN_WORKER_LOCK.locked())
    return {
        "status": "running" if stcn_running else "idle",
        "is_running": stcn_running,
        "state_file": str(_state_path()),
        "target_trade_date": target_date,
        "kline_imported_date": _date_text(state.get("kline_imported_date")),
        "stcn_imported_date": _date_text(state.get("stcn_imported_date")),
        "published_trade_date": _date_text(state.get("published_trade_date")),
        "last_kline_import_at": state.get("last_kline_import_at"),
        "last_stcn_attempt_at": state.get("last_stcn_attempt_at"),
        "last_stcn_status": state.get("last_stcn_status"),
        "last_error": state.get("last_error"),
        "last_output": state.get("last_output"),
        "kline_summary": state.get("kline_summary") or {},
        "stcn_summary": state.get("stcn_summary") or {},
    }


def run_kline_import_after_step1() -> dict[str, Any]:
    settings = get_settings()
    target_date = _latest_kline_trade_date(settings.quant_dir / "daily_kline")
    if not target_date:
        raise RuntimeError("No kline trade date was found after Step 1.")

    state = _read_state(settings)
    previous_published = (
        _date_text(state.get("published_trade_date"))
        or _db_max_trade_date(settings, before_date=target_date)
        or _db_max_trade_date(settings)
    )
    state.update(
        {
            "target_trade_date": target_date,
            "published_trade_date": previous_published,
            "last_kline_import_at": _now_iso(),
            "last_error": None,
        }
    )
    _write_state(state, settings)

    summary_path = settings.run_dir / f"fei_kline_import_{target_date}.json"
    command = [
        sys.executable,
        str(settings.project_root / "scripts" / "import_daily_kline_to_postgres.py"),
        "--target-date",
        target_date,
        "--summary-json",
        str(summary_path),
    ]
    returncode, output = _run_script(command, cwd=settings.project_root, timeout=KLINE_IMPORT_TIMEOUT_SECONDS)
    summary = _read_summary(summary_path)
    if returncode != 0:
        state = _read_state(settings)
        state.update(
            {
                "last_error": output or summary.get("error") or "FEI kline import failed.",
                "last_output": output,
                "kline_summary": summary,
                "updated_at": _now_iso(),
            }
        )
        _write_state(state, settings)
        raise RuntimeError(state["last_error"])

    imported_rows = int(summary.get("imported_rows") or 0)
    if imported_rows <= 0:
        state = _read_state(settings)
        state.update(
            {
                "last_error": f"FEI kline import for {target_date} imported 0 rows.",
                "last_output": output,
                "kline_summary": summary,
                "updated_at": _now_iso(),
            }
        )
        _write_state(state, settings)
        raise RuntimeError(state["last_error"])

    state = _read_state(settings)
    state.update(
        {
            "target_trade_date": target_date,
            "kline_imported_date": target_date,
            "last_kline_import_at": _now_iso(),
            "last_output": output,
            "kline_summary": summary,
            "stcn_loop_requested_at": _now_iso(),
            "last_stcn_status": state.get("last_stcn_status") or "pending",
            "last_error": None,
            "updated_at": _now_iso(),
        }
    )
    state = _maybe_publish(state)
    _write_state(state, settings)
    return {"target_trade_date": target_date, "imported_rows": imported_rows, "summary": summary}


def run_stcn_sync_once(target_date: str) -> dict[str, Any]:
    settings = get_settings()
    acquired = _STCN_WORKER_LOCK.acquire(blocking=False)
    if not acquired:
        return {"status": "skipped", "reason": "stcn_worker_already_running"}
    try:
        summary_path = settings.run_dir / f"stcn_average_trade_{target_date}.json"
        command = [
            sys.executable,
            str(settings.project_root / "scripts" / "import_stcn_average_trade.py"),
            "--target-date",
            target_date,
            "--timeout",
            "10",
            "--sleep",
            "3",
            "--retries",
            "3",
            "--summary-json",
            str(summary_path),
        ]
        state = _read_state(settings)
        state.update(
            {
                "target_trade_date": target_date,
                "last_stcn_attempt_at": _now_iso(),
                "last_stcn_status": "running",
                "last_error": None,
                "updated_at": _now_iso(),
            }
        )
        _write_state(state, settings)

        try:
            returncode, output = _run_script(command, cwd=settings.project_root, timeout=STCN_ATTEMPT_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            state = _read_state(settings)
            state.update(
                {
                    "last_stcn_status": "failed",
                    "last_error": f"STCN worker timed out after {STCN_ATTEMPT_TIMEOUT_SECONDS} seconds.",
                    "updated_at": _now_iso(),
                }
            )
            _write_state(state, settings)
            return {"status": "failed", "error": state["last_error"]}

        summary = _read_summary(summary_path)
        status = str(summary.get("status") or ("success" if returncode == 0 else "failed"))
        state = _read_state(settings)
        state.update(
            {
                "last_stcn_status": status,
                "last_output": output,
                "stcn_summary": summary,
                "updated_at": _now_iso(),
            }
        )
        if returncode != 0:
            state["last_error"] = output or summary.get("error") or "STCN import failed."
        elif status == "success" and _date_text(summary.get("source_latest_trade_date")) == target_date:
            state["stcn_imported_date"] = target_date
            state["last_error"] = None
        elif status == "no_update":
            state["last_error"] = summary.get("error")
        else:
            state["last_error"] = summary.get("error")
        state = _maybe_publish(state)
        _write_state(state, settings)
        return {"status": status, "returncode": returncode, "summary": summary}
    finally:
        _STCN_WORKER_LOCK.release()


def _run_loop(stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        try:
            state = _read_state()
            target_date = _date_text(state.get("target_trade_date"))
            if (
                target_date
                and _date_text(state.get("kline_imported_date")) == target_date
                and _date_text(state.get("stcn_imported_date")) != target_date
            ):
                run_stcn_sync_once(target_date)
            else:
                previous_state = dict(state)
                state = _maybe_publish(state)
                if state != previous_state:
                    _write_state(state)
        except Exception as exc:
            state = _read_state()
            state.update({"last_error": str(exc), "updated_at": _now_iso()})
            _write_state(state)
        stop_event.wait(STCN_POLL_SECONDS)


def start_fei_db_sync_scheduler() -> None:
    global _STOP_EVENT, _THREAD
    with _THREAD_LOCK:
        if _THREAD is not None and _THREAD.is_alive():
            return
        _STOP_EVENT = threading.Event()
        _THREAD = threading.Thread(target=_run_loop, args=(_STOP_EVENT,), name="fei-db-sync", daemon=True)
        _THREAD.start()


def stop_fei_db_sync_scheduler() -> None:
    global _STOP_EVENT, _THREAD
    with _THREAD_LOCK:
        if _STOP_EVENT is not None:
            _STOP_EVENT.set()
        if _THREAD is not None and _THREAD.is_alive():
            _THREAD.join(timeout=2)
        _STOP_EVENT = None
        _THREAD = None
