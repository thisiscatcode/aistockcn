from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from app.config import get_settings


def _ensure_project_root_importable() -> None:
    root = getattr(get_settings(), "project_root", Path(__file__).resolve().parents[4])
    root_text = str(root)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)


def _shared_settings_module():
    _ensure_project_root_importable()
    import control_settings

    return control_settings


def get_admin_settings() -> dict[str, Any]:
    settings = get_settings()
    shared = _shared_settings_module()
    payload = shared.read_control_settings(settings.quant_dir)
    return {
        "settings": payload,
        "path": str(settings.control_settings_path),
    }


def update_admin_settings(*, exclude_st_from_model_candidates: bool) -> dict[str, Any]:
    settings = get_settings()
    shared = _shared_settings_module()
    payload = shared.write_control_settings(
        settings.quant_dir,
        {"exclude_st_from_model_candidates": exclude_st_from_model_candidates},
    )
    return {
        "code": "admin_settings_updated",
        "settings": payload,
        "path": str(settings.control_settings_path),
    }


def exclude_st_setting_enabled() -> bool:
    return bool(get_admin_settings()["settings"].get("exclude_st_from_model_candidates", True))


def filter_model_candidate_rows(rows, *, name_column: str = "name"):
    shared = _shared_settings_module()
    return shared.filter_model_candidate_rows(
        rows,
        exclude_st=exclude_st_setting_enabled(),
        name_column=name_column,
    )
