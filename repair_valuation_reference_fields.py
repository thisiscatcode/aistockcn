#!/usr/bin/env python3
"""Repair valuation parquet files using cached share-count reference data."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from download_data import DEFAULT_DATA_DIR, reference_valuation_path


REFERENCE_COLUMNS = ["total_market_cap", "float_market_cap", "total_shares", "float_shares"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fill missing valuation reference fields from local reference cache.")
    parser.add_argument("--data-dir", default=DEFAULT_DATA_DIR, help="Input/output quant data directory.")
    parser.add_argument("--limit", type=int, default=0, help="Only repair the first N valuation files; 0 means all.")
    return parser.parse_args()


def repair_one(data_dir: Path, valuation_path: Path) -> tuple[bool, int]:
    code = valuation_path.stem.zfill(6)
    reference_path = reference_valuation_path(data_dir, code)
    if not reference_path.exists():
        return False, 0

    valuation_df = pd.read_parquet(valuation_path)
    reference_df = pd.read_parquet(reference_path)
    if valuation_df.empty or reference_df.empty or "date" not in valuation_df.columns or "date" not in reference_df.columns:
        return False, 0

    for col in REFERENCE_COLUMNS:
        if col not in valuation_df.columns:
            valuation_df[col] = pd.NA
        if col not in reference_df.columns:
            reference_df[col] = pd.NA

    valuation_df["date"] = pd.to_datetime(valuation_df["date"], errors="coerce").astype("datetime64[ns]")
    reference_df["date"] = pd.to_datetime(reference_df["date"], errors="coerce").astype("datetime64[ns]")
    before_missing = int(valuation_df[REFERENCE_COLUMNS].isna().any(axis=1).sum())
    if before_missing == 0:
        return False, 0

    reference_df = (
        reference_df[["date", "total_shares", "float_shares"]]
        .dropna(subset=["date"])
        .sort_values("date")
        .reset_index(drop=True)
    )
    if reference_df.empty:
        return False, 0

    asof_df = pd.merge_asof(
        valuation_df[["date"]].sort_values("date"),
        reference_df,
        on="date",
        direction="backward",
    ).sort_index()

    for col in ["total_shares", "float_shares"]:
        valuation_df[col] = pd.to_numeric(valuation_df[col], errors="coerce").combine_first(
            pd.to_numeric(asof_df[col], errors="coerce")
        )
    valuation_df["close"] = pd.to_numeric(valuation_df["close"], errors="coerce")

    total_mask = valuation_df["total_market_cap"].isna() & valuation_df["close"].notna() & valuation_df["total_shares"].notna()
    valuation_df.loc[total_mask, "total_market_cap"] = valuation_df.loc[total_mask, "close"] * valuation_df.loc[total_mask, "total_shares"]

    float_mask = valuation_df["float_market_cap"].isna() & valuation_df["close"].notna() & valuation_df["float_shares"].notna()
    valuation_df.loc[float_mask, "float_market_cap"] = valuation_df.loc[float_mask, "close"] * valuation_df.loc[float_mask, "float_shares"]

    after_missing = int(valuation_df[REFERENCE_COLUMNS].isna().any(axis=1).sum())
    repaired_rows = before_missing - after_missing
    if repaired_rows <= 0:
        return False, 0

    valuation_df = valuation_df.sort_values(["date", "code"] if "code" in valuation_df.columns else ["date"]).reset_index(drop=True)
    valuation_df.to_parquet(valuation_path, index=False)
    return True, repaired_rows


def main() -> int:
    args = parse_args()
    data_dir = Path(args.data_dir)
    valuation_paths = sorted((data_dir / "daily_valuation").glob("*.parquet"))
    if args.limit > 0:
        valuation_paths = valuation_paths[: args.limit]

    changed_files = 0
    repaired_rows = 0
    for idx, valuation_path in enumerate(valuation_paths, start=1):
        changed, rows = repair_one(data_dir, valuation_path)
        if changed:
            changed_files += 1
            repaired_rows += rows
        if idx % 500 == 0:
            print(f"checked {idx}/{len(valuation_paths)} files; repaired {changed_files} files, {repaired_rows} rows")

    print(f"valuation repair complete: repaired {changed_files} files, {repaired_rows} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
