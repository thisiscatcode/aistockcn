#!/usr/bin/env python3
"""Import daily kline close/turnover/volume/amount data into stock_daily_metrics."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

try:
    import psycopg
except ImportError:  # pragma: no cover - depends on local environment
    psycopg = None


REQUIRED_COLUMNS = ["date", "close"]
OPTIONAL_COLUMNS = ["code", "exchange", "turnover", "volume", "amount"]

UPSERT_SQL = """
insert into stock_daily_metrics (
  trade_date,
  code,
  exchange,
  close,
  volume,
  amount,
  average_trade,
  turnover,
  imported_at
) select
  trade_date,
  code,
  exchange,
  close,
  volume,
  amount,
  average_trade,
  turnover,
  now()
from stock_daily_metrics_import
on conflict (trade_date, code, exchange) do update set
  close = excluded.close,
  volume = excluded.volume,
  amount = excluded.amount,
  average_trade = coalesce(excluded.average_trade, stock_daily_metrics.average_trade),
  turnover = excluded.turnover,
  imported_at = now()
"""

TEMP_TABLE_SQL = """
create temp table if not exists stock_daily_metrics_import (
  trade_date date not null,
  code text not null,
  exchange text not null,
  close numeric,
  volume numeric,
  amount numeric,
  average_trade numeric,
  turnover numeric
) on commit drop
"""

TRUNCATE_TEMP_SQL = "truncate stock_daily_metrics_import"

DELETE_OLD_ROWS_SQL = "delete from stock_daily_metrics where trade_date < %s"

COPY_SQL = """
copy stock_daily_metrics_import (
  trade_date,
  code,
  exchange,
  close,
  volume,
  amount,
  average_trade,
  turnover
) from stdin
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import daily kline metrics into Postgres.")
    parser.add_argument(
        "--kline-dir",
        default="quant_data/daily_kline",
        help="Directory containing per-stock daily kline parquet files.",
    )
    parser.add_argument(
        "--schema-sql",
        default="scripts/create_stock_daily_metrics.sql",
        help="Path to the SQL file that creates stock_daily_metrics.",
    )
    parser.add_argument(
        "--database-url",
        default=os.getenv("APP_DB_URL") or os.getenv("PAPER_DB_URL"),
        help="Postgres DSN. Defaults to APP_DB_URL, then PAPER_DB_URL.",
    )
    parser.add_argument("--batch-size", type=int, default=5000, help="Rows to upsert per batch.")
    parser.add_argument(
        "--target-date",
        default=None,
        help="Import only one trade date in YYYY-MM-DD or YYYYMMDD format. When set, --months pruning is disabled.",
    )
    parser.add_argument("--summary-json", default=None, help="Optional path to write a machine-readable import summary.")
    parser.add_argument(
        "--months",
        type=float,
        default=3.0,
        help="Import only rows newer than max trade date minus this many months. Use 0 for all history.",
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


def to_db_value(value: Any) -> Any:
    if pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.date()
    if hasattr(value, "item"):
        return value.item()
    return value


def infer_exchange(code: Any) -> str:
    normalized = str(code or "").zfill(6)
    return "sh" if normalized.startswith(("5", "6", "9")) else "sz"


def rows_from_kline(
    path: Path,
    *,
    start_date: date | None = None,
    target_date: date | None = None,
) -> list[tuple[Any, ...]]:
    df = pd.read_parquet(path)
    missing = [column for column in REQUIRED_COLUMNS if column not in df.columns]
    if missing:
        raise ValueError(f"{path} is missing required columns: {', '.join(missing)}")

    for column in OPTIONAL_COLUMNS:
        if column not in df.columns:
            df[column] = None

    df = df[REQUIRED_COLUMNS + OPTIONAL_COLUMNS].copy()
    if df["code"].isna().all():
        df["code"] = path.stem
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date", "code"])
    if start_date is not None:
        df = df[df["date"] >= pd.Timestamp(start_date)]
    if target_date is not None:
        df = df[df["date"].dt.date == target_date]
    df["code"] = df["code"].astype(str).str.zfill(6)
    exchange = df["exchange"]
    missing_exchange = exchange.isna() | (exchange.astype(str).str.strip() == "")
    df.loc[missing_exchange, "exchange"] = df.loc[missing_exchange, "code"].map(infer_exchange)
    df["exchange"] = df["exchange"].astype(str).str.lower()

    rows: list[tuple[Any, ...]] = []
    for record in df.to_dict(orient="records"):
        rows.append(
            (
                to_db_value(record["date"]),
                to_db_value(record["code"]),
                to_db_value(record["exchange"]),
                to_db_value(record["close"]),
                to_db_value(record["volume"]),
                to_db_value(record["amount"]),
                None,
                to_db_value(record["turnover"]),
            )
        )
    return rows


def latest_trade_date(paths: list[Path]) -> date | None:
    latest: pd.Timestamp | None = None
    for path in paths:
        try:
            df = pd.read_parquet(path, columns=["date"])
        except Exception:
            continue
        if df.empty:
            continue
        max_date = pd.to_datetime(df["date"], errors="coerce").max()
        if pd.isna(max_date):
            continue
        max_timestamp = pd.Timestamp(max_date)
        if latest is None or max_timestamp > latest:
            latest = max_timestamp
    return latest.date() if latest is not None else None


def batched(items: list[tuple[Any, ...]], batch_size: int) -> Iterable[list[tuple[Any, ...]]]:
    for start in range(0, len(items), batch_size):
        yield items[start : start + batch_size]


def main() -> int:
    args = parse_args()
    try:
        target_date = parse_target_date(args.target_date)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        write_summary(
            args.summary_json,
            {
                "ok": False,
                "error": str(exc),
                "generated_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        return 2

    if not args.database_url:
        print("APP_DB_URL or PAPER_DB_URL must be set, or pass --database-url.", file=sys.stderr)
        write_summary(
            args.summary_json,
            {
                "ok": False,
                "error": "APP_DB_URL or PAPER_DB_URL must be set, or pass --database-url.",
                "generated_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        return 2
    if psycopg is None:
        print("psycopg is not installed in this Python environment.", file=sys.stderr)
        write_summary(
            args.summary_json,
            {
                "ok": False,
                "error": "psycopg is not installed in this Python environment.",
                "generated_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        return 2
    if args.batch_size < 1:
        print("--batch-size must be >= 1.", file=sys.stderr)
        return 2
    if args.months < 0:
        print("--months must be >= 0.", file=sys.stderr)
        return 2

    kline_dir = Path(args.kline_dir)
    schema_sql_path = Path(args.schema_sql)
    if not kline_dir.exists():
        print(f"{kline_dir} does not exist.", file=sys.stderr)
        return 2
    if not schema_sql_path.exists():
        print(f"{schema_sql_path} does not exist.", file=sys.stderr)
        return 2

    paths = sorted(kline_dir.glob("*.parquet"))
    max_trade_date = latest_trade_date(paths)
    start_date = None
    if target_date is None and args.months > 0 and max_trade_date is not None:
        start_date = (pd.Timestamp(max_trade_date) - pd.DateOffset(months=args.months)).date()
    schema_sql = schema_sql_path.read_text(encoding="utf-8")
    total_rows = 0

    with psycopg.connect(args.database_url) as conn:
        try:
            with conn.cursor() as cur:
                cur.execute(schema_sql)
                if start_date is not None:
                    cur.execute(DELETE_OLD_ROWS_SQL, [start_date])
                cur.execute(TEMP_TABLE_SQL)
                for index, path in enumerate(paths, start=1):
                    rows = rows_from_kline(path, start_date=start_date, target_date=target_date)
                    for batch in batched(rows, args.batch_size):
                        cur.execute(TRUNCATE_TEMP_SQL)
                        with cur.copy(COPY_SQL) as copy:
                            for row in batch:
                                copy.write_row(row)
                        cur.execute(UPSERT_SQL)
                    total_rows += len(rows)
                    if index % 250 == 0:
                        print(f"Processed {index}/{len(paths)} files, {total_rows} rows.", flush=True)
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    summary = {
        "ok": True,
        "target_date": target_date.isoformat() if target_date is not None else None,
        "max_trade_date": max_trade_date.isoformat() if max_trade_date is not None else None,
        "start_date": start_date.isoformat() if start_date is not None else None,
        "kline_dir": str(kline_dir),
        "file_count": len(paths),
        "imported_rows": total_rows,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    write_summary(args.summary_json, summary)

    if target_date is not None:
        print(f"Imported {total_rows} rows for {target_date} from {kline_dir} into stock_daily_metrics.")
    elif start_date is not None:
        print(f"Imported {total_rows} rows from {kline_dir} into stock_daily_metrics since {start_date}.")
    else:
        print(f"Imported {total_rows} rows from {kline_dir} into stock_daily_metrics.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
