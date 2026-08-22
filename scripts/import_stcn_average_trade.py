#!/usr/bin/env python3
"""Import STCN average shares-per-trade data into stock_daily_metrics."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

try:
    import fcntl
except ImportError:  # pragma: no cover - Linux deployment provides fcntl
    fcntl = None

try:
    import psycopg
except ImportError:  # pragma: no cover - depends on local environment
    psycopg = None


SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/113 Safari/537.36"

MARKETS = (
    {
        "key": "mbcj_hsag",
        "label": "沪市A股",
        "exchange": "sh",
        "paged": True,
        "url": "https://info.stcn.com/data_center/jysj/json/mbjy_hsa_{page}.json",
    },
    {
        "key": "mbcj_szzb",
        "label": "深市主板",
        "exchange": "sz",
        "paged": True,
        "url": "https://info.stcn.com/data_center/jysj/json/mbjy_sszb_{page}.json",
    },
    {
        "key": "mbcj_cyb",
        "label": "创业板",
        "exchange": "sz",
        "paged": True,
        "url": "https://info.stcn.com/data_center/jysj/json/mbjy_sscyb_{page}.json",
    },
    {
        "key": "mbcj_kcb",
        "label": "科创板",
        "exchange": "sh",
        "paged": False,
        "url": "https://info.stcn.com/dc/sjb/indexWeb.jsp?p=xcxjyydKcb",
    },
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
STCN_EXCLUDED_PREFIXES = ("200", "201", "689", "900")

UPSERT_SQL = """
insert into stock_daily_metrics (
  trade_date,
  code,
  exchange,
  average_trade,
  imported_at
) values (
  %s, %s, %s, %s, now()
)
on conflict (trade_date, code, exchange) do update set
  average_trade = excluded.average_trade,
  imported_at = now()
"""

RUN_INSERT_SQL = """
insert into stcn_average_trade_runs (
  started_at,
  status,
  source_latest_trade_date,
  fetched_rows,
  upserted_rows,
  error,
  finished_at
) values (
  %s, %s, %s, %s, %s, %s, now()
)
"""


@dataclass(frozen=True)
class ParsedRow:
    trade_date: date
    code: str
    exchange: str
    average_trade: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import STCN average shares-per-trade data.")
    parser.add_argument(
        "--database-url",
        default=os.getenv("APP_DB_URL") or os.getenv("PAPER_DB_URL"),
        help="Postgres DSN. Defaults to APP_DB_URL, then PAPER_DB_URL.",
    )
    parser.add_argument(
        "--runs-schema-sql",
        default=str(PROJECT_ROOT / "scripts" / "create_stcn_average_trade_runs.sql"),
        help="Path to the SQL file that creates stcn_average_trade_runs.",
    )
    parser.add_argument(
        "--metrics-schema-sql",
        default=str(PROJECT_ROOT / "scripts" / "create_stock_daily_metrics.sql"),
        help="Path to the SQL file that creates stock_daily_metrics.",
    )
    parser.add_argument("--timeout", type=float, default=10.0, help="HTTP timeout seconds per request.")
    parser.add_argument("--sleep", type=float, default=3.0, help="Seconds to sleep after each STCN request.")
    parser.add_argument("--retries", type=int, default=3, help="Retries per STCN request before failing.")
    parser.add_argument("--target-date", default=None, help="Expected source date in YYYY-MM-DD or YYYYMMDD format.")
    parser.add_argument("--summary-json", default=None, help="Optional path to write a machine-readable import summary.")
    parser.add_argument(
        "--lock-file",
        default=str(PROJECT_ROOT / "run" / "stcn_average_trade.lock"),
        help="Process lock file used to prevent overlapping STCN fetches.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Fetch and parse data without writing to Postgres.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Fetch even if today's Shanghai-date source data was already imported successfully.",
    )
    return parser.parse_args()


def parse_target_date(value: str | None) -> date | None:
    if not value:
        return None
    parsed = pd.to_datetime(str(value).strip(), errors="coerce")
    if pd.isna(parsed):
        raise ValueError("--target-date must be a valid date in YYYY-MM-DD or YYYYMMDD format")
    return pd.Timestamp(parsed).date()


def write_summary(path: str | None, payload: dict[str, Any]) -> None:
    if not path:
        return
    summary_path = Path(path)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2, default=str) + "\n", encoding="utf-8")


@contextlib.contextmanager
def acquire_process_lock(path: str):
    if fcntl is None:
        yield True
        return
    lock_path = Path(path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("w", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            handle.write(f"{os.getpid()}\n")
            handle.flush()
            yield True
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def read_schema(path: str) -> str:
    schema_path = Path(path)
    if not schema_path.exists():
        raise FileNotFoundError(f"{schema_path} does not exist")
    return schema_path.read_text(encoding="utf-8")


def shanghai_today() -> date:
    return datetime.now(SHANGHAI_TZ).date()


def _fetch_json_once(url: str, *, timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8", errors="replace")

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"failed to decode JSON from {url}: {raw[:200]!r}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"unexpected JSON payload from {url}")
    return payload


def fetch_json(url: str, *, timeout: float, retries: int, sleep_seconds: float) -> dict[str, Any]:
    attempts = max(int(retries), 1)
    delay_base = max(float(sleep_seconds), 0.0)
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            payload = _fetch_json_once(url, timeout=timeout)
            if delay_base > 0:
                time.sleep(delay_base)
            return payload
        except (urllib.error.URLError, TimeoutError, OSError, RuntimeError, ValueError) as exc:
            last_error = exc
            if attempt >= attempts:
                break
            backoff = delay_base * attempt
            print(f"STCN request failed, retrying in {backoff:.1f}s ({attempt}/{attempts}): {exc}", flush=True)
            if backoff > 0:
                time.sleep(backoff)
    raise RuntimeError(f"failed to fetch {url}: {last_error}") from last_error


def fetch_market(
    market: dict[str, Any],
    *,
    timeout: float,
    retries: int,
    sleep_seconds: float,
) -> list[dict[str, Any]]:
    if not market["paged"]:
        payload = fetch_json(str(market["url"]), timeout=timeout, retries=retries, sleep_seconds=sleep_seconds)
        rows = payload.get("data")
        if not isinstance(rows, list):
            raise RuntimeError(f"{market['key']} returned no data list")
        return rows

    first_payload = fetch_json(str(market["url"]).format(page=1), timeout=timeout, retries=retries, sleep_seconds=sleep_seconds)
    rows = first_payload.get("data")
    if not isinstance(rows, list):
        raise RuntimeError(f"{market['key']} page 1 returned no data list")
    all_rows = list(rows)
    try:
        page_count = int(first_payload.get("pageCount") or 1)
    except (TypeError, ValueError):
        page_count = 1
    if page_count < 1:
        page_count = 1

    for page in range(2, page_count + 1):
        payload = fetch_json(
            str(market["url"]).format(page=page),
            timeout=timeout,
            retries=retries,
            sleep_seconds=sleep_seconds,
        )
        page_rows = payload.get("data")
        if not isinstance(page_rows, list):
            raise RuntimeError(f"{market['key']} page {page} returned no data list")
        all_rows.extend(page_rows)
    return all_rows


def parse_date(value: Any) -> date | None:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return pd.Timestamp(parsed).date()


def parse_average_trade(value: Any) -> int | None:
    text = str(value or "").strip().replace(",", "")
    if not text or text == "--":
        return None
    try:
        return int(round(float(text)))
    except ValueError:
        return None


def normalize_code(value: Any) -> str:
    return str(value or "").strip().zfill(6)


def is_excluded_stcn_code(code: str) -> bool:
    return str(code or "").strip().zfill(6).startswith(STCN_EXCLUDED_PREFIXES)


def parse_market_rows(market: dict[str, Any], source_rows: list[dict[str, Any]]) -> list[ParsedRow]:
    parsed: list[ParsedRow] = []
    for source in source_rows:
        code = normalize_code(source.get("secucode"))
        if not code or len(code) != 6:
            continue
        if is_excluded_stcn_code(code):
            continue
        exchange = str(market["exchange"])
        for index in range(1, 6):
            trade_date = parse_date(source.get(f"rq{index}"))
            average_trade = parse_average_trade(source.get(f"bs{index}"))
            if trade_date is None or average_trade is None:
                continue
            parsed.append(
                ParsedRow(
                    trade_date=trade_date,
                    code=code,
                    exchange=exchange,
                    average_trade=average_trade,
                )
            )
    return parsed


def fetch_all_rows(*, timeout: float, retries: int, sleep_seconds: float) -> tuple[list[ParsedRow], dict[str, int]]:
    rows: list[ParsedRow] = []
    counts: dict[str, int] = {}
    for market in MARKETS:
        source_rows = fetch_market(market, timeout=timeout, retries=retries, sleep_seconds=sleep_seconds)
        parsed_rows = parse_market_rows(market, source_rows)
        counts[str(market["key"])] = len(parsed_rows)
        if not parsed_rows:
            raise RuntimeError(f"{market['key']} produced no parsed rows")
        rows.extend(parsed_rows)
    return rows, counts


def dedupe_rows(rows: list[ParsedRow]) -> list[ParsedRow]:
    by_key: dict[tuple[date, str, str], ParsedRow] = {}
    for row in rows:
        by_key[(row.trade_date, row.code, row.exchange)] = row
    return sorted(by_key.values(), key=lambda item: (item.trade_date, item.exchange, item.code))


def source_latest_trade_date(rows: list[ParsedRow]) -> date | None:
    return max((row.trade_date for row in rows), default=None)


def ensure_schema(conn: Any, *, runs_schema_sql: str, metrics_schema_sql: str) -> None:
    with conn.cursor() as cur:
        cur.execute(metrics_schema_sql)
        cur.execute(runs_schema_sql)
    conn.commit()


def was_today_successfully_imported(conn: Any, target_date: date) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            select 1
            from stcn_average_trade_runs
            where status = 'success'
              and source_latest_trade_date = %s
            limit 1
            """,
            [target_date],
        )
        return cur.fetchone() is not None


def record_run(
    conn: Any,
    *,
    started_at: datetime,
    status: str,
    latest_date: date | None,
    fetched_rows: int,
    upserted_rows: int,
    error: str | None = None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(RUN_INSERT_SQL, [started_at, status, latest_date, fetched_rows, upserted_rows, error])
    conn.commit()


def upsert_rows(conn: Any, rows: list[ParsedRow]) -> int:
    params = [(row.trade_date, row.code, row.exchange, row.average_trade) for row in rows]
    with conn.cursor() as cur:
        cur.executemany(UPSERT_SQL, params)
    return len(params)


def main() -> int:
    started_at = datetime.now(timezone.utc)
    args = parse_args()
    try:
        target_date = parse_target_date(args.target_date) or shanghai_today()
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        write_summary(
            args.summary_json,
            {
                "ok": False,
                "status": "failed",
                "error": str(exc),
                "started_at": started_at.isoformat(),
                "finished_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        return 2

    if not args.database_url and not args.dry_run:
        print("APP_DB_URL or PAPER_DB_URL must be set, or pass --database-url.", file=sys.stderr)
        write_summary(
            args.summary_json,
            {
                "ok": False,
                "status": "failed",
                "target_date": target_date.isoformat(),
                "error": "APP_DB_URL or PAPER_DB_URL must be set, or pass --database-url.",
                "started_at": started_at.isoformat(),
                "finished_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        return 2
    if psycopg is None and not args.dry_run:
        print("psycopg is not installed in this Python environment.", file=sys.stderr)
        write_summary(
            args.summary_json,
            {
                "ok": False,
                "status": "failed",
                "target_date": target_date.isoformat(),
                "error": "psycopg is not installed in this Python environment.",
                "started_at": started_at.isoformat(),
                "finished_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        return 2
    if args.sleep < 0:
        print("--sleep must be >= 0.", file=sys.stderr)
        return 2
    if args.retries < 1:
        print("--retries must be >= 1.", file=sys.stderr)
        return 2

    with acquire_process_lock(args.lock_file) as lock_acquired:
        if not lock_acquired:
            write_summary(
                args.summary_json,
                {
                    "ok": False,
                    "status": "skipped",
                    "target_date": target_date.isoformat(),
                    "source_latest_trade_date": None,
                    "fetched_rows": 0,
                    "upserted_rows": 0,
                    "error": "another STCN import is already running",
                    "started_at": started_at.isoformat(),
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            print("Skipped: another STCN import is already running.")
            return 0
        return run_import(args=args, started_at=started_at, target_date=target_date)


def run_import(*, args: argparse.Namespace, started_at: datetime, target_date: date) -> int:
    try:
        rows_schema_sql = read_schema(args.runs_schema_sql)
        metrics_schema_sql = read_schema(args.metrics_schema_sql)

        if not args.dry_run:
            with psycopg.connect(args.database_url) as conn:
                ensure_schema(conn, runs_schema_sql=rows_schema_sql, metrics_schema_sql=metrics_schema_sql)
                if not args.force and was_today_successfully_imported(conn, target_date):
                    record_run(
                        conn,
                        started_at=started_at,
                        status="no_update",
                        latest_date=target_date,
                        fetched_rows=0,
                        upserted_rows=0,
                        error="skipped because today's Shanghai-date STCN data was already imported",
                    )
                    write_summary(
                        args.summary_json,
                        {
                            "ok": True,
                            "status": "success",
                            "target_date": target_date.isoformat(),
                            "source_latest_trade_date": target_date.isoformat(),
                            "fetched_rows": 0,
                            "upserted_rows": 0,
                            "market_rows": {},
                            "error": "skipped because today's Shanghai-date STCN data was already imported",
                            "started_at": started_at.isoformat(),
                            "finished_at": datetime.now(timezone.utc).isoformat(),
                        },
                    )
                    print(f"Skipped: source date {target_date} was already imported successfully.")
                    return 0

        fetched_rows, counts = fetch_all_rows(timeout=args.timeout, retries=args.retries, sleep_seconds=args.sleep)
        rows = dedupe_rows(fetched_rows)
        latest_date = source_latest_trade_date(rows)
        status = "success" if latest_date == target_date else "no_update"
        summary = f"latest_source_date={latest_date}, rows={len(rows)}, market_rows={counts}"
        summary_payload = {
            "ok": status == "success",
            "status": status,
            "target_date": target_date.isoformat(),
            "source_latest_trade_date": latest_date.isoformat() if latest_date is not None else None,
            "fetched_rows": len(rows),
            "upserted_rows": 0,
            "market_rows": counts,
            "error": None if status == "success" else f"source has not reached Shanghai date {target_date}",
            "started_at": started_at.isoformat(),
        }

        if args.dry_run:
            summary_payload["finished_at"] = datetime.now(timezone.utc).isoformat()
            write_summary(args.summary_json, summary_payload)
            print(f"Dry run: {summary}")
            return 0

        with psycopg.connect(args.database_url) as conn:
            try:
                upserted_rows = upsert_rows(conn, rows)
                record_run(
                    conn,
                    started_at=started_at,
                    status=status,
                    latest_date=latest_date,
                    fetched_rows=len(rows),
                    upserted_rows=upserted_rows,
                    error=None if status == "success" else f"source has not reached Shanghai date {target_date}",
                )
                summary_payload["upserted_rows"] = upserted_rows
            except Exception:
                conn.rollback()
                raise

        summary_payload["finished_at"] = datetime.now(timezone.utc).isoformat()
        write_summary(args.summary_json, summary_payload)
        print(f"Imported STCN average_trade: {summary}, status={status}.")
        return 0
    except Exception as exc:
        if args.database_url and psycopg is not None and not args.dry_run:
            try:
                with psycopg.connect(args.database_url) as conn:
                    ensure_schema(
                        conn,
                        runs_schema_sql=read_schema(args.runs_schema_sql),
                        metrics_schema_sql=read_schema(args.metrics_schema_sql),
                    )
                    record_run(
                        conn,
                        started_at=started_at,
                        status="failed",
                        latest_date=None,
                        fetched_rows=0,
                        upserted_rows=0,
                        error=str(exc),
                    )
            except Exception:
                pass
        write_summary(
            args.summary_json,
            {
                "ok": False,
                "status": "failed",
                "target_date": target_date.isoformat(),
                "source_latest_trade_date": None,
                "fetched_rows": 0,
                "upserted_rows": 0,
                "error": str(exc),
                "started_at": started_at.isoformat(),
                "finished_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        print(f"STCN import failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
