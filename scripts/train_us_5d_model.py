#!/usr/bin/env python3
"""Train and validate the isolated US 5-day model; never activates it automatically."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import lightgbm as lgb
import numpy as np
import pandas as pd
import psycopg


PROFILE = "us_5d_v1"
HORIZON = 5
PURGE_DAYS = 5
MIN_DATES = 504
ROUND_TRIP_COST_BPS = 20.0


def features(frame: pd.DataFrame) -> pd.DataFrame:
    data = frame.sort_values(["symbol", "trade_date"]).copy()
    grouped = data.groupby("symbol", group_keys=False)
    data["return_1d"] = grouped["close"].pct_change(1)
    data["momentum_5d"] = grouped["close"].pct_change(5)
    data["momentum_20d"] = grouped["close"].pct_change(20)
    data["volatility_20d"] = grouped["return_1d"].rolling(20).std().reset_index(level=0, drop=True)
    volume_mean = grouped["volume"].rolling(20).mean().reset_index(level=0, drop=True)
    volume_std = grouped["volume"].rolling(20).std().reset_index(level=0, drop=True)
    data["volume_z20"] = (data["volume"] - volume_mean) / volume_std.replace(0, np.nan)
    data["range_pct"] = (data["high"] - data["low"]) / data["close"].replace(0, np.nan)
    data["target_5d"] = grouped["close"].shift(-HORIZON) / data["close"] - 1
    return data.replace([np.inf, -np.inf], np.nan)


def rank_ic(group: pd.DataFrame) -> float:
    if group["score"].nunique() < 2 or group["target_5d"].nunique() < 2:
        return np.nan
    return float(group["score"].corr(group["target_5d"], method="spearman"))


def validate(data: pd.DataFrame, feature_names: list[str]) -> tuple[dict[str, float | int], pd.DataFrame]:
    dates = sorted(pd.to_datetime(data["trade_date"]).dt.date.unique())
    if len(dates) < MIN_DATES:
        raise RuntimeError(f"requires_{MIN_DATES}_trading_dates")
    boundaries = [int(len(dates) * fraction) for fraction in (0.60, 0.72, 0.84)]
    predictions: list[pd.DataFrame] = []
    for fold, split in enumerate(boundaries, start=1):
        validation_end = boundaries[fold] if fold < len(boundaries) else len(dates)
        train_dates = dates[: max(0, split - PURGE_DAYS)]
        validation_dates = dates[split:validation_end]
        train = data[data["trade_date"].dt.date.isin(train_dates)].dropna(subset=feature_names + ["target_5d"])
        test = data[data["trade_date"].dt.date.isin(validation_dates)].dropna(subset=feature_names + ["target_5d"])
        if train.empty or test.empty:
            continue
        model = lgb.LGBMRegressor(n_estimators=240, learning_rate=0.035, num_leaves=31, subsample=0.8, colsample_bytree=0.85, random_state=2026 + fold, verbosity=-1)
        model.fit(train[feature_names], train["target_5d"])
        scored = test[["trade_date", "symbol", "target_5d"]].copy()
        scored["score"] = model.predict(test[feature_names])
        scored["fold"] = fold
        predictions.append(scored)
    if not predictions:
        raise RuntimeError("walk_forward_has_no_predictions")
    result = pd.concat(predictions, ignore_index=True)
    daily_ic = result.groupby("trade_date", group_keys=False).apply(rank_ic).dropna()
    result["percentile"] = result.groupby("trade_date")["score"].rank(pct=True)
    selected = result[result["percentile"] >= 0.9]
    gross_return = float(selected["target_5d"].mean()) if not selected.empty else float("nan")
    net_return = gross_return - ROUND_TRIP_COST_BPS / 10000.0
    metrics: dict[str, float | int] = {
        "folds": int(result["fold"].nunique()),
        "observations": int(len(result)),
        "mean_daily_rank_ic": float(daily_ic.mean()),
        "positive_ic_rate": float((daily_ic > 0).mean()),
        "top_decile_gross_return_5d": gross_return,
        "top_decile_net_return_5d": net_return,
        "round_trip_cost_bps": ROUND_TRIP_COST_BPS,
        "purge_days": PURGE_DAYS,
    }
    return metrics, result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", default="quant/model_registry/US")
    args = parser.parse_args()
    database_url = os.environ.get("PAPER_DB_URL", "").strip()
    if not database_url:
        raise RuntimeError("PAPER_DB_URL is required")
    with psycopg.connect(database_url) as conn:
        frame = pd.read_sql_query(
            """select b.trade_date, b.symbol, b.open, b.high, b.low, b.close, b.volume
               from us_stock_daily_bars b join us_stock_master m on m.symbol=b.symbol
               where b.provider='MASSIVE' and b.adjustment_state='adjusted' and m.is_active and not m.del_flg
               order by b.symbol, b.trade_date""",
            conn,
        )
    if frame.empty:
        raise RuntimeError("us_adjusted_bars_not_available")
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    prepared = features(frame)
    names = ["return_1d", "momentum_5d", "momentum_20d", "volatility_20d", "volume_z20", "range_pct"]
    metrics, predictions = validate(prepared, names)
    train = prepared.dropna(subset=names + ["target_5d"])
    model = lgb.LGBMRegressor(n_estimators=300, learning_rate=0.03, num_leaves=31, subsample=0.85, colsample_bytree=0.85, random_state=2026, verbosity=-1)
    model.fit(train[names], train["target_5d"])
    latest_date = prepared["trade_date"].max()
    latest = prepared[prepared["trade_date"] == latest_date].dropna(subset=names).copy()
    latest["score"] = model.predict(latest[names])
    latest["rank"] = latest["score"].rank(ascending=False, method="first").astype(int)
    passed = bool(metrics["mean_daily_rank_ic"] > 0 and metrics["top_decile_net_return_5d"] > 0 and metrics["folds"] >= 3)
    trained_at = datetime.now(UTC)
    version_seed = f"{PROFILE}:{trained_at.isoformat()}:{len(train)}"
    version = f"us-{PROFILE}-{trained_at:%Y%m%dT%H%M%SZ}-{hashlib.sha256(version_seed.encode()).hexdigest()[:8]}"
    output = Path(args.output_root) / version
    output.mkdir(parents=True, exist_ok=False)
    model.booster_.save_model(str(output / "lightgbm_model.txt"))
    latest[["trade_date", "symbol", "rank", "score", *names]].to_parquet(output / "inference_scores_latest.parquet", index=False)
    metadata = {
        "profile_name": PROFILE, "market": "US", "horizon_trading_days": HORIZON,
        "trained_at": trained_at.isoformat(), "train_date_min": str(train["trade_date"].min().date()),
        "train_date_max": str(train["trade_date"].max().date()), "score_date": str(latest_date.date()),
        "features": names, "metrics": metrics, "validation_status": "passed" if passed else "failed",
        "data_contract": {"provider": "MASSIVE", "adjustment_state": "adjusted", "currency": "USD", "calendar": "US"},
    }
    (output / "training_metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    registry = {"id": str(uuid4()), "market": "US", "model_version": version, "profile": PROFILE, "trained_at": trained_at.isoformat(), "validation_status": metadata["validation_status"]}
    (output / "registry_record.json").write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"model_version": version, "validation_status": metadata["validation_status"], "metrics": metrics}))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
