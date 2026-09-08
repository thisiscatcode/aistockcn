from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from app.config import Settings, get_settings
from app.services.files import read_json
from app.services.model_profiles import resolve_model_profile
from app.services.model_registry import (
    activate_model,
    get_active_deployment,
    get_latest_model_for_profile,
    sync_model_registry,
    update_validation_status,
    verify_artifact_manifest,
    verify_immutable_artifact_location,
)


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if pd.notna(result) else None


def _parquet_date_max(path: Path) -> str | None:
    if not path.is_file():
        return None
    frame = pd.read_parquet(path, columns=["date"])
    if frame.empty:
        return None
    values = pd.to_datetime(frame["date"], errors="coerce")
    latest = values.max()
    return None if pd.isna(latest) else pd.Timestamp(latest).date().isoformat()


def _metric_check(checks: list[dict[str, Any]], name: str, value: Any, minimum: float) -> None:
    numeric = _number(value)
    checks.append(
        {
            "name": name,
            "passed": numeric is not None and numeric >= minimum,
            "value": numeric,
            "minimum": minimum,
        }
    )


def auto_promote_latest_paper_model(
    settings: Settings | Any | None = None,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Validate and activate the newest candidate for the active paper profile.

    This gate is intentionally limited to a deployment that already has paper
    permission. It never enables paper trading for a disabled market/profile.
    """
    resolved = settings or get_settings()
    sync_model_registry(resolved)
    active = get_active_deployment("CN", settings=resolved, sync=False)
    if active is None:
        return {"status": "noop", "reason": "no_active_cn_deployment"}
    if not bool(active.get("paper_enabled")):
        return {"status": "noop", "reason": "paper_trading_disabled"}

    profile_name = str(active.get("profile") or "").strip()
    profile = resolve_model_profile(profile_name)
    policy = profile.get("auto_paper_promotion")
    if not isinstance(policy, dict) or not bool(policy.get("enabled")):
        return {"status": "noop", "reason": "auto_promotion_disabled", "profile": profile_name}

    candidate = get_latest_model_for_profile("CN", profile_name, settings=resolved, sync=False)
    if candidate is None:
        return {"status": "noop", "reason": "no_candidate", "profile": profile_name}
    if str(candidate.get("id")) == str(active.get("id")):
        return {
            "status": "noop",
            "reason": "active_model_already_latest",
            "profile": profile_name,
            "model_version": candidate.get("model_version"),
        }
    if str(candidate.get("validation_status") or "") not in {"pending", "passed"}:
        return {
            "status": "noop",
            "reason": "candidate_not_eligible",
            "profile": profile_name,
            "model_version": candidate.get("model_version"),
            "validation_status": candidate.get("validation_status"),
        }

    artifact_dir = verify_immutable_artifact_location(candidate, resolved)
    verify_artifact_manifest(candidate, resolved)
    metadata = read_json(artifact_dir / "training_metadata.json")
    metrics = dict(candidate.get("validation_metrics") or {})
    if not metrics and isinstance(metadata.get("metrics"), dict):
        metrics = dict(metadata["metrics"])

    score_date = _parquet_date_max(artifact_dir / "inference_scores_latest.parquet")
    inference_date = _parquet_date_max(resolved.quant_dir / "inference_features_latest.parquet")
    objective = str(metadata.get("model_objective") or profile.get("model_objective") or "binary")
    checks: list[dict[str, Any]] = []

    min_valid_rows = int(policy.get("min_valid_rows") or 0)
    valid_rows = int(metadata.get("valid_rows") or 0)
    checks.append(
        {
            "name": "valid_rows",
            "passed": valid_rows >= min_valid_rows,
            "value": valid_rows,
            "minimum": min_valid_rows,
        }
    )
    if bool(policy.get("require_current_score_date", True)):
        checks.append(
            {
                "name": "current_score_date",
                "passed": bool(score_date and inference_date and score_date == inference_date),
                "value": score_date,
                "expected": inference_date,
            }
        )

    if objective == "regression":
        _metric_check(checks, "ic", metrics.get("ic"), float(policy.get("min_ic") or 0.0))
        _metric_check(
            checks,
            "rank_ic",
            metrics.get("rank_ic"),
            float(policy.get("min_rank_ic") or 0.0),
        )
        allowed_drop = float(policy.get("max_rank_ic_drop_from_active") or 0.0)
        active_rank_ic = _number((active.get("validation_metrics") or {}).get("rank_ic"))
        candidate_rank_ic = _number(metrics.get("rank_ic"))
        if allowed_drop > 0 and active_rank_ic is not None:
            minimum = active_rank_ic - allowed_drop
            checks.append(
                {
                    "name": "rank_ic_stability",
                    "passed": candidate_rank_ic is not None and candidate_rank_ic >= minimum,
                    "value": candidate_rank_ic,
                    "minimum": minimum,
                    "active_value": active_rank_ic,
                }
            )
    else:
        _metric_check(checks, "auc", metrics.get("auc"), float(policy.get("min_auc") or 0.0))
        allowed_drop = float(policy.get("max_auc_drop_from_active") or 0.0)
        active_auc = _number((active.get("validation_metrics") or {}).get("auc"))
        candidate_auc = _number(metrics.get("auc"))
        if allowed_drop > 0 and active_auc is not None:
            minimum = active_auc - allowed_drop
            checks.append(
                {
                    "name": "auc_stability",
                    "passed": candidate_auc is not None and candidate_auc >= minimum,
                    "value": candidate_auc,
                    "minimum": minimum,
                    "active_value": active_auc,
                }
            )

    passed = all(bool(check.get("passed")) for check in checks)
    validation_metrics = {
        **metrics,
        "auto_paper_promotion": {
            "passed": passed,
            "score_date": score_date,
            "inference_date": inference_date,
            "checks": checks,
        },
    }
    if not passed:
        if dry_run:
            return {
                "status": "would_reject",
                "reason": "validation_gate_failed",
                "profile": profile_name,
                "model_version": candidate.get("model_version"),
                "checks": checks,
            }
        updated = update_validation_status(
            market="CN",
            model_version=str(candidate["model_version"]),
            validation_status="failed",
            metrics=validation_metrics,
            settings=resolved,
        )
        return {
            "status": "rejected",
            "reason": "validation_gate_failed",
            "profile": profile_name,
            "model_version": candidate.get("model_version"),
            "validation_status": updated.get("validation_status"),
            "checks": checks,
        }

    if dry_run:
        return {
            "status": "would_promote",
            "profile": profile_name,
            "model_version": candidate.get("model_version"),
            "score_date": score_date,
            "checks": checks,
        }
    if str(candidate.get("validation_status")) != "passed":
        update_validation_status(
            market="CN",
            model_version=str(candidate["model_version"]),
            validation_status="passed",
            metrics=validation_metrics,
            settings=resolved,
        )
    deployment = activate_model(
        market="CN",
        model_version=str(candidate["model_version"]),
        paper_enabled=True,
        actor="pipeline_auto_promotion",
        reason="Automatic paper-only promotion after configured holdout and freshness gates passed.",
        settings=resolved,
    )
    return {
        "status": "promoted",
        "profile": profile_name,
        "model_version": deployment.get("model_version"),
        "revision": deployment.get("revision"),
        "score_date": score_date,
        "checks": checks,
    }
