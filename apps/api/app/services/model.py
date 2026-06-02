from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa

from app.config import get_settings
from app.serializers import records_to_json, to_jsonable
from app.services.files import read_json
from app.services.admin_settings import filter_model_candidate_rows
from app.services.model_profiles import get_model_profile_catalog, set_active_model_profile

TRUSTED_BACKTEST_METHOD_VERSIONS = {
    "purged_label_horizon_v1",
    "purged_label_horizon_costs_v2",
}
LOBSTER_PICK_KLINE_COLUMNS = ["date", "code", "exchange", "close", "volume", "amount", "turnover"]
LOBSTER_PICK_VALUATION_COLUMNS = ["date", "code", "exchange", "float_market_cap"]
_LOBSTER_PICK_CACHE: dict[str, Any] = {}


def _safe_read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except (OSError, UnicodeDecodeError, ValueError, pd.errors.ParserError):
        return pd.DataFrame()


def _safe_read_parquet(path: Path, columns: list[str] | None = None) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_parquet(path, columns=columns)
    except (pa.ArrowException, OSError, ValueError):
        return pd.DataFrame()


def _safe_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(number):
        return None
    return number


def _date_string(value: Any) -> str | None:
    date_value = pd.to_datetime(value, errors="coerce")
    if pd.isna(date_value):
        return None
    return pd.Timestamp(date_value).date().isoformat()


def _code_board(code: str) -> str:
    if code.startswith(("300", "301")):
        return "创业板"
    return "主板"


def _is_lobster_allowed_code(code: str) -> bool:
    return code.startswith(("000", "001", "002", "003", "300", "301", "600", "601", "603", "605"))


def _lobster_cache_key(settings: Any) -> str:
    parts: list[str] = []
    for path in [settings.stock_list_path, settings.quant_dir / "inference_features_latest.parquet"]:
        try:
            stat = path.stat()
            parts.append(f"{path.name}:{stat.st_mtime_ns}:{stat.st_size}")
        except OSError:
            parts.append(f"{path.name}:missing")
    return "|".join(parts)


def _slice_lobster_payload(payload: dict[str, Any], limit: int) -> dict[str, Any]:
    safe_limit = max(min(int(limit or 100), 500), 1)
    rows = list(payload.get("picks") or [])
    limited_rows = rows[:safe_limit]
    return {
        **payload,
        "returned": int(len(limited_rows)),
        "limit": safe_limit,
        "picks": limited_rows,
    }


def _file_updated_at(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat()
    except OSError:
        return None


def _artifact_status(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {"path": None, "exists": False, "updated_at": None}
    return {
        "path": str(path),
        "exists": path.exists(),
        "updated_at": _file_updated_at(path),
    }


def _profile_model_dir(profile_name: str | None) -> Path | None:
    if not profile_name:
        return None
    return get_settings().quant_dir / "model_profiles" / profile_name / "models"


def _production_model_dir() -> Path:
    return get_settings().models_dir


def _copy_file_if_exists(source: Path, destination: Path) -> bool:
    if not source.exists():
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(source.read_bytes())
    return True


def _sync_profile_to_production(profile_name: str) -> dict[str, Any]:
    profile_dir = _profile_model_dir(profile_name)
    if profile_dir is None:
        raise ValueError("profile name is required")
    production_dir = _production_model_dir()
    copied: list[str] = []
    missing: list[str] = []
    for name in ["lightgbm_model.txt", "feature_importance.csv", "training_metadata.json", "inference_scores_latest.parquet"]:
        if _copy_file_if_exists(profile_dir / name, production_dir / name):
            copied.append(name)
        else:
            missing.append(name)
    if "inference_scores_latest.parquet" in missing or "training_metadata.json" in missing:
        raise FileNotFoundError(f"profile {profile_name} is missing required model artifacts: {', '.join(missing)}")
    return {"copied": copied, "missing": missing}


def _parquet_date_max(path: Path, *, column: str) -> str | None:
    frame = _safe_read_parquet(path, columns=[column])
    if frame.empty or column not in frame.columns:
        return None
    date_series = pd.to_datetime(frame[column], errors="coerce")
    if date_series.dropna().empty:
        return None
    return pd.Timestamp(date_series.max()).date().isoformat()


def _enrich_backtest_profile(
    summary: dict[str, Any],
    profiles: list[dict[str, Any]],
    *,
    fallback_to_first: bool = True,
) -> dict[str, Any]:
    if not summary:
        return {}
    if summary.get("profile_name") and summary.get("profile_label"):
        return summary

    candidate = None
    for profile in profiles:
        if (
            summary.get("rebalance_every") == profile.get("backtest_rebalance_every")
            and summary.get("retrain_every") == profile.get("backtest_retrain_every")
            and summary.get("top_k") == profile.get("backtest_top_k")
            and summary.get("threshold") == profile.get("score_threshold")
        ):
            candidate = profile
            break
    if candidate is None and profiles and fallback_to_first:
        candidate = profiles[0]
    if candidate is None:
        return summary

    enriched = dict(summary)
    enriched.setdefault("profile_name", candidate.get("name"))
    enriched.setdefault("profile_label", candidate.get("label"))
    return enriched


def _annotate_backtest_trust(summary: dict[str, Any]) -> dict[str, Any]:
    if not summary:
        return {}
    annotated = dict(summary)
    is_trustworthy = annotated.get("method_version") in TRUSTED_BACKTEST_METHOD_VERSIONS
    annotated["is_trustworthy"] = is_trustworthy
    if not is_trustworthy:
        annotated["trust_warning"] = (
            "Legacy backtest artifact. Rerun this profile with the purged walk-forward backtest before using these performance numbers."
        )
    return annotated


def _profile_name(value: Any) -> str | None:
    profile_name = str(value or "").strip()
    return profile_name or None


def _profile_label(profile_name: str | None, profiles: list[dict[str, Any]]) -> str | None:
    if not profile_name:
        return None
    for profile in profiles:
        if profile.get("name") == profile_name:
            return str(profile.get("label") or profile_name)
    return profile_name


def _backtest_summary_entry_for_profile(profile_name: str | None, profiles: list[dict[str, Any]]) -> tuple[dict[str, Any], Path | None]:
    if not profile_name:
        return {}, None

    settings = get_settings()
    runs_dir = settings.backtests_dir / "runs"
    candidate_paths = list(runs_dir.glob("*/summary.json"))
    latest_path = settings.backtests_dir / "summary.json"
    if latest_path.exists():
        candidate_paths.append(latest_path)
    summary_files = sorted(set(candidate_paths), key=lambda path: path.stat().st_mtime, reverse=True)
    for summary_path in summary_files:
        summary = _enrich_backtest_profile(read_json(summary_path), profiles, fallback_to_first=False)
        if _profile_name(summary.get("profile_name")) == profile_name:
            return _annotate_backtest_trust(summary), summary_path
    return {}, None


def _backtest_summary_for_profile(profile_name: str | None, profiles: list[dict[str, Any]]) -> dict[str, Any]:
    summary, _summary_path = _backtest_summary_entry_for_profile(profile_name, profiles)
    return summary


def _backtest_equity_curve(summary_path: Path | None) -> tuple[list[dict[str, Any]], Path | None]:
    if summary_path is None:
        return [], None
    equity_path = summary_path.parent / "equity_curve.parquet"
    equity_df = _safe_read_parquet(equity_path)
    if equity_df.empty:
        return [], equity_path
    columns = [
        column
        for column in ["rebalance_date", "portfolio_return", "equity", "num_picks"]
        if column in equity_df.columns
    ]
    if "rebalance_date" not in columns or "equity" not in columns:
        return [], equity_path
    equity_df = equity_df.loc[:, columns].copy()
    equity_df["rebalance_date"] = pd.to_datetime(equity_df["rebalance_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    equity_df = equity_df.dropna(subset=["rebalance_date"])
    return records_to_json(equity_df.to_dict(orient="records")), equity_path


def _backtest_run_rows() -> list[dict[str, Any]]:
    settings = get_settings()
    catalog = get_model_profile_catalog()
    profiles = catalog["profiles"]
    label_by_name = {profile["name"]: profile["label"] for profile in profiles}
    runs_dir = settings.backtests_dir / "runs"
    rows: list[dict[str, Any]] = []

    summary_files = sorted(runs_dir.glob("*/summary.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    for summary_path in summary_files:
        summary = read_json(summary_path)
        if not summary:
            continue
        summary = _annotate_backtest_trust(summary)
        profile_name = str(summary.get("profile_name") or "").strip() or None
        rows.append(
            {
                "run_id": summary.get("run_id") or summary_path.parent.name,
                "profile_name": profile_name,
                "profile_label": summary.get("profile_label") or (label_by_name.get(profile_name) if profile_name else None),
                "generated_at": summary.get("generated_at"),
                "portfolio_total_return": summary.get("portfolio_total_return"),
                "portfolio_cagr": summary.get("portfolio_cagr"),
                "portfolio_max_drawdown": summary.get("portfolio_max_drawdown"),
                "portfolio_win_rate": summary.get("portfolio_win_rate"),
                "method_version": summary.get("method_version"),
                "is_trustworthy": summary.get("is_trustworthy"),
                "num_rebalances": summary.get("num_rebalances"),
                "backtest_start": summary.get("backtest_start"),
                "backtest_end": summary.get("backtest_end"),
                "summary_path": str(summary_path),
            }
        )

    if rows:
        return rows

    latest_summary = read_json(settings.backtests_dir / "summary.json")
    if latest_summary:
        latest_summary = _enrich_backtest_profile(latest_summary, profiles)
        latest_summary = _annotate_backtest_trust(latest_summary)
        profile_name = str(latest_summary.get("profile_name") or "").strip() or None
        return [
            {
                "run_id": latest_summary.get("run_id") or "latest",
                "profile_name": profile_name,
                "profile_label": latest_summary.get("profile_label") or (label_by_name.get(profile_name) if profile_name else None),
                "generated_at": latest_summary.get("generated_at"),
                "portfolio_total_return": latest_summary.get("portfolio_total_return"),
                "portfolio_cagr": latest_summary.get("portfolio_cagr"),
                "portfolio_max_drawdown": latest_summary.get("portfolio_max_drawdown"),
                "portfolio_win_rate": latest_summary.get("portfolio_win_rate"),
                "method_version": latest_summary.get("method_version"),
                "is_trustworthy": latest_summary.get("is_trustworthy"),
                "num_rebalances": latest_summary.get("num_rebalances"),
                "backtest_start": latest_summary.get("backtest_start"),
                "backtest_end": latest_summary.get("backtest_end"),
                "summary_path": str(settings.backtests_dir / "summary.json"),
            }
        ]
    return []


def get_model_overview(profile_name: str | None = None) -> dict[str, Any]:
    settings = get_settings()
    production_metadata = read_json(settings.models_dir / "training_metadata.json")
    profile_catalog = get_model_profile_catalog()
    active_profile = _profile_name(profile_catalog.get("active_profile")) or profile_catalog["default_profile"]
    production_training_profile = _profile_name(production_metadata.get("profile_name")) or active_profile
    profile_names = {profile["name"] for profile in profile_catalog["profiles"]}
    selected_profile = _profile_name(profile_name)
    if selected_profile not in profile_names:
        selected_profile = active_profile
    selected_profile_label = _profile_label(selected_profile, profile_catalog["profiles"])
    profile_model_dir = _profile_model_dir(selected_profile)
    profile_training_metadata_path = profile_model_dir / "training_metadata.json" if profile_model_dir is not None else None
    profile_feature_importance_path = profile_model_dir / "feature_importance.csv" if profile_model_dir is not None else None
    profile_metadata = read_json(profile_training_metadata_path) if profile_training_metadata_path is not None else {}
    if not profile_metadata and selected_profile == production_training_profile:
        profile_metadata = production_metadata
        profile_training_metadata_path = settings.models_dir / "training_metadata.json"
        profile_feature_importance_path = settings.models_dir / "feature_importance.csv"
    selected_training = profile_metadata
    backtest, backtest_summary_path = _backtest_summary_entry_for_profile(selected_profile, profile_catalog["profiles"])
    equity_curve, equity_curve_path = _backtest_equity_curve(backtest_summary_path)
    selected_feature_importance_path = profile_feature_importance_path if profile_feature_importance_path and profile_feature_importance_path.exists() else None
    importance_df = _safe_read_csv(selected_feature_importance_path) if selected_feature_importance_path is not None else pd.DataFrame()
    backtest_runs = _backtest_run_rows()

    top_features: list[dict[str, Any]] = []
    if not importance_df.empty:
        columns = [col for col in ["feature", "importance_gain", "importance_split"] if col in importance_df.columns]
        top_features = records_to_json(
            importance_df[columns]
            .sort_values("importance_gain", ascending=False)
            .head(20)
            .to_dict(orient="records")
        )

    return {
        "current_profile": selected_profile,
        "current_profile_label": selected_profile_label,
        "active_profile": active_profile,
        "active_profile_label": _profile_label(active_profile, profile_catalog["profiles"]),
        "training_profile": production_training_profile,
        "training_metadata": selected_training,
        "backtest_summary": backtest,
        "backtest_equity_curve": equity_curve,
        "artifact_status": {
            "training_metadata": _artifact_status(profile_training_metadata_path if selected_training else None),
            "feature_importance": _artifact_status(selected_feature_importance_path),
            "backtest_summary": _artifact_status(backtest_summary_path),
            "backtest_equity_curve": _artifact_status(equity_curve_path),
        },
        "backtest_runs": backtest_runs,
        "model_profiles": profile_catalog["profiles"],
        "default_profile": profile_catalog["default_profile"],
        "active_profile_artifact_status": _artifact_status(settings.models_dir / "inference_scores_latest.parquet"),
        "top_features": top_features,
    }


def _scores_path_for_profile(profile_name: str | None) -> tuple[str | None, Path]:
    settings = get_settings()
    catalog = get_model_profile_catalog()
    profile_names = {profile["name"] for profile in catalog["profiles"]}
    selected_profile = _profile_name(profile_name)
    active_profile = _profile_name(catalog.get("active_profile")) or catalog["default_profile"]
    if selected_profile in profile_names:
        profile_dir = _profile_model_dir(selected_profile)
        profile_scores_path = profile_dir / "inference_scores_latest.parquet" if profile_dir is not None else None
        if profile_scores_path is not None and profile_scores_path.exists():
            return selected_profile, profile_scores_path
        if selected_profile == active_profile:
            return selected_profile, settings.models_dir / "inference_scores_latest.parquet"
        if profile_scores_path is not None:
            return selected_profile, profile_scores_path
    return active_profile, settings.models_dir / "inference_scores_latest.parquet"


def get_latest_picks(*, limit: int = 25, profile_name: str | None = None) -> dict[str, Any]:
    settings = get_settings()
    selected_profile, scores_path = _scores_path_for_profile(profile_name)
    features_path = settings.quant_dir / "inference_features_latest.parquet"
    scores_df = _safe_read_parquet(scores_path)
    feature_time = _file_updated_at(features_path)
    model_time = _file_updated_at(scores_path)
    source_close_date = _parquet_date_max(features_path, column="date")
    raw_sync_date = _parquet_date_max(settings.stock_list_path, column="trade_date") or _parquet_date_max(
        settings.stock_registry_path,
        column="trade_date",
    )
    if scores_df.empty:
        return {
            "rows": 0,
            "latest_date": None,
            "source_close_date": source_close_date,
            "raw_sync_date": raw_sync_date,
            "feature_time": feature_time,
            "data_src_time": feature_time,
            "model_time": model_time,
            "profile_name": selected_profile,
            "picks": [],
        }

    scores_df = filter_model_candidate_rows(scores_df)
    if scores_df.empty:
        return {
            "rows": 0,
            "latest_date": None,
            "source_close_date": source_close_date,
            "raw_sync_date": raw_sync_date,
            "feature_time": feature_time,
            "data_src_time": feature_time,
            "model_time": model_time,
            "profile_name": selected_profile,
            "picks": [],
        }

    latest_signal_date = None
    snapshot_df = scores_df.copy()
    if "date" in scores_df.columns:
        scores_df["date"] = pd.to_datetime(scores_df["date"], errors="coerce")
        latest_signal = scores_df["date"].max()
        if not pd.isna(latest_signal):
            latest_signal_date = pd.Timestamp(latest_signal).date().isoformat()
            snapshot_df = scores_df.loc[scores_df["date"].eq(latest_signal)].copy()

    top_df = snapshot_df.sort_values("score", ascending=False).head(limit).copy()
    if "date" in top_df.columns:
        top_df.insert(0, "signal_date", top_df["date"].dt.strftime("%Y-%m-%d"))
    top_df.insert(0, "rank", range(1, len(top_df) + 1))
    top_df["feature_time"] = feature_time
    top_df["data_src_time"] = feature_time
    top_df["model_time"] = model_time
    ordered_columns = [
        col
        for col in [
            "rank",
            "signal_date",
            "feature_time",
            "model_time",
            "code",
            "name",
            "industry",
            "score",
            "close",
            "bias_20",
            "pe_ttm",
            "pb",
        ]
        if col in top_df.columns
    ]
    return {
        "rows": int(len(scores_df)),
        "latest_date": latest_signal_date,
        "source_close_date": source_close_date or latest_signal_date,
        "raw_sync_date": raw_sync_date,
        "feature_time": feature_time,
        "data_src_time": feature_time,
        "model_time": model_time,
        "profile_name": selected_profile,
        "picks": records_to_json(top_df[ordered_columns].to_dict(orient="records")),
    }


def get_lobster_picks(*, limit: int = 100) -> dict[str, Any]:
    settings = get_settings()
    cache_key = _lobster_cache_key(settings)
    if _LOBSTER_PICK_CACHE.get("key") == cache_key and isinstance(_LOBSTER_PICK_CACHE.get("payload"), dict):
        return _slice_lobster_payload(_LOBSTER_PICK_CACHE["payload"], limit)

    stock_df = _safe_read_parquet(settings.stock_list_path)
    if stock_df.empty or "code" not in stock_df.columns:
        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "trade_date": None,
            "source": "quant_data",
            "universe": 0,
            "scanned": 0,
            "qualified": 0,
            "returned": 0,
            "limit": limit,
            "rules": {
                "volume": "last_3_days_strictly_increasing",
                "turnover": "each_last_3_days_lte_10_pct",
                "three_day_gain": "gt_0_lte_10_pct",
                "score": "latest_amount / latest_float_market_cap * 100",
                "sort": "score_desc_then_amount_desc",
            },
            "picks": [],
        }

    stock_df = stock_df.copy()
    stock_df["code"] = stock_df["code"].astype(str).str.zfill(6)
    stock_df = stock_df[stock_df["code"].map(_is_lobster_allowed_code)].copy()
    if "is_active" in stock_df.columns:
        stock_df = stock_df[stock_df["is_active"].fillna(True).astype(bool)].copy()
    if "exchange" not in stock_df.columns:
        stock_df["exchange"] = ""
    if "name" not in stock_df.columns:
        stock_df["name"] = stock_df["code"]
    if "industry" not in stock_df.columns:
        stock_df["industry"] = ""

    target_trade_date = _parquet_date_max(settings.stock_list_path, column="trade_date")
    if target_trade_date is None:
        target_trade_date = _parquet_date_max(settings.stock_registry_path, column="trade_date")

    metadata_by_code = {
        str(row.code).zfill(6): row
        for row in stock_df[["code", "exchange", "name", "industry"]].itertuples(index=False)
    }

    rows: list[dict[str, Any]] = []
    scanned = 0
    kline_dir = settings.quant_dir / "daily_kline"
    valuation_dir = settings.quant_dir / "daily_valuation"

    for code, stock in metadata_by_code.items():
        kline_path = kline_dir / f"{code}.parquet"
        valuation_path = valuation_dir / f"{code}.parquet"
        if not kline_path.exists() or not valuation_path.exists():
            continue

        kline_df = _safe_read_parquet(kline_path, columns=LOBSTER_PICK_KLINE_COLUMNS)
        if kline_df.empty or len(kline_df) < 3:
            continue

        kline_df = kline_df.copy()
        kline_df["date"] = pd.to_datetime(kline_df["date"], errors="coerce")
        kline_df = kline_df.dropna(subset=["date"]).sort_values("date")
        if target_trade_date is not None:
            kline_df = kline_df[kline_df["date"] <= pd.Timestamp(target_trade_date)]
        latest_three = kline_df.tail(3).copy()
        if len(latest_three) < 3:
            continue

        latest_date = _date_string(latest_three["date"].iloc[-1])
        if target_trade_date is not None and latest_date != target_trade_date:
            continue

        scanned += 1
        closes = pd.to_numeric(latest_three["close"], errors="coerce").to_numpy(dtype=float)
        volumes = pd.to_numeric(latest_three["volume"], errors="coerce").to_numpy(dtype=float)
        turnovers = pd.to_numeric(latest_three["turnover"], errors="coerce").to_numpy(dtype=float)
        amount = _safe_float(latest_three["amount"].iloc[-1])
        if (
            len(closes) != 3
            or len(volumes) != 3
            or len(turnovers) != 3
            or not np.isfinite(closes).all()
            or not np.isfinite(volumes).all()
            or not np.isfinite(turnovers).all()
            or amount is None
        ):
            continue

        volume_up = volumes[0] < volumes[1] < volumes[2]
        turnover_ok = bool((turnovers <= 10).all())
        if closes[0] <= 0:
            continue
        three_day_gain_pct = (closes[2] / closes[0] - 1) * 100
        early_gain = 0 < three_day_gain_pct <= 10
        if not (volume_up and turnover_ok and early_gain):
            continue

        valuation_df = _safe_read_parquet(valuation_path, columns=LOBSTER_PICK_VALUATION_COLUMNS)
        if valuation_df.empty:
            continue
        valuation_df = valuation_df.copy()
        valuation_df["date"] = pd.to_datetime(valuation_df["date"], errors="coerce")
        valuation_df = valuation_df.dropna(subset=["date"]).sort_values("date")
        if latest_date is not None:
            valuation_df = valuation_df[valuation_df["date"] <= pd.Timestamp(latest_date)]
        if valuation_df.empty:
            continue
        float_market_cap = _safe_float(valuation_df["float_market_cap"].iloc[-1])
        if float_market_cap is None or float_market_cap <= 0:
            continue

        score = amount / float_market_cap * 100
        date_values = [_date_string(value) for value in latest_three["date"].tolist()]
        turnover_values = [round(float(value), 4) for value in turnovers.tolist()]
        volume_values = [float(value) for value in volumes.tolist()]
        close_values = [round(float(value), 4) for value in closes.tolist()]
        amount_yi = amount / 100_000_000
        float_market_cap_yi = float_market_cap / 100_000_000
        rows.append(
            {
                "signal_date": latest_date,
                "code": code,
                "exchange": str(getattr(stock, "exchange", "") or "").lower(),
                "board": _code_board(code),
                "name": str(getattr(stock, "name", "") or code),
                "industry": str(getattr(stock, "industry", "") or ""),
                "price": round(float(closes[-1]), 3),
                "score": round(float(score), 4),
                "amount": float(amount),
                "amount_yi": round(float(amount_yi), 4),
                "float_market_cap": float(float_market_cap),
                "float_market_cap_yi": round(float(float_market_cap_yi), 4),
                "current_turnover": round(float(turnovers[-1]), 4),
                "three_day_gain_pct": round(float(three_day_gain_pct), 4),
                "three_day_dates": date_values,
                "three_day_volumes": volume_values,
                "three_day_turnovers": turnover_values,
                "three_day_closes": close_values,
                "volume_path": " -> ".join(f"{value:,.0f}" for value in volume_values),
                "turnover_path": " -> ".join(f"{value:.2f}%" for value in turnover_values),
                "close_path": " -> ".join(f"{value:.2f}" for value in close_values),
            }
        )

    rows = sorted(rows, key=lambda row: (row["score"], row["amount"]), reverse=True)
    for index, row in enumerate(rows, start=1):
        row["rank"] = index

    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "trade_date": target_trade_date,
        "source": "quant_data/daily_kline + quant_data/daily_valuation",
        "universe": int(len(stock_df)),
        "scanned": int(scanned),
        "qualified": int(len(rows)),
        "returned": int(len(rows)),
        "limit": int(len(rows)),
        "rules": {
            "volume": "last_3_days_strictly_increasing",
            "turnover": "each_last_3_days_lte_10_pct",
            "three_day_gain": "gt_0_lte_10_pct",
            "score": "latest_amount / latest_float_market_cap * 100",
            "sort": "score_desc_then_amount_desc",
        },
        "picks": records_to_json(rows),
    }
    _LOBSTER_PICK_CACHE.clear()
    _LOBSTER_PICK_CACHE.update({"key": cache_key, "payload": payload})
    return _slice_lobster_payload(payload, limit)


def activate_model_for_paper(profile_name: str) -> dict[str, Any]:
    profile = set_active_model_profile(profile_name)
    sync_result = _sync_profile_to_production(str(profile["name"]))
    return {
        "ok": True,
        "profile_name": profile["name"],
        "profile_label": profile["label"],
        "synced_to": str(_production_model_dir()),
        **sync_result,
    }
