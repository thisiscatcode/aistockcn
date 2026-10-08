from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from active_model_inference import file_digest, published_scores, refresh_predictions


class ActiveModelInferenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.quant = Path(self.temporary.name) / "quant_data"
        self.artifact = self.quant / "model_registry" / "CN" / "test-v1"
        self.artifact.mkdir(parents=True)
        self.mappings = {"industry": ["UNKNOWN", "A", "B"]}
        self.metadata = {
            "feature_cols": ["x", "industry"], "categorical_cols": ["industry"],
            "category_mappings": self.mappings, "score_date": "2026-09-09",
            "profile_name": "short_5d", "label_horizon": 5,
            "model_objective": "binary",
        }
        features = pd.DataFrame({"x": np.arange(60, dtype=np.float32), "industry": [1, 2] * 30})
        model = lgb.LGBMClassifier(n_estimators=5, min_child_samples=2, num_leaves=4, verbosity=-1, n_jobs=1)
        model.fit(features, (features.x > 30).astype(int), categorical_feature=["industry"])
        model.booster_.save_model(str(self.artifact / "lightgbm_model.txt"))
        self.write_metadata()
        self.write_inputs("2026-09-10")
        # A separate archived score artifact must never be overwritten.
        (self.artifact / "inference_scores_latest.parquet").write_bytes(b"training-snapshot")

    def write_metadata(self):
        (self.artifact / "training_metadata.json").write_text(json.dumps(self.metadata))

    def write_inputs(self, date):
        pd.DataFrame({
            "date": [date] * 3, "code": ["000001", "000002", "000003"],
            "name": ["One", "Two", "ST Three"], "x": [2., 45., 50.],
            "industry": ["A", "B", "UNSEEN"], "close": [10., 20., 30.],
        }).to_parquet(self.quant / "inference_features_latest.parquet", index=False)

    def test_new_days_are_scored_without_changing_model_or_archived_artifacts(self):
        digests = {p.name: file_digest(p) for p in self.artifact.iterdir()}
        first = refresh_predictions(self.quant, self.artifact)
        rows = pd.read_parquet(first)
        self.assertEqual(set(rows.code), {"000001", "000002"})
        self.assertEqual(str(rows.date.max().date()), "2026-09-10")
        self.assertEqual(refresh_predictions(self.quant, self.artifact), first)
        self.assertEqual(published_scores(self.quant, self.artifact), first)
        self.write_inputs("2026-09-11")
        second = refresh_predictions(self.quant, self.artifact)
        self.assertNotEqual(second, first)
        self.assertEqual({p.name: file_digest(p) for p in self.artifact.iterdir()}, digests)

    def test_missing_features_do_not_replace_published_snapshot(self):
        first = refresh_predictions(self.quant, self.artifact)
        path = self.quant / "inference_features_latest.parquet"
        pd.read_parquet(path).drop(columns="x").to_parquet(path, index=False)
        with self.assertRaisesRegex(RuntimeError, "missing columns"):
            refresh_predictions(self.quant, self.artifact)
        self.assertEqual(published_scores(self.quant, self.artifact), first)

    def test_stale_cached_inputs_block_after_market_data_advances(self):
        refresh_predictions(self.quant, self.artifact)
        path = self.quant / "daily_kline" / "000001.parquet"
        path.parent.mkdir()
        pd.DataFrame({"date": ["2026-09-11"]}).to_parquet(path, index=False)
        with self.assertRaisesRegex(RuntimeError, "features are stale"):
            refresh_predictions(self.quant, self.artifact)

    def test_daily_prediction_path_retains_five_session_rebalance_schedule(self):
        from paper_trade_futu import rebalance_decision

        path = self.quant / "daily_kline" / "000001.parquet"
        path.parent.mkdir()
        pd.DataFrame({"date": ["2026-09-03", "2026-09-04", "2026-09-07", "2026-09-08", "2026-09-09", "2026-09-10"]}).to_parquet(path, index=False)
        scores = refresh_predictions(self.quant, self.artifact)
        decision = rebalance_decision(scores_path=scores, state={"last_applied_signal_date": "2026-09-03"}, signal_date="2026-09-10")
        self.assertTrue(decision["rebalance_due"])
        self.assertEqual(decision["rebalance_every"], 5)
        self.assertEqual(decision["rebalance_wait_count"], 5)

    def test_corrupt_or_wrong_model_predictions_are_rejected(self):
        scores = refresh_predictions(self.quant, self.artifact)
        scores.write_bytes(b"corrupt")
        with self.assertRaisesRegex(RuntimeError, "checksum mismatch"):
            published_scores(self.quant, self.artifact)
        (self.artifact / "lightgbm_model.txt").write_text("different model")
        with self.assertRaisesRegex(RuntimeError, "different model"):
            published_scores(self.quant, self.artifact)

    def test_regression_scores_preserve_percentile_ranking(self):
        self.metadata["model_objective"] = "regression"
        self.write_metadata()
        result = pd.read_parquet(refresh_predictions(self.quant, self.artifact))
        self.assertIn("raw_score", result)
        np.testing.assert_allclose(result.score, [1., .5])

    def test_legacy_encoding_must_reproduce_archived_predictions(self):
        original = pd.read_parquet(refresh_predictions(self.quant, self.artifact))
        original.to_parquet(self.artifact / "inference_scores_latest.parquet", index=False)
        self.metadata.pop("category_mappings")
        self.metadata.update(production_train_date_min="2026-09-01", production_train_date_max="2026-09-02")
        self.write_metadata()
        path = self.quant / "model_profiles" / "short_5d" / "ml_features_ready.parquet"
        path.parent.mkdir(parents=True)
        pd.DataFrame({"date": ["2026-09-01", "2026-09-02"], "name": ["One", "Two"], "industry": ["A", "B"]}).to_parquet(path, index=False)
        self.write_inputs("2026-09-11")
        refresh_predictions(self.quant, self.artifact)
        cache = self.quant / "model_inference" / "CN" / "test-v1" / "category_encoding.json"
        self.assertEqual(json.loads(cache.read_text())["category_mappings"], self.mappings)
        cache.unlink()
        original["score"] = 0.
        original.to_parquet(self.artifact / "inference_scores_latest.parquet", index=False)
        self.write_inputs("2026-09-12")
        with self.assertRaisesRegex(RuntimeError, "does not reproduce"):
            refresh_predictions(self.quant, self.artifact)


if __name__ == "__main__":
    unittest.main()
