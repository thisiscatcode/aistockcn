from __future__ import annotations

from pathlib import Path
from typing import Any

from app.config import Settings, get_settings


def latest_registry_scores_path(settings: Settings | Any | None = None, *, market: str = "CN") -> Path:
    """Return the newest immutable score artifact, with a legacy fallback."""
    resolved = settings or get_settings()
    registry_root = resolved.quant_dir / "model_registry" / market.upper()
    candidates = list(registry_root.glob("*/inference_scores_latest.parquet"))
    if candidates:
        return max(candidates, key=lambda path: (path.stat().st_mtime_ns, str(path)))
    return resolved.models_dir / "inference_scores_latest.parquet"
