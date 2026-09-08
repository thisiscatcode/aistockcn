from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.services import model_promotion  # noqa: E402


class ModelPromotionTests(unittest.TestCase):
    def _fixture(self, root: Path, *, rank_ic: float = 0.09) -> tuple[SimpleNamespace, dict, dict, dict]:
        quant_dir = root / "quant_data"
        artifact_dir = quant_dir / "model_registry" / "CN" / "candidate-v2"
        artifact_dir.mkdir(parents=True)
        pd.DataFrame([{"date": "2026-09-08", "code": "000001", "score": 0.9}]).to_parquet(
            artifact_dir / "inference_scores_latest.parquet", index=False
        )
        pd.DataFrame([{"date": "2026-09-08", "code": "000001"}]).to_parquet(
            quant_dir / "inference_features_latest.parquet", index=False
        )
        (artifact_dir / "training_metadata.json").write_text(
            json.dumps({"model_objective": "regression", "valid_rows": 200_000}),
            encoding="utf-8",
        )
        settings = SimpleNamespace(quant_dir=quant_dir, project_root=root)
        active = {
            "id": "active-v1",
            "profile": "medium_10d_v2",
            "paper_enabled": True,
            "validation_metrics": {"rank_ic": 0.08},
        }
        candidate = {
            "id": "candidate-v2",
            "model_version": "candidate-v2",
            "profile": "medium_10d_v2",
            "artifact_path": str(artifact_dir.relative_to(root)),
            "validation_status": "pending",
            "validation_metrics": {"ic": 0.04, "rank_ic": rank_ic},
        }
        profile = {
            "name": "medium_10d_v2",
            "model_objective": "regression",
            "auto_paper_promotion": {
                "enabled": True,
                "min_valid_rows": 100_000,
                "min_ic": 0.01,
                "min_rank_ic": 0.03,
                "max_rank_ic_drop_from_active": 0.03,
                "require_current_score_date": True,
            },
        }
        return settings, active, candidate, profile

    def test_matching_fresh_candidate_is_validated_and_promoted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings, active, candidate, profile = self._fixture(Path(tmp))
            with (
                mock.patch.object(model_promotion, "sync_model_registry"),
                mock.patch.object(model_promotion, "get_active_deployment", return_value=active),
                mock.patch.object(model_promotion, "get_latest_model_for_profile", return_value=candidate),
                mock.patch.object(model_promotion, "resolve_model_profile", return_value=profile),
                mock.patch.object(
                    model_promotion,
                    "verify_immutable_artifact_location",
                    return_value=settings.project_root / candidate["artifact_path"],
                ),
                mock.patch.object(model_promotion, "verify_artifact_manifest"),
                mock.patch.object(
                    model_promotion,
                    "update_validation_status",
                    return_value={"validation_status": "passed"},
                ) as update,
                mock.patch.object(
                    model_promotion,
                    "activate_model",
                    return_value={"model_version": "candidate-v2", "revision": 3},
                ) as activate,
            ):
                result = model_promotion.auto_promote_latest_paper_model(settings)

        self.assertEqual(result["status"], "promoted")
        self.assertEqual(result["score_date"], "2026-09-08")
        self.assertEqual(update.call_args.kwargs["validation_status"], "passed")
        self.assertEqual(activate.call_args.kwargs["model_version"], "candidate-v2")
        self.assertTrue(all(check["passed"] for check in result["checks"]))

    def test_degraded_candidate_is_rejected_without_activation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings, active, candidate, profile = self._fixture(Path(tmp), rank_ic=0.01)
            with (
                mock.patch.object(model_promotion, "sync_model_registry"),
                mock.patch.object(model_promotion, "get_active_deployment", return_value=active),
                mock.patch.object(model_promotion, "get_latest_model_for_profile", return_value=candidate),
                mock.patch.object(model_promotion, "resolve_model_profile", return_value=profile),
                mock.patch.object(
                    model_promotion,
                    "verify_immutable_artifact_location",
                    return_value=settings.project_root / candidate["artifact_path"],
                ),
                mock.patch.object(model_promotion, "verify_artifact_manifest"),
                mock.patch.object(
                    model_promotion,
                    "update_validation_status",
                    return_value={"validation_status": "failed"},
                ) as update,
                mock.patch.object(model_promotion, "activate_model") as activate,
            ):
                result = model_promotion.auto_promote_latest_paper_model(settings)

        self.assertEqual(result["status"], "rejected")
        self.assertEqual(update.call_args.kwargs["validation_status"], "failed")
        activate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
