#!/usr/bin/env python3
"""Refresh slow-moving reference data outside the daily Step 1 batch.

This job is intentionally separate from ``batch_download_all_a.py`` so the
daily market-data refresh can stay fast. Operators can run this batch manually
when the system is idle to refresh:

- industry metadata on the canonical stock lists
- dated AkShare valuation/share history cached under ``quant_data/reference``

The resulting cache is then reused by the normal daily Step 1 pipeline.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import FrameType
from typing import Any

import download_data as dl
from repair_valuation_reference_fields import repair_one


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh slow-moving industry and reference valuation data.")
    parser.add_argument("--data-dir", default=dl.DEFAULT_DATA_DIR, help="Output data directory.")
    parser.add_argument("--start-date", default=dl.DEFAULT_START_DATE, help="Start date in YYYYMMDD format.")
    parser.add_argument(
        "--end-date",
        default=datetime.now(timezone.utc).strftime("%Y%m%d"),
        help="End date in YYYYMMDD format.",
    )
    parser.add_argument("--sleep", type=float, default=0.2, help="Seconds to sleep between symbols.")
    parser.add_argument("--limit", type=int, default=0, help="Only refresh the first N stocks; 0 means all.")
    parser.add_argument("--skip-industry", action="store_true", help="Skip refreshing industry metadata.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing reference valuation files.")
    parser.add_argument(
        "--symbol-timeout-seconds",
        type=int,
        default=int(os.getenv("REFERENCE_SYMBOL_TIMEOUT_SECONDS", "300")),
        help="Maximum seconds to spend on one stock before recording a failure and moving on; 0 disables the timeout.",
    )
    parser.add_argument(
        "--state-file",
        default="quant_data/batch_state/reference_data_state.json",
        help="State file path for progress tracking.",
    )
    return parser.parse_args()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class SymbolTimeoutError(TimeoutError):
    pass


@contextmanager
def symbol_timeout(seconds: int, code: str) -> Any:
    if seconds <= 0:
        yield
        return

    previous_handler = signal.getsignal(signal.SIGALRM)

    def _handle_timeout(signum: int, frame: FrameType | None) -> None:
        raise SymbolTimeoutError(f"{code} exceeded {seconds}s symbol timeout")

    signal.signal(signal.SIGALRM, _handle_timeout)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous_handler)


def load_active_universe(data_dir: Path, *, limit: int) -> Any:
    stock_df = dl.load_canonical_active_stock_list(data_dir)
    if stock_df.empty:
        raise SystemExit("stock_list.parquet is missing or empty. Run the Step 1 daily batch first.")
    if limit > 0:
        stock_df = stock_df.head(limit).copy()
    return stock_df.reset_index(drop=True)


def resolve_trade_date(stock_df: Any, fallback_end_date: str) -> str:
    if "trade_date" in stock_df.columns:
        trade_date = dl.pd.to_datetime(stock_df["trade_date"], errors="coerce").max()
        if not dl.pd.isna(trade_date):
            return dl.pd.Timestamp(trade_date).strftime("%Y-%m-%d")
    return dl.pd.to_datetime(fallback_end_date, format="%Y%m%d").strftime("%Y-%m-%d")


def load_state(state_path: Path, *, total_codes: int, start_date: str, end_date: str) -> dict[str, Any]:
    if state_path.exists():
        try:
            payload = json.loads(state_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            payload = {}
    else:
        payload = {}

    return {
        "created_at": payload.get("created_at", utc_now_iso()),
        "updated_at": utc_now_iso(),
        "completed_at": None,
        "start_date": start_date,
        "end_date": end_date,
        "total_codes": int(total_codes),
        "done_codes": [],
        "failed_codes": {},
        "last_code": "",
        "last_error": None,
    }


def save_state(state_path: Path, state: dict[str, Any]) -> None:
    state["updated_at"] = utc_now_iso()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def update_industry_tables(data_dir: Path, industry_updates: list[dict[str, Any]]) -> None:
    if not industry_updates:
        return

    updates_df = dl.pd.DataFrame(industry_updates)
    stock_list_path = data_dir / dl.STOCK_LIST_FILENAME
    registry_path = data_dir / dl.STOCK_REGISTRY_FILENAME

    if stock_list_path.exists():
        stock_df = dl.pd.read_parquet(stock_list_path)
        stock_df = dl.apply_industry_updates(stock_df, updates_df)
        stock_df.to_parquet(stock_list_path, index=False)

    if registry_path.exists():
        registry_df = dl.pd.read_parquet(registry_path)
        registry_df = dl.apply_industry_updates(registry_df, updates_df)
        registry_df.to_parquet(registry_path, index=False)


def publish_daily_valuation_reference(data_dir: Path) -> dict[str, int]:
    valuation_paths = sorted((data_dir / "daily_valuation").glob("*.parquet"))
    changed_files = 0
    changed_rows = 0
    for idx, valuation_path in enumerate(valuation_paths, start=1):
        changed, rows = repair_one(data_dir, valuation_path, overwrite_existing=True)
        if changed:
            changed_files += 1
            changed_rows += rows
        if idx % 500 == 0:
            print(
                f"Published reference values into daily valuation: checked {idx}/{len(valuation_paths)}, "
                f"changed_files={changed_files}, changed_rows={changed_rows}",
                flush=True,
            )
    return {
        "checked_files": len(valuation_paths),
        "changed_files": changed_files,
        "changed_rows": changed_rows,
    }


def upsert_stock_master(data_dir: Path, *, database_url: str) -> None:
    root_dir = Path(__file__).resolve().parent
    command = [
        sys.executable,
        str(root_dir / "scripts" / "import_stock_list_to_postgres.py"),
        "--stock-list",
        str(data_dir / dl.STOCK_LIST_FILENAME),
        "--database-url",
        database_url,
    ]
    completed = subprocess.run(command, check=False, cwd=root_dir)
    if completed.returncode != 0:
        raise RuntimeError(f"stock_master stock-list upsert failed with exit code {completed.returncode}.")


def run_fei_stock_attributes(data_dir: Path) -> None:
    database_url = os.getenv("APP_DB_URL") or os.getenv("PAPER_DB_URL")
    if not database_url:
        raise RuntimeError("APP_DB_URL or PAPER_DB_URL is required to run Fei stock attributes after reference refresh.")

    root_dir = Path(__file__).resolve().parent
    upsert_stock_master(data_dir, database_url=database_url)
    command = [
        sys.executable,
        str(root_dir / "scripts" / "import_stock_master_attributes.py"),
        "--valuation-dir",
        str(data_dir / "daily_valuation"),
        "--stock-list",
        str(data_dir / dl.STOCK_LIST_FILENAME),
        "--database-url",
        database_url,
        "--sleep",
        os.getenv("FEI_STOCK_ATTRIBUTES_SLEEP", "3"),
        "--status-file",
        "run/fei_stock_attributes_status.json",
        "--checkpoint-file",
        "run/fei_stock_attributes_checkpoint.json",
    ]
    completed = subprocess.run(command, check=False, cwd=root_dir)
    if completed.returncode != 0:
        raise RuntimeError(f"Fei stock attributes failed with exit code {completed.returncode}.")


def publish_reference_outputs(data_dir: Path) -> dict[str, Any]:
    print("Publishing reference data into daily valuation parquet files...", flush=True)
    valuation_summary = publish_daily_valuation_reference(data_dir)
    print("Running full Fei stock attributes sync...", flush=True)
    run_fei_stock_attributes(data_dir)
    return {
        "daily_valuation": valuation_summary,
        "stock_master_upserted": True,
        "fei_stock_attributes_synced": True,
    }


def needs_reference_refresh(*, data_dir: Path, code: str, target_trade_date: str, overwrite: bool) -> bool:
    if overwrite:
        return True
    latest_cached_date = dl.latest_date_in_parquet(dl.reference_valuation_path(data_dir, code))
    if latest_cached_date is None:
        return True
    target_trade_ts = dl.pd.to_datetime(target_trade_date, errors="coerce")
    if dl.pd.isna(target_trade_ts):
        return False
    return latest_cached_date < dl.pd.Timestamp(target_trade_ts).normalize()


def main() -> int:
    args = parse_args()
    data_dir = Path(args.data_dir)
    state_path = Path(args.state_file)

    dl.load_dependencies()
    dl.ensure_reference_dirs(data_dir)
    stock_df = load_active_universe(data_dir, limit=args.limit)
    trade_date = resolve_trade_date(stock_df, args.end_date)
    state = load_state(
        state_path,
        total_codes=len(stock_df),
        start_date=args.start_date,
        end_date=args.end_date,
    )
    save_state(state_path, state)

    industry_updates: list[dict[str, Any]] = []
    needs_baostock = not args.skip_industry

    if needs_baostock:
        dl.baostock_login()

    try:
        print(f"Slow-reference stock count: {len(stock_df)}")
        print(f"State file: {state_path}")
        print(f"Target trading day: {trade_date}")
        print(f"Per-symbol timeout: {args.symbol_timeout_seconds}s")

        records = stock_df.to_dict(orient="records")
        for idx, stock in enumerate(records, start=1):
            code = str(stock.get("code", "")).zfill(6)
            exchange = dl.normalize_exchange(stock.get("exchange"))
            state["last_code"] = code
            state["last_error"] = None
            print(f"[reference {idx}/{len(records)}] Refreshing slow reference data: {code}")

            try:
                if not args.skip_industry and (
                    args.overwrite or not dl._is_known_category_value(stock.get("industry"))
                ):
                    industry_row = dl.get_stock_industry(code, exchange, trade_date)
                    industry_updates.append(
                        {
                            "code": code,
                            "exchange": exchange,
                            "industry": industry_row.get("industry"),
                            "industry_classification": industry_row.get("industry_classification"),
                        }
                    )

                if needs_reference_refresh(
                    data_dir=data_dir,
                    code=code,
                    target_trade_date=trade_date,
                    overwrite=args.overwrite,
                ):
                    with symbol_timeout(args.symbol_timeout_seconds, code):
                        reference_df = dl.fetch_market_cap_df(code, args.start_date, args.end_date)
                    reference_path = dl.reference_valuation_path(data_dir, code)
                    reference_df.to_parquet(reference_path, index=False)

                state["done_codes"] = sorted(set([*state["done_codes"], code]))
                state["failed_codes"].pop(code, None)
                print(f"{code} completed")
            except Exception as exc:  # pragma: no cover - network/API dependent
                message = str(exc)
                state["failed_codes"][code] = message
                state["last_error"] = message
                print(f"{code} failed: {message}")

            save_state(state_path, state)
            time.sleep(args.sleep)

        update_industry_tables(data_dir, industry_updates)
        refreshed_stock_df = load_active_universe(data_dir, limit=0)
        state["completed_at"] = utc_now_iso()
        save_state(state_path, state)
        status_path = dl.write_reference_status(
            data_dir,
            stock_df=refreshed_stock_df,
            target_trade_date=trade_date,
            batch_state=state,
        )
        publish_error = None
        publish_summary: dict[str, Any] | None = None
        try:
            publish_summary = publish_reference_outputs(data_dir)
        except Exception as exc:
            publish_error = str(exc)
            print(f"Reference publish failed: {publish_error}", flush=True)

        summary = {
            "finished": True,
            "total_codes": len(stock_df),
            "done_codes": len(state["done_codes"]),
            "failed_codes": len(state["failed_codes"]),
            "state_file": str(state_path),
            "reference_status": str(status_path),
            "publish": publish_summary,
            "publish_error": publish_error,
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        if publish_error:
            return 3
        return 0 if not state["failed_codes"] else 2
    finally:
        if needs_baostock:
            dl.baostock_logout()


if __name__ == "__main__":
    raise SystemExit(main())
