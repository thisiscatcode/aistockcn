#!/usr/bin/env python3
"""Build a rule-based pre-explosion A-share watchlist."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from control_settings import exclude_st_from_model_candidates, filter_model_candidate_rows


DEFAULT_DATA_DIR = "quant_data"
DEFAULT_OUTPUT_DIR = "quant_data/pre_explosion"
PATTERN_NAME = "pre_explosion_pattern"
TARGET_HORIZON_DAYS = 10
TARGET_RETURN_THRESHOLD = 0.30

SMOKE_POSITIVE_WINDOWS = {
    "003026": ("2026-04-13", "2026-04-23"),
    "300975": ("2026-05-13", "2026-05-23"),
    "600162": ("2026-05-13", "2026-05-23"),
    "300179": ("2026-05-08", "2026-05-18"),
    "600367": ("2026-05-13", "2026-05-23"),
    "603678": ("2026-05-13", "2026-05-23"),
    "000636": ("2026-04-20", "2026-04-30"),
}

OUTPUT_COLUMNS = [
    "date",
    "code",
    "exchange",
    "name",
    "industry",
    "close",
    "amount",
    "turnover",
    "pct_chg",
    "pre_explosion_score",
    "pattern_name",
    "setup_type",
    "entry_state",
    "reason_tags",
    "ma5",
    "ma10",
    "ma20",
    "high20",
    "low20",
    "high40",
    "low40",
    "bias20",
    "pct_chg_5d",
    "pct_chg_20d",
    "volatility_20d",
    "turnover_ma5",
    "amount_ma20",
    "amount_ratio20",
    "close_to_high20",
    "close_to_low20",
    "close_to_high40",
    "close_to_low40",
    "pct_from_40d_low_close",
    "max_pct_chg_20d",
    "max_amount_ratio20_20d",
    "platform_drawdown_10d",
    "near_limit_up",
    "future_10d_return",
    "target_10d_30",
]


@dataclass(frozen=True)
class PatternThresholds:
    platform_amount_min: float = 500_000_000.0
    platform_smallcap_amount_min: float = 150_000_000.0
    platform_turnover_ma5_min: float = 3.0
    platform_smallcap_turnover_ma5_min: float = 5.0
    platform_close_to_high20_min: float = -0.15
    platform_close_to_low20_min: float = 0.05
    platform_bias20_min: float = -0.08
    low_price_max: float = 5.0
    low_price_amount_min: float = 50_000_000.0
    low_price_turnover_ma5_min: float = 0.5
    low_price_close_to_high20_min: float = -0.15
    strong_day_pct_min: float = 5.0
    low_price_strong_day_pct_min: float = 4.0
    amount_expansion_min: float = 1.5
    extended_ret5: float = 0.25
    extended_ret20: float = 0.60
    extended_bias20: float = 0.25


DEFAULT_THRESHOLDS = PatternThresholds()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the pre-explosion pattern watchlist.")
    parser.add_argument("--data-dir", default=DEFAULT_DATA_DIR)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--limit", type=int, default=0, help="Use only the first N stocks; 0 means all.")
    parser.add_argument("--latest-only", action="store_true", help="Only write the latest watchlist artifact.")
    return parser.parse_args()


def _jsonable(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        number = float(value)
        return None if np.isnan(number) else number
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
    if pd.isna(value):
        return None
    return value


def _safe_ratio(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    cleaned = denominator.replace(0, np.nan)
    return numerator / cleaned


def load_stock_universe(data_dir: Path, limit: int = 0) -> pd.DataFrame:
    stock_path = data_dir / "stock_list.parquet"
    stocks = pd.read_parquet(stock_path)
    stocks["code"] = stocks["code"].astype(str).str.zfill(6)
    if "exchange" not in stocks.columns:
        stocks["exchange"] = np.where(stocks["code"].str.startswith("6"), "sh", "sz")
    stocks["exchange"] = stocks["exchange"].astype(str).str.lower()
    if "name" not in stocks.columns:
        stocks["name"] = stocks["code"]
    if "industry" not in stocks.columns:
        stocks["industry"] = "UNKNOWN"
    stocks["industry"] = stocks["industry"].fillna("UNKNOWN")
    stocks = filter_model_candidate_rows(
        stocks,
        exclude_st=exclude_st_from_model_candidates(data_dir),
    )
    if limit > 0:
        stocks = stocks.head(limit).copy()
    return stocks.reset_index(drop=True)


def enrich_stock_features(kline: pd.DataFrame) -> pd.DataFrame:
    df = kline.sort_values("date").copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    for column in ["open", "high", "low", "close", "volume", "amount", "turnover", "pct_chg"]:
        if column not in df.columns:
            df[column] = np.nan
        df[column] = pd.to_numeric(df[column], errors="coerce")

    close = df["close"]
    amount = df["amount"]
    turnover = df["turnover"]
    df["ma5"] = close.rolling(5).mean()
    df["ma10"] = close.rolling(10).mean()
    df["ma20"] = close.rolling(20).mean()
    df["high20"] = df["high"].rolling(20).max()
    df["low20"] = df["low"].rolling(20).min()
    df["high40"] = df["high"].rolling(40).max()
    df["low40"] = df["low"].rolling(40).min()
    df["pct_chg_5d"] = close.pct_change(5)
    df["pct_chg_20d"] = close.pct_change(20)
    df["bias20"] = _safe_ratio(close, df["ma20"]) - 1
    df["volatility_20d"] = close.rolling(20).std() / df["ma20"]
    df["turnover_ma5"] = turnover.rolling(5).mean()
    df["amount_ma20"] = amount.rolling(20).mean()
    df["amount_ratio20"] = _safe_ratio(amount, df["amount_ma20"])
    df["close_to_high20"] = _safe_ratio(close, df["high20"]) - 1
    df["close_to_low20"] = _safe_ratio(close, df["low20"]) - 1
    df["close_to_high40"] = _safe_ratio(close, df["high40"]) - 1
    df["close_to_low40"] = _safe_ratio(close, df["low40"]) - 1
    df["pct_from_40d_low_close"] = _safe_ratio(close, close.rolling(40).min()) - 1
    df["max_pct_chg_20d"] = df["pct_chg"].rolling(20).max()
    df["max_amount_ratio20_20d"] = df["amount_ratio20"].rolling(20).max()
    df["platform_drawdown_10d"] = _safe_ratio(close, df["high"].rolling(10).max()) - 1
    df["near_limit_up"] = df["pct_chg"] >= 9.5
    df["future_10d_return"] = close.shift(-TARGET_HORIZON_DAYS) / close - 1
    df["target_10d_30"] = df["future_10d_return"] >= TARGET_RETURN_THRESHOLD
    return df


def _score_platform(row: pd.Series, thresholds: PatternThresholds) -> tuple[int, list[str]]:
    tags: list[str] = ["platform"]
    score = 0
    if row["amount"] >= thresholds.platform_amount_min:
        score += 12
        tags.append("high_amount")
    elif row["amount"] >= thresholds.platform_smallcap_amount_min and row["turnover_ma5"] >= thresholds.platform_smallcap_turnover_ma5_min:
        score += 10
        tags.append("active_smallcap_amount")
    if row["turnover_ma5"] >= thresholds.platform_turnover_ma5_min:
        score += 12
        tags.append("active_turnover")
    if row["close_to_high20"] >= -0.05:
        score += 18
        tags.append("near_20d_high")
    elif row["close_to_high20"] >= thresholds.platform_close_to_high20_min:
        score += 10
        tags.append("within_platform")
    if row["close_to_low20"] >= 0.15:
        score += 14
        tags.append("held_above_low")
    elif row["close_to_low20"] >= thresholds.platform_close_to_low20_min:
        score += 8
    if row["bias20"] >= 0.02:
        score += 12
        tags.append("above_ma20")
    elif row["bias20"] >= thresholds.platform_bias20_min:
        score += 6
        tags.append("ma20_supported")
    if row["max_pct_chg_20d"] >= thresholds.strong_day_pct_min:
        score += 12
        tags.append("prior_strong_day")
    if row["max_amount_ratio20_20d"] >= thresholds.amount_expansion_min:
        score += 10
        tags.append("prior_volume_expansion")
    if -8 <= row["pct_chg"] <= 0 and row["close_to_high20"] >= -0.15:
        score += 8
        tags.append("washout")
    if row["pct_chg_5d"] >= -0.05:
        score += 6
        tags.append("short_structure_ok")
    return min(score, 100), tags


def _score_low_price(row: pd.Series, thresholds: PatternThresholds) -> tuple[int, list[str]]:
    tags: list[str] = ["low_price"]
    score = 0
    if row["close"] <= thresholds.low_price_max:
        score += 18
        tags.append("cheap_price")
    if row["amount"] >= thresholds.low_price_amount_min:
        score += 12
        tags.append("liquid_enough")
    if row["turnover_ma5"] >= thresholds.low_price_turnover_ma5_min:
        score += 10
        tags.append("warming_turnover")
    if row["close_to_high20"] >= -0.06:
        score += 16
        tags.append("near_range_high")
    elif row["close_to_high20"] >= thresholds.low_price_close_to_high20_min:
        score += 10
        tags.append("range_recovery")
    if row["max_pct_chg_20d"] >= thresholds.low_price_strong_day_pct_min:
        score += 12
        tags.append("first_strong_day")
    if row["max_amount_ratio20_20d"] >= thresholds.amount_expansion_min:
        score += 12
        tags.append("volume_wakeup")
    if row["pct_chg_20d"] >= -0.08:
        score += 8
        tags.append("base_intact")
    if row["pct_chg"] <= 0:
        score += 6
        tags.append("pre_breakout_rest")
    return min(score, 100), tags


def _entry_state(row: pd.Series, thresholds: PatternThresholds) -> str:
    if (
        row["pct_chg_5d"] >= thresholds.extended_ret5
        or row["pct_chg_20d"] >= thresholds.extended_ret20
        or row["bias20"] >= thresholds.extended_bias20
    ):
        return "EXTENDED"
    if row["near_limit_up"]:
        return "EXTENDED"
    if row["pct_chg"] >= 3 and row["amount_ratio20"] >= 1.2 and row["close_to_high20"] >= -0.08:
        return "TRIGGER"
    if row["close_to_high20"] >= -0.005 and row["amount_ratio20"] >= 1.0:
        return "TRIGGER"
    return "WATCH"


def classify_pattern(row: pd.Series, thresholds: PatternThresholds = DEFAULT_THRESHOLDS) -> dict[str, Any] | None:
    required = [
        "close",
        "amount",
        "turnover_ma5",
        "bias20",
        "close_to_high20",
        "close_to_low20",
        "max_pct_chg_20d",
        "max_amount_ratio20_20d",
    ]
    if any(pd.isna(row.get(column)) for column in required):
        return None
    if row.get("amount", 0) <= 0 or row.get("volume", 0) <= 0:
        return None

    has_prior_signal = (
        row["max_pct_chg_20d"] >= thresholds.strong_day_pct_min
        or row["max_amount_ratio20_20d"] >= thresholds.amount_expansion_min
    )
    platform_standard_match = (
        row["amount"] >= thresholds.platform_amount_min
        and row["turnover_ma5"] >= thresholds.platform_turnover_ma5_min
        and row["close_to_high20"] >= thresholds.platform_close_to_high20_min
        and row["close_to_low20"] >= thresholds.platform_close_to_low20_min
        and row["bias20"] >= thresholds.platform_bias20_min
        and has_prior_signal
    )
    platform_smallcap_match = (
        row["amount"] >= thresholds.platform_smallcap_amount_min
        and row["turnover_ma5"] >= thresholds.platform_smallcap_turnover_ma5_min
        and row["close_to_high20"] >= thresholds.platform_close_to_high20_min
        and row["close_to_low20"] >= thresholds.platform_close_to_low20_min
        and row["bias20"] >= thresholds.platform_bias20_min
        and has_prior_signal
    )
    platform_match = platform_standard_match or platform_smallcap_match

    low_price_signal = (
        row["max_pct_chg_20d"] >= thresholds.low_price_strong_day_pct_min
        or row["max_amount_ratio20_20d"] >= thresholds.amount_expansion_min
    )
    low_price_match = (
        row["close"] <= thresholds.low_price_max
        and row["amount"] >= thresholds.low_price_amount_min
        and row["turnover_ma5"] >= thresholds.low_price_turnover_ma5_min
        and row["close_to_high20"] >= thresholds.low_price_close_to_high20_min
        and low_price_signal
    )
    if not platform_match and not low_price_match:
        return None

    if platform_match:
        score, tags = _score_platform(row, thresholds)
        setup_type = "platform_washout"
    else:
        score, tags = _score_low_price(row, thresholds)
        setup_type = "low_price_reversal"

    state = _entry_state(row, thresholds)
    if state == "TRIGGER":
        score = min(score + 8, 100)
        tags.append("entry_trigger")
    elif state == "EXTENDED":
        tags.append("already_extended")

    return {
        "pre_explosion_score": int(score),
        "pattern_name": PATTERN_NAME,
        "setup_type": setup_type,
        "entry_state": state,
        "reason_tags": "|".join(dict.fromkeys(tags)),
    }


def scan_stock(kline: pd.DataFrame, stock: dict[str, Any]) -> pd.DataFrame:
    features = enrich_stock_features(kline)
    required = [
        "close",
        "amount",
        "volume",
        "turnover_ma5",
        "bias20",
        "close_to_high20",
        "close_to_low20",
        "max_pct_chg_20d",
        "max_amount_ratio20_20d",
    ]
    valid = features[required].notna().all(axis=1) & features["amount"].gt(0) & features["volume"].gt(0)
    has_prior_signal = (
        features["max_pct_chg_20d"].ge(DEFAULT_THRESHOLDS.strong_day_pct_min)
        | features["max_amount_ratio20_20d"].ge(DEFAULT_THRESHOLDS.amount_expansion_min)
    )
    platform_standard_match = (
        features["amount"].ge(DEFAULT_THRESHOLDS.platform_amount_min)
        & features["turnover_ma5"].ge(DEFAULT_THRESHOLDS.platform_turnover_ma5_min)
        & features["close_to_high20"].ge(DEFAULT_THRESHOLDS.platform_close_to_high20_min)
        & features["close_to_low20"].ge(DEFAULT_THRESHOLDS.platform_close_to_low20_min)
        & features["bias20"].ge(DEFAULT_THRESHOLDS.platform_bias20_min)
        & has_prior_signal
    )
    platform_smallcap_match = (
        features["amount"].ge(DEFAULT_THRESHOLDS.platform_smallcap_amount_min)
        & features["turnover_ma5"].ge(DEFAULT_THRESHOLDS.platform_smallcap_turnover_ma5_min)
        & features["close_to_high20"].ge(DEFAULT_THRESHOLDS.platform_close_to_high20_min)
        & features["close_to_low20"].ge(DEFAULT_THRESHOLDS.platform_close_to_low20_min)
        & features["bias20"].ge(DEFAULT_THRESHOLDS.platform_bias20_min)
        & has_prior_signal
    )
    platform_match = platform_standard_match | platform_smallcap_match
    low_price_signal = (
        features["max_pct_chg_20d"].ge(DEFAULT_THRESHOLDS.low_price_strong_day_pct_min)
        | features["max_amount_ratio20_20d"].ge(DEFAULT_THRESHOLDS.amount_expansion_min)
    )
    low_price_match = (
        features["close"].le(DEFAULT_THRESHOLDS.low_price_max)
        & features["amount"].ge(DEFAULT_THRESHOLDS.low_price_amount_min)
        & features["turnover_ma5"].ge(DEFAULT_THRESHOLDS.low_price_turnover_ma5_min)
        & features["close_to_high20"].ge(DEFAULT_THRESHOLDS.low_price_close_to_high20_min)
        & low_price_signal
    )
    candidate_mask = valid & (platform_match | low_price_match)
    if not bool(candidate_mask.any()):
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    result = features.loc[candidate_mask].copy()
    candidate_platform = platform_match.loc[candidate_mask].to_numpy(dtype=bool)
    result["pattern_name"] = PATTERN_NAME
    result["setup_type"] = np.where(candidate_platform, "platform_washout", "low_price_reversal")

    score = np.zeros(len(result), dtype=float)
    platform_idx = result["setup_type"].eq("platform_washout")
    low_price_idx = ~platform_idx

    score += np.where(platform_idx & result["amount"].ge(DEFAULT_THRESHOLDS.platform_amount_min), 12, 0)
    score += np.where(
        platform_idx
        & result["amount"].lt(DEFAULT_THRESHOLDS.platform_amount_min)
        & result["amount"].ge(DEFAULT_THRESHOLDS.platform_smallcap_amount_min)
        & result["turnover_ma5"].ge(DEFAULT_THRESHOLDS.platform_smallcap_turnover_ma5_min),
        10,
        0,
    )
    score += np.where(platform_idx & result["turnover_ma5"].ge(DEFAULT_THRESHOLDS.platform_turnover_ma5_min), 12, 0)
    score += np.where(platform_idx & result["close_to_high20"].ge(-0.05), 18, 0)
    score += np.where(platform_idx & result["close_to_high20"].lt(-0.05) & result["close_to_high20"].ge(DEFAULT_THRESHOLDS.platform_close_to_high20_min), 10, 0)
    score += np.where(platform_idx & result["close_to_low20"].ge(0.15), 14, 0)
    score += np.where(platform_idx & result["close_to_low20"].lt(0.15) & result["close_to_low20"].ge(DEFAULT_THRESHOLDS.platform_close_to_low20_min), 8, 0)
    score += np.where(platform_idx & result["bias20"].ge(0.02), 12, 0)
    score += np.where(platform_idx & result["bias20"].lt(0.02) & result["bias20"].ge(DEFAULT_THRESHOLDS.platform_bias20_min), 6, 0)
    score += np.where(platform_idx & result["max_pct_chg_20d"].ge(DEFAULT_THRESHOLDS.strong_day_pct_min), 12, 0)
    score += np.where(platform_idx & result["max_amount_ratio20_20d"].ge(DEFAULT_THRESHOLDS.amount_expansion_min), 10, 0)
    score += np.where(platform_idx & result["pct_chg"].between(-8, 0) & result["close_to_high20"].ge(-0.15), 8, 0)
    score += np.where(platform_idx & result["pct_chg_5d"].ge(-0.05), 6, 0)

    score += np.where(low_price_idx & result["close"].le(DEFAULT_THRESHOLDS.low_price_max), 18, 0)
    score += np.where(low_price_idx & result["amount"].ge(DEFAULT_THRESHOLDS.low_price_amount_min), 12, 0)
    score += np.where(low_price_idx & result["turnover_ma5"].ge(DEFAULT_THRESHOLDS.low_price_turnover_ma5_min), 10, 0)
    score += np.where(low_price_idx & result["close_to_high20"].ge(-0.06), 16, 0)
    score += np.where(low_price_idx & result["close_to_high20"].lt(-0.06) & result["close_to_high20"].ge(DEFAULT_THRESHOLDS.low_price_close_to_high20_min), 10, 0)
    score += np.where(low_price_idx & result["max_pct_chg_20d"].ge(DEFAULT_THRESHOLDS.low_price_strong_day_pct_min), 12, 0)
    score += np.where(low_price_idx & result["max_amount_ratio20_20d"].ge(DEFAULT_THRESHOLDS.amount_expansion_min), 12, 0)
    score += np.where(low_price_idx & result["pct_chg_20d"].ge(-0.08), 8, 0)
    score += np.where(low_price_idx & result["pct_chg"].le(0), 6, 0)

    extended = (
        result["pct_chg_5d"].ge(DEFAULT_THRESHOLDS.extended_ret5)
        | result["pct_chg_20d"].ge(DEFAULT_THRESHOLDS.extended_ret20)
        | result["bias20"].ge(DEFAULT_THRESHOLDS.extended_bias20)
        | result["near_limit_up"].fillna(False)
    )
    trigger = (
        result["pct_chg"].ge(3)
        & result["amount_ratio20"].ge(1.2)
        & result["close_to_high20"].ge(-0.08)
    ) | (
        result["close_to_high20"].ge(-0.005)
        & result["amount_ratio20"].ge(1.0)
    )
    result["entry_state"] = np.where(extended, "EXTENDED", np.where(trigger, "TRIGGER", "WATCH"))
    score += np.where(result["entry_state"].eq("TRIGGER"), 8, 0)
    result["pre_explosion_score"] = np.clip(score, 0, 100).astype(int)

    def build_tags(row: pd.Series) -> str:
        if row["setup_type"] == "platform_washout":
            tags = ["platform"]
            tags.append("high_amount" if row["amount"] >= DEFAULT_THRESHOLDS.platform_amount_min else "active_smallcap_amount")
            tags.append("active_turnover")
            tags.append("near_20d_high" if row["close_to_high20"] >= -0.05 else "within_platform")
            tags.append("held_above_low" if row["close_to_low20"] >= 0.15 else "platform_low_held")
            tags.append("above_ma20" if row["bias20"] >= 0.02 else "ma20_supported")
            if row["max_pct_chg_20d"] >= DEFAULT_THRESHOLDS.strong_day_pct_min:
                tags.append("prior_strong_day")
            if row["max_amount_ratio20_20d"] >= DEFAULT_THRESHOLDS.amount_expansion_min:
                tags.append("prior_volume_expansion")
            if -8 <= row["pct_chg"] <= 0 and row["close_to_high20"] >= -0.15:
                tags.append("washout")
        else:
            tags = ["low_price", "cheap_price", "liquid_enough", "warming_turnover"]
            tags.append("near_range_high" if row["close_to_high20"] >= -0.06 else "range_recovery")
            if row["max_pct_chg_20d"] >= DEFAULT_THRESHOLDS.low_price_strong_day_pct_min:
                tags.append("first_strong_day")
            if row["max_amount_ratio20_20d"] >= DEFAULT_THRESHOLDS.amount_expansion_min:
                tags.append("volume_wakeup")
            if row["pct_chg_20d"] >= -0.08:
                tags.append("base_intact")
        if row["entry_state"] == "TRIGGER":
            tags.append("entry_trigger")
        elif row["entry_state"] == "EXTENDED":
            tags.append("already_extended")
        return "|".join(dict.fromkeys(tags))

    result["reason_tags"] = result.apply(build_tags, axis=1)
    result["code"] = str(stock.get("code") or "").zfill(6)
    result["exchange"] = str(stock.get("exchange") or "").lower()
    result["name"] = stock.get("name") or ""
    result["industry"] = stock.get("industry") or "UNKNOWN"
    return result.loc[:, OUTPUT_COLUMNS]


def build_watchlist(data_dir: Path, *, limit: int = 0) -> pd.DataFrame:
    stocks = load_stock_universe(data_dir, limit=limit)
    frames: list[pd.DataFrame] = []
    kline_dir = data_dir / "daily_kline"
    for stock in stocks.to_dict(orient="records"):
        code = str(stock["code"]).zfill(6)
        path = kline_dir / f"{code}.parquet"
        if not path.exists():
            continue
        try:
            kline = pd.read_parquet(path)
        except Exception:
            continue
        if len(kline) < 30:
            continue
        frame = scan_stock(kline, stock)
        if not frame.empty:
            frames.append(frame)
    if not frames:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)
    watchlist = pd.concat(frames, ignore_index=True)
    watchlist["date"] = pd.to_datetime(watchlist["date"], errors="coerce")
    watchlist = watchlist.dropna(subset=["date", "code"])
    return watchlist.sort_values(["date", "pre_explosion_score", "amount"], ascending=[True, False, False]).reset_index(drop=True)


def latest_watchlist(history: pd.DataFrame) -> pd.DataFrame:
    if history.empty:
        return history.copy()
    latest_date = history["date"].max()
    latest = history[history["date"].eq(latest_date)].copy()
    return latest.sort_values(["entry_state", "pre_explosion_score", "amount"], ascending=[False, False, False]).reset_index(drop=True)


def build_summary(history: pd.DataFrame, latest: pd.DataFrame, *, data_dir: Path) -> dict[str, Any]:
    completed = history[history["future_10d_return"].notna()].copy() if not history.empty else pd.DataFrame()
    early = completed[completed["entry_state"].ne("EXTENDED")] if not completed.empty else pd.DataFrame()
    smoke_hits: dict[str, Any] = {}
    for code, (start, end) in SMOKE_POSITIVE_WINDOWS.items():
        window = history[
            history["code"].astype(str).str.zfill(6).eq(code)
            & history["date"].between(pd.Timestamp(start), pd.Timestamp(end))
            & history["entry_state"].ne("EXTENDED")
        ] if not history.empty else pd.DataFrame()
        smoke_hits[code] = {
            "hit": bool(not window.empty),
            "first_date": None if window.empty else pd.Timestamp(window["date"].min()).date().isoformat(),
            "best_score": None if window.empty else int(window["pre_explosion_score"].max()),
        }
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pattern_name": PATTERN_NAME,
        "data_dir": str(data_dir),
        "latest_date": None if latest.empty else pd.Timestamp(latest["date"].max()).date().isoformat(),
        "history_rows": int(len(history)),
        "latest_rows": int(len(latest)),
        "latest_watch_rows": int((latest["entry_state"] == "WATCH").sum()) if not latest.empty else 0,
        "latest_trigger_rows": int((latest["entry_state"] == "TRIGGER").sum()) if not latest.empty else 0,
        "latest_extended_rows": int((latest["entry_state"] == "EXTENDED").sum()) if not latest.empty else 0,
        "target_horizon_days": TARGET_HORIZON_DAYS,
        "target_return_threshold": TARGET_RETURN_THRESHOLD,
        "completed_rows": int(len(completed)),
        "early_completed_rows": int(len(early)),
        "early_hit_rate_10d_30": None if early.empty else float(early["target_10d_30"].mean()),
        "early_future_10d_return_mean": None if early.empty else float(early["future_10d_return"].mean()),
        "early_future_10d_return_median": None if early.empty else float(early["future_10d_return"].median()),
        "smoke_positive_hits": smoke_hits,
    }


def normalize_output(df: pd.DataFrame) -> pd.DataFrame:
    output = df.copy()
    for column in OUTPUT_COLUMNS:
        if column not in output.columns:
            output[column] = None
    output = output.loc[:, OUTPUT_COLUMNS]
    output["date"] = pd.to_datetime(output["date"], errors="coerce")
    for column in ["code", "exchange", "name", "industry", "pattern_name", "setup_type", "entry_state", "reason_tags"]:
        output[column] = output[column].fillna("").astype(str)
    for column in [col for col in OUTPUT_COLUMNS if col not in {"date", "code", "exchange", "name", "industry", "setup_type", "entry_state", "reason_tags"}]:
        if column == "target_10d_30" or column == "near_limit_up":
            output[column] = output[column].fillna(False).astype(bool)
        else:
            output[column] = pd.to_numeric(output[column], errors="coerce").astype("float64")
    return output


def write_artifacts(history: pd.DataFrame, output_dir: Path, *, latest_only: bool = False, data_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    latest = normalize_output(latest_watchlist(history))
    history = normalize_output(history)
    latest.to_parquet(output_dir / "watchlist_latest.parquet", index=False)
    if not latest_only:
        history.to_parquet(output_dir / "watchlist_history.parquet", index=False)
    summary = build_summary(history, latest, data_dir=data_dir)
    (output_dir / "summary_latest.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=_jsonable), encoding="utf-8")
    return summary


def main() -> int:
    args = parse_args()
    data_dir = Path(args.data_dir)
    output_dir = Path(args.output_dir)
    history = build_watchlist(data_dir, limit=max(int(args.limit), 0))
    summary = write_artifacts(history, output_dir, latest_only=bool(args.latest_only), data_dir=data_dir)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
