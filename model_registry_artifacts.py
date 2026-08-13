"""Create immutable, self-describing model artifact snapshots after training."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


REQUIRED_ARTIFACTS = ("training_metadata.json", "inference_scores_latest.parquet")
OPTIONAL_ARTIFACTS = ("lightgbm_model.txt", "feature_importance.csv")


def _file_digest(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return {"sha256": digest.hexdigest(), "size": path.stat().st_size}


def _manifest(path: Path) -> dict[str, dict[str, Any]]:
    result = {
        name: _file_digest(path / name)
        for name in (*REQUIRED_ARTIFACTS, *OPTIONAL_ARTIFACTS)
        if (path / name).is_file()
    }
    missing = [name for name in REQUIRED_ARTIFACTS if name not in result]
    if missing:
        raise RuntimeError(f"model artifacts are missing: {', '.join(missing)}")
    return result


def create_model_registry_snapshot(*, data_dir: Path, profile: str, market: str = "CN") -> dict[str, Any]:
    source = data_dir / "model_profiles" / profile / "models"
    source_manifest = _manifest(source)
    trained_at = datetime.now(UTC)
    digest = hashlib.sha256(
        json.dumps(source_manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    model_version = f"{market.lower()}-{profile}-{trained_at.strftime('%Y%m%dT%H%M%SZ')}-{digest[:8]}"
    registry_root = data_dir / "model_registry" / market.upper()
    destination = registry_root / model_version
    temporary = registry_root / f".{model_version}.{uuid4().hex}.tmp"
    registry_root.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise RuntimeError(f"immutable model version already exists: {destination}")
    temporary.mkdir()
    try:
        for name in source_manifest:
            shutil.copy2(source / name, temporary / name)
        record = {
            "market": market.upper(),
            "model_version": model_version,
            "profile": profile,
            "trained_at": trained_at.isoformat(),
            "validation_status": "pending",
            "artifact_manifest": _manifest(temporary),
        }
        record_path = temporary / "registry_record.json"
        record_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.rename(temporary, destination)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return {**record, "artifact_path": str(destination)}
