"""Daily predictions from a deployed model, outside its immutable training artifacts."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import numpy as np
import pandas as pd

from control_settings import exclude_st_from_model_candidates, filter_model_candidate_rows


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_json(path: Path, payload: dict) -> None:
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _runtime_dir(quant_dir: Path, artifact_dir: Path, market: str) -> Path:
    return quant_dir / "model_inference" / market.upper() / artifact_dir.name


def _require_current_inputs(quant_dir: Path, signal_date: str) -> None:
    benchmark = quant_dir / "daily_kline" / "000001.parquet"
    if benchmark.exists():
        dates = pd.read_parquet(benchmark, columns=["date"])["date"]
        latest = pd.to_datetime(dates, errors="coerce").max()
        if pd.notna(latest) and pd.Timestamp(signal_date) < latest.normalize():
            raise RuntimeError(
                f"inference features are stale ({signal_date}); latest downloaded market date is {latest.date()}"
            )


def published_scores(quant_dir: Path, artifact_dir: Path, market: str = "CN") -> Path | None:
    """Read a fully published prediction snapshot tied to this exact model."""
    root = _runtime_dir(quant_dir, artifact_dir, market)
    pointer = root / "latest.json"
    if not pointer.exists():
        return None
    payload = json.loads(pointer.read_text())
    snapshot = (root / payload["snapshot"]).resolve()
    if snapshot.parent != root.resolve():
        raise RuntimeError("prediction snapshot escapes its model directory")
    if payload["model_sha256"] != file_digest(artifact_dir / "lightgbm_model.txt"):
        raise RuntimeError("prediction snapshot belongs to a different model")
    if payload["metadata_sha256"] != file_digest(artifact_dir / "training_metadata.json"):
        raise RuntimeError("prediction snapshot training metadata mismatch")
    scores = snapshot / "inference_scores_latest.parquet"
    if payload["scores_sha256"] != file_digest(scores):
        raise RuntimeError("prediction snapshot checksum mismatch")
    return scores


def _feature_frame(frame: pd.DataFrame, metadata: dict, mappings: dict) -> pd.DataFrame:
    columns = metadata["feature_cols"]
    missing = set(columns) - set(frame.columns)
    if missing:
        raise RuntimeError(f"inference features are missing columns: {sorted(missing)}")
    categorical = set(metadata.get("categorical_cols", []))
    data = {}
    for column in columns:
        if column in categorical:
            values = frame[column].fillna("UNKNOWN").astype("string")
            data[column] = pd.Categorical(values, categories=mappings[column]).codes.astype(np.int32)
        else:
            data[column] = frame[column].to_numpy(dtype=np.float32, na_value=np.nan)
    return pd.DataFrame(data)


def _predict(booster, frame: pd.DataFrame, metadata: dict, mappings: dict) -> pd.DataFrame:
    scored = frame.copy()
    prediction = booster.predict(_feature_frame(frame, metadata, mappings), num_threads=2)
    if metadata.get("model_objective") == "regression":
        scored["raw_score"] = np.asarray(prediction, dtype=np.float32)
        scored["score"] = scored.groupby("date")["raw_score"].rank(method="average", pct=True).astype("float32")
    else:
        scored["score"] = prediction
    if not np.isfinite(scored["score"]).all():
        raise RuntimeError("model produced non-finite predictions")
    return scored.sort_values("score", ascending=False).reset_index(drop=True)


def _category_mappings(quant_dir: Path, artifact_dir: Path, metadata: dict, booster) -> dict:
    if "category_mappings" in metadata:
        return metadata["category_mappings"]
    columns = metadata.get("categorical_cols", [])
    if not columns:
        return {}
    cache = _runtime_dir(quant_dir, artifact_dir, "CN") / "category_encoding.json"
    identity = file_digest(artifact_dir / "lightgbm_model.txt")
    if cache.exists():
        recovered = json.loads(cache.read_text())
        if recovered.get("model_sha256") == identity:
            return recovered["category_mappings"]
    # Older models encoded categories numerically without saving the vocabulary.
    # Recover it only when the original training window is still available, then
    # require it to reproduce every archived prediction before using it live.
    train_path = quant_dir / "model_profiles" / metadata["profile_name"] / "ml_features_ready.parquet"
    training = pd.read_parquet(train_path, columns=["date", "name", *columns])
    start = pd.Timestamp(metadata.get("production_train_date_min") or metadata["train_date_min"])
    end = pd.Timestamp(metadata.get("production_train_date_max") or metadata["valid_date_max"])
    dates = pd.to_datetime(training["date"])
    training = training.loc[dates.between(start, end)]
    if metadata.get("exclude_st_from_model_candidates", True):
        training = filter_model_candidate_rows(training, exclude_st=True)
    if training.empty or pd.to_datetime(training["date"]).min() > start or pd.to_datetime(training["date"]).max() < end:
        raise RuntimeError("cannot recover original categorical encoding: training window is unavailable")
    archived = pd.read_parquet(artifact_dir / "inference_scores_latest.parquet")
    mappings = {}
    for column in columns:
        seen = {"UNKNOWN"}
        for frame in (training, archived):
            seen.update(str(value) for value in frame[column].dropna().unique() if str(value))
        mappings[column] = ["UNKNOWN", *sorted(seen - {"UNKNOWN"})]
    del training
    reproduced = _predict(booster, archived, metadata, mappings).set_index("code")["score"]
    original = archived.set_index("code")["score"].reindex(reproduced.index)
    if not np.allclose(reproduced, original, rtol=1e-6, atol=1e-7):
        raise RuntimeError("recovered categorical encoding does not reproduce archived predictions")
    _atomic_json(cache, {"model_sha256": identity, "category_mappings": mappings})
    return mappings


def refresh_predictions(quant_dir: Path, artifact_dir: Path, market: str = "CN") -> Path:
    """Score changed inputs once, publishing the complete result atomically."""
    import lightgbm as lgb

    root = _runtime_dir(quant_dir, artifact_dir, market)
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        inputs = quant_dir / "inference_features_latest.parquet"
        signature = file_digest(inputs)
        model_digest = file_digest(artifact_dir / "lightgbm_model.txt")
        metadata_digest = file_digest(artifact_dir / "training_metadata.json")
        exclude_st = exclude_st_from_model_candidates(quant_dir)
        pointer = root / "latest.json"
        previous = json.loads(pointer.read_text()) if pointer.exists() else {}
        if (previous.get("features_sha256") == signature and previous.get("model_sha256") == model_digest
                and previous.get("metadata_sha256") == metadata_digest
                and previous.get("exclude_st") == exclude_st):
            _require_current_inputs(quant_dir, previous["score_date"])
            published = published_scores(quant_dir, artifact_dir, market)
            if published is not None:
                return published
        metadata = json.loads((artifact_dir / "training_metadata.json").read_text())
        frame = pd.read_parquet(inputs)
        if file_digest(inputs) != signature:
            raise RuntimeError("inference features changed while being read; retry next cycle")
        frame["date"] = pd.to_datetime(frame["date"], errors="raise")
        latest_date = frame["date"].max()
        if pd.isna(latest_date) or frame.empty:
            raise RuntimeError("inference features contain no valid dates")
        if latest_date < pd.Timestamp(metadata["score_date"]):
            raise RuntimeError("inference features predate the deployed model's original predictions")
        _require_current_inputs(quant_dir, latest_date.date().isoformat())
        frame = frame.loc[frame["date"] == latest_date].copy()
        if exclude_st:
            frame = filter_model_candidate_rows(frame, exclude_st=True)
        if frame.empty:
            raise RuntimeError("no investable inference rows remain")
        booster = lgb.Booster(model_file=str(artifact_dir / "lightgbm_model.txt"))
        if booster.feature_name() != metadata["feature_cols"]:
            raise RuntimeError("model features do not match training metadata")
        mappings = _category_mappings(quant_dir, artifact_dir, metadata, booster)
        scored = _predict(booster, frame, metadata, mappings)
        snapshot_name = f"{latest_date.date().isoformat()}-{uuid4().hex}"
        temporary = root / f".{snapshot_name}.tmp"
        destination = root / snapshot_name
        temporary.mkdir()
        try:
            scores = temporary / "inference_scores_latest.parquet"
            scored.to_parquet(scores, index=False)
            (temporary / "training_metadata.json").write_text(json.dumps({**metadata, "category_mappings": mappings}))
            provenance = {
                "snapshot": snapshot_name,
                "model_version": artifact_dir.name,
                "model_sha256": model_digest,
                "metadata_sha256": metadata_digest,
                "features_sha256": signature,
                "scores_sha256": file_digest(scores),
                "exclude_st": exclude_st,
                "score_date": latest_date.date().isoformat(),
                "rows": len(scored),
                "generated_at": datetime.now(UTC).isoformat(),
            }
            (temporary / "provenance.json").write_text(json.dumps(provenance, indent=2))
            os.rename(temporary, destination)
            _atomic_json(pointer, provenance)
        finally:
            shutil.rmtree(temporary, ignore_errors=True)
        return destination / "inference_scores_latest.parquet"
