from __future__ import annotations

from typing import Any

from app.config import get_settings
from app.services.files import read_json, write_json_atomic

DEFAULT_PROFILE_NAME = "short_5d"
DEFAULT_PROFILES: list[dict[str, Any]] = [
    {
        "name": "short_1d",
        "label": "1D Short",
        "label_horizon": 1,
        "label_threshold": 0.01,
        "valid_days": 60,
        "score_threshold": 0.5,
        "score_top_k": 20,
        "backtest_min_train_days": 252,
        "backtest_retrain_every": 10,
        "backtest_rebalance_every": 1,
        "backtest_top_k": 5,
    },
    {
        "name": "short_2d",
        "label": "2D Short",
        "label_horizon": 2,
        "label_threshold": 0.0125,
        "valid_days": 60,
        "score_threshold": 0.5,
        "score_top_k": 20,
        "backtest_min_train_days": 252,
        "backtest_retrain_every": 13,
        "backtest_rebalance_every": 2,
        "backtest_top_k": 5,
    },
    {
        "name": "short_3d",
        "label": "3D Short",
        "label_horizon": 3,
        "label_threshold": 0.015,
        "valid_days": 60,
        "score_threshold": 0.5,
        "score_top_k": 20,
        "backtest_min_train_days": 252,
        "backtest_retrain_every": 15,
        "backtest_rebalance_every": 3,
        "backtest_top_k": 5,
    },
    {
        "name": "short_4d",
        "label": "4D Short",
        "label_horizon": 4,
        "label_threshold": 0.0175,
        "valid_days": 60,
        "score_threshold": 0.5,
        "score_top_k": 20,
        "backtest_min_train_days": 252,
        "backtest_retrain_every": 18,
        "backtest_rebalance_every": 4,
        "backtest_top_k": 5,
    },
    {
        "name": "short_5d",
        "label": "5D Short",
        "label_horizon": 5,
        "label_threshold": 0.02,
        "valid_days": 60,
        "score_threshold": 0.5,
        "score_top_k": 20,
        "backtest_min_train_days": 252,
        "backtest_retrain_every": 20,
        "backtest_rebalance_every": 5,
        "backtest_top_k": 5,
    },
    {
        "name": "medium_10d_v2",
        "label": "10D A-Share V2",
        "label_horizon": 10,
        "label_threshold": 0.0,
        "return_mode": "next_open_to_close",
        "model_objective": "regression",
        "cross_sectional_target": True,
        "valid_days": 120,
        "score_threshold": 0.8,
        "score_top_k": 50,
        "backtest_min_train_days": 504,
        "backtest_retrain_every": 4,
        "backtest_rebalance_every": 5,
        "backtest_top_k": 20,
        "backtest_max_drop": 4,
        "backtest_budget_total": 1_000_000.0,
        "deployment_status": "available",
    },
]


def _catalog_path():
    return get_settings().run_dir / "model_profiles.json"


def _normalize_profile(raw: dict[str, Any]) -> dict[str, Any] | None:
    name = str(raw.get("name") or "").strip()
    if not name:
        return None
    label = str(raw.get("label") or name).strip() or name
    model_objective = str(raw.get("model_objective") or "binary").strip().lower()
    if model_objective not in {"binary", "regression"}:
        model_objective = "binary"
    return_mode = str(raw.get("return_mode") or "close_to_close").strip().lower()
    if return_mode not in {"close_to_close", "next_open_to_close"}:
        return_mode = "close_to_close"
    return {
        "name": name,
        "label": label,
        "label_horizon": max(int(raw.get("label_horizon") or 5), 1),
        "label_threshold": float(raw["label_threshold"]) if raw.get("label_threshold") is not None else 0.02,
        "return_mode": return_mode,
        "model_objective": model_objective,
        "cross_sectional_target": bool(raw.get("cross_sectional_target", False)),
        "valid_days": max(int(raw.get("valid_days") or 60), 1),
        "score_threshold": float(raw.get("score_threshold") or 0.5),
        "score_top_k": max(int(raw.get("score_top_k") or 20), 1),
        "backtest_min_train_days": max(int(raw.get("backtest_min_train_days") or 252), 1),
        "backtest_retrain_every": max(int(raw.get("backtest_retrain_every") or 20), 1),
        "backtest_rebalance_every": max(int(raw.get("backtest_rebalance_every") or 5), 1),
        "backtest_top_k": max(int(raw.get("backtest_top_k") or 5), 1),
        "backtest_max_drop": max(int(raw.get("backtest_max_drop") or 0), 0),
        "backtest_budget_total": max(float(raw.get("backtest_budget_total") or 50_000.0), 1.0),
        "deployment_status": str(raw.get("deployment_status") or "available").strip() or "available",
    }


def get_model_profile_catalog() -> dict[str, Any]:
    raw_catalog = read_json(_catalog_path())
    raw_profiles = raw_catalog.get("profiles")
    normalized_profiles: list[dict[str, Any]] = []
    seen_names: set[str] = set()

    if isinstance(raw_profiles, list):
        for item in raw_profiles:
            if not isinstance(item, dict):
                continue
            profile = _normalize_profile(item)
            if profile is None or profile["name"] in seen_names:
                continue
            normalized_profiles.append(profile)
            seen_names.add(profile["name"])

    if not normalized_profiles:
        normalized_profiles = [profile.copy() for profile in DEFAULT_PROFILES]

    default_profile = str(raw_catalog.get("default_profile") or DEFAULT_PROFILE_NAME).strip() or DEFAULT_PROFILE_NAME
    if default_profile not in {profile["name"] for profile in normalized_profiles}:
        default_profile = normalized_profiles[0]["name"]
    active_profile = str(raw_catalog.get("active_profile") or default_profile).strip() or default_profile
    if active_profile not in {profile["name"] for profile in normalized_profiles}:
        active_profile = default_profile

    return {
        "default_profile": default_profile,
        "active_profile": active_profile,
        "profiles": normalized_profiles,
        "path": str(_catalog_path()),
    }


def get_model_profiles() -> list[dict[str, Any]]:
    return list(get_model_profile_catalog()["profiles"])


def resolve_model_profile(profile_name: str | None = None) -> dict[str, Any]:
    catalog = get_model_profile_catalog()
    profiles = catalog["profiles"]
    selected = (profile_name or "").strip()
    if selected:
        for profile in profiles:
            if profile["name"] == selected:
                return profile
    default_name = catalog["default_profile"]
    for profile in profiles:
        if profile["name"] == default_name:
            return profile
    return profiles[0]


def get_active_model_profile() -> dict[str, Any]:
    catalog = get_model_profile_catalog()
    return resolve_model_profile(str(catalog.get("active_profile") or catalog.get("default_profile") or ""))


def set_active_model_profile(profile_name: str) -> dict[str, Any]:
    profile = resolve_model_profile(profile_name)
    path = _catalog_path()
    raw_catalog = read_json(path)
    catalog = get_model_profile_catalog()
    payload = {
        "default_profile": raw_catalog.get("default_profile") or catalog["default_profile"],
        "active_profile": profile["name"],
        "profiles": raw_catalog.get("profiles") if isinstance(raw_catalog.get("profiles"), list) else catalog["profiles"],
    }
    write_json_atomic(path, payload, ensure_ascii=False)
    return profile
