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
    parser.add_argument(
        "--overwrite-existing",
        action="store_true",
        help="Overwrite existing reference-derived values when cached reference data is available.",
    )
    return parser.parse_args()


def _changed_rows(before: pd.DataFrame, after: pd.DataFrame) -> int:
    changed = pd.DataFrame(False, index=before.index, columns=before.columns)
    for col in before.columns:
        before_col = pd.to_numeric(before[col], errors="coerce")
        after_col = pd.to_numeric(after[col], errors="coerce")
        changed[col] = ~(before_col.eq(after_col) | (before_col.isna() & after_col.isna()))
    return int(changed.any(axis=1).sum())


def repair_one(data_dir: Path, valuation_path: Path, *, overwrite_existing: bool = False) -> tuple[bool, int]:
    code = valuation_path.stem.zfill(6)
    reference_path = reference_valuation_path(data_dir, code)
    if not reference_path.exists():
        return False, 0

    valuation_df = pd.read_parquet(valuation_path).reset_index(drop=True)
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
    before_values = valuation_df[REFERENCE_COLUMNS].copy()

    dated_rows = pd.DataFrame({"_repair_order": valuation_df.index, "date": valuation_df["date"]}).dropna(subset=["date"])
    if dated_rows.empty:
        return False, 0
    dated_rows = dated_rows.sort_values("date").reset_index(drop=True)

    exact_reference_df = (
        reference_df[["date", *REFERENCE_COLUMNS]]
        .dropna(subset=["date"])
        .sort_values("date")
        .drop_duplicates(subset=["date"], keep="last")
        .reset_index(drop=True)
    )
    share_reference_df = (
        reference_df[["date", "total_shares", "float_shares"]]
        .dropna(subset=["date"])
        .sort_values("date")
        .drop_duplicates(subset=["date"], keep="last")
        .reset_index(drop=True)
    )
    if exact_reference_df.empty or share_reference_df.empty:
        return False, 0

    exact_values = dated_rows.merge(exact_reference_df, on="date", how="left").set_index("_repair_order")
    asof_df = pd.merge_asof(
        dated_rows,
        share_reference_df,
        on="date",
        direction="backward",
    ).set_index("_repair_order")

    for col in ["total_shares", "float_shares"]:
        reference_values = pd.Series(pd.NA, index=valuation_df.index, dtype="Float64")
        if col in asof_df.columns:
            reference_values.loc[asof_df.index] = pd.to_numeric(asof_df[col], errors="coerce").to_numpy()
        current_values = pd.to_numeric(valuation_df[col], errors="coerce")
        if overwrite_existing:
            valuation_df.loc[reference_values.notna(), col] = reference_values.loc[reference_values.notna()]
        else:
            valuation_df[col] = current_values.combine_first(reference_values)

    valuation_df["close"] = pd.to_numeric(valuation_df["close"], errors="coerce")

    cap_specs = [
        ("total_market_cap", "total_shares"),
        ("float_market_cap", "float_shares"),
    ]
    for cap_col, share_col in cap_specs:
        exact_cap = pd.Series(pd.NA, index=valuation_df.index, dtype="Float64")
        if cap_col in exact_values.columns:
            exact_cap.loc[exact_values.index] = pd.to_numeric(exact_values[cap_col], errors="coerce").to_numpy()
        computed_cap = pd.to_numeric(valuation_df["close"], errors="coerce") * pd.to_numeric(
            valuation_df[share_col],
            errors="coerce",
        )
        reference_cap = exact_cap.combine_first(computed_cap)
        current_cap = pd.to_numeric(valuation_df[cap_col], errors="coerce")
        if overwrite_existing:
            valuation_df.loc[reference_cap.notna(), cap_col] = reference_cap.loc[reference_cap.notna()]
        else:
            valuation_df[cap_col] = current_cap.combine_first(reference_cap)

    repaired_rows = _changed_rows(before_values, valuation_df[REFERENCE_COLUMNS])
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
        changed, rows = repair_one(data_dir, valuation_path, overwrite_existing=args.overwrite_existing)
        if changed:
            changed_files += 1
            repaired_rows += rows
        if idx % 500 == 0:
            print(f"checked {idx}/{len(valuation_paths)} files; repaired {changed_files} files, {repaired_rows} rows")

    print(f"valuation repair complete: repaired {changed_files} files, {repaired_rows} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
