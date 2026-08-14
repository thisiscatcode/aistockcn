#!/usr/bin/env python3
"""Checkpointed Massive daily OHLCV backfill with explicit adjustment and lineage."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))
from app.services.us_market import US_MODEL_DATA_SCHEMA_SQL


def request_json(url: str, *, attempts: int = 6) -> dict[str, Any]:
    request = Request(url, headers={"User-Agent": "AiStockCN/1.0 research@aistockcn.com"})
    for attempt in range(attempts):
        try:
            with urlopen(request, timeout=45) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            retryable = exc.code == 429 or 500 <= exc.code < 600
            if not retryable or attempt + 1 >= attempts:
                raise
            retry_after = exc.headers.get("Retry-After")
            delay = float(retry_after) if retry_after and retry_after.isdigit() else min(60.0, 5.0 * (2**attempt))
        except (TimeoutError, URLError):
            if attempt + 1 >= attempts:
                raise
            delay = min(60.0, 5.0 * (2**attempt))
        time.sleep(delay)
    raise RuntimeError("massive_retry_exhausted")


def fetch_bars(symbol: str, start: date, end: date, api_key: str) -> list[dict[str, Any]]:
    query = urlencode({"adjusted": "true", "sort": "asc", "limit": "50000", "apiKey": api_key})
    url = f"https://api.massive.com/v2/aggs/ticker/{quote(symbol)}/range/1/day/{start}/{end}?{query}"
    payload = request_json(url)
    if payload.get("status") not in {"OK", "DELAYED"}:
        raise RuntimeError(str(payload.get("error") or payload.get("message") or "massive_request_failed"))
    return payload.get("results") if isinstance(payload.get("results"), list) else []


def payload_hash(row: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(row, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--years", type=int, default=3)
    parser.add_argument("--date-to", default=date.today().isoformat())
    parser.add_argument("--limit", type=int)
    parser.add_argument("--symbols", default="")
    parser.add_argument("--resume-run-id")
    parser.add_argument("--sleep-seconds", type=float, default=float(os.getenv("US_BACKFILL_SLEEP_SECONDS", "12")))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    database_url = os.environ.get("PAPER_DB_URL", "").strip()
    api_key = os.environ.get("MASSIVE_API_KEY", "").strip()
    if not database_url or not api_key:
        raise RuntimeError("PAPER_DB_URL and MASSIVE_API_KEY are required")
    date_to = date.fromisoformat(args.date_to)
    date_from = date_to - timedelta(days=max(1, args.years) * 366)
    run_id = args.resume_run_id or str(uuid4())
    requested = [item.strip().upper() for item in args.symbols.split(",") if item.strip()]

    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(US_MODEL_DATA_SCHEMA_SQL)
            if not requested:
                cur.execute("select symbol from us_stock_master where is_active and not del_flg order by fav_flg desc, market_cap desc nulls last, symbol")
                requested = [str(row["symbol"]) for row in cur.fetchall()]
            if args.limit:
                requested = requested[: max(1, args.limit)]
            cur.execute(
                """
                insert into us_market_ingestion_runs(id, provider, adjustment_state, date_from, date_to, status, requested_symbols)
                values (%s, 'MASSIVE', 'adjusted', %s, %s, 'running', %s)
                on conflict (id) do update set status = 'running', last_error = null
                """,
                [run_id, date_from, date_to, len(requested)],
            )
            cur.execute("select checkpoint from us_market_ingestion_runs where id = %s", [run_id])
            checkpoint = dict((cur.fetchone() or {}).get("checkpoint") or {})
        conn.commit()

        done = set(checkpoint.get("completed_symbols") or [])
        failures: dict[str, str] = dict(checkpoint.get("failures") or {})
        total_rows = int(checkpoint.get("row_count") or 0)
        for index, symbol in enumerate(requested, start=1):
            if symbol in done:
                continue
            try:
                bars = fetch_bars(symbol, date_from, date_to, api_key)
                rows = []
                for bar in bars:
                    timestamp = int(bar["t"])
                    trade_date = datetime.fromtimestamp(timestamp / 1000, tz=UTC).date()
                    rows.append((trade_date, symbol, bar["o"], bar["h"], bar["l"], bar["c"], bar["v"], bar.get("vw"), bar.get("n"), timestamp, run_id, payload_hash(bar)))
                with conn.cursor() as cur:
                    cur.executemany(
                        """
                        insert into us_stock_daily_bars(
                          trade_date, symbol, open, high, low, close, volume, vwap,
                          transaction_count, provider, adjustment_state, provider_timestamp,
                          ingestion_run_id, source_payload_sha256
                        ) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,'MASSIVE','adjusted',%s,%s,%s)
                        on conflict (trade_date, symbol, provider, adjustment_state) do update set
                          open=excluded.open, high=excluded.high, low=excluded.low, close=excluded.close,
                          volume=excluded.volume, vwap=excluded.vwap, transaction_count=excluded.transaction_count,
                          provider_timestamp=excluded.provider_timestamp, ingestion_run_id=excluded.ingestion_run_id,
                          source_payload_sha256=excluded.source_payload_sha256, imported_at=now()
                        """,
                        rows,
                    )
                conn.commit()
                done.add(symbol)
                failures.pop(symbol, None)
                total_rows += len(rows)
            except Exception as exc:
                conn.rollback()
                failures[symbol] = str(exc)[:500]
            checkpoint = {"completed_symbols": sorted(done), "failures": failures, "row_count": total_rows, "last_symbol": symbol}
            with conn.cursor() as cur:
                cur.execute(
                    """update us_market_ingestion_runs set completed_symbols=%s, failed_symbols=%s,
                       row_count=%s, checkpoint=%s::jsonb where id=%s""",
                    [len(done), len(failures), total_rows, json.dumps(checkpoint), run_id],
                )
            conn.commit()
            print(f"[{index}/{len(requested)}] {symbol}: {len(done)} complete, {len(failures)} failed", flush=True)
            if index < len(requested):
                time.sleep(max(0.0, args.sleep_seconds))

        final_status = "completed" if not failures else "partial"
        with conn.cursor() as cur:
            cur.execute(
                "update us_market_ingestion_runs set status=%s, completed_at=now(), last_error=%s where id=%s",
                [final_status, next(iter(failures.values()), None), run_id],
            )
        conn.commit()
    print(json.dumps({"run_id": run_id, "status": final_status, "symbols": len(done), "failures": len(failures), "rows": total_rows}))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
