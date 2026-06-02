"""Shared runtime control settings and stock-name filters."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


CONTROL_SETTINGS_FILENAME = "control_settings.json"
DEFAULT_CONTROL_SETTINGS: dict[str, Any] = {
    "exclude_st_from_model_candidates": True,
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def control_settings_path(quant_dir: Path | str = "quant_data") -> Path:
    return Path(quant_dir) / CONTROL_SETTINGS_FILENAME


def read_control_settings(quant_dir: Path | str = "quant_data") -> dict[str, Any]:
    path = control_settings_path(quant_dir)
    settings = dict(DEFAULT_CONTROL_SETTINGS)
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                settings.update(payload)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            pass
    settings["exclude_st_from_model_candidates"] = bool(settings.get("exclude_st_from_model_candidates", True))
    settings.setdefault("updated_at", None)
    return settings


def write_control_settings(quant_dir: Path | str, updates: dict[str, Any]) -> dict[str, Any]:
    settings = read_control_settings(quant_dir)
    if "exclude_st_from_model_candidates" in updates:
        settings["exclude_st_from_model_candidates"] = bool(updates["exclude_st_from_model_candidates"])
    settings["updated_at"] = now_iso()
    path = control_settings_path(quant_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return settings


def exclude_st_from_model_candidates(quant_dir: Path | str = "quant_data") -> bool:
    return bool(read_control_settings(quant_dir).get("exclude_st_from_model_candidates", True))


def _normalized_stock_name(name: object) -> str:
    return str(name or "").strip().upper().replace(" ", "")


def is_st_stock_name(name: object) -> bool:
    normalized = _normalized_stock_name(name)
    return normalized.startswith(("*ST", "ST", "SST", "S*ST"))


def is_delisting_stock_name(name: object) -> bool:
    normalized = _normalized_stock_name(name)
    return normalized.startswith("退市") or normalized.endswith("退")


def is_investable_stock_name(name: object, *, exclude_st: bool = True) -> bool:
    normalized = str(name or "").strip()
    if not normalized:
        return True
    if is_delisting_stock_name(normalized):
        return False
    if exclude_st and is_st_stock_name(normalized):
        return False
    return True


def filter_model_candidate_rows(
    rows: pd.DataFrame,
    *,
    exclude_st: bool,
    name_column: str = "name",
) -> pd.DataFrame:
    if rows.empty or name_column not in rows.columns:
        return rows.copy()
    return rows[rows[name_column].map(lambda value: is_investable_stock_name(value, exclude_st=exclude_st))].copy()
