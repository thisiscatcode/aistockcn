from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.services import model_profiles as model_profiles_service
from backtest_walk_forward import select_topk_drop_picks
from feature_engineering import build_features
from train_lightgbm import cross_sectional_demean, percentile_rank_scores


class MediumStrategyTests(unittest.TestCase):
    @staticmethod
    def _panel() -> tuple[pd.DataFrame, pd.DataFrame]:
        panel = pd.DataFrame(
            {
                "date": pd.date_range("2026-01-01", periods=4, freq="D"),
                "code": ["000001"] * 4,
                "exchange": ["sz"] * 4,
                "open": [10.0, 11.0, 12.0, 13.0],
                "high": [10.5, 11.5, 12.5, 13.5],
                "low": [9.5, 10.5, 11.5, 12.5],
                "close": [10.0, 12.0, 15.0, 16.0],
                "turnover": [1.0] * 4,
                "volume": [100.0] * 4,
            }
        )
        stocks = pd.DataFrame(
            [{"code": "000001", "exchange": "sz", "name": "A", "industry": "Bank"}]
        )
        return panel, stocks

    def test_next_open_return_uses_executable_entry_price(self) -> None:
        panel, stocks = self._panel()

        result = build_features(
            panel,
            stocks,
            label_horizon=2,
            label_threshold=0.0,
            return_mode="next_open_to_close",
        )

        self.assertAlmostEqual(float(result.loc[0, "future_return"]), 15.0 / 11.0 - 1.0)

    def test_legacy_close_return_remains_unchanged(self) -> None:
        panel, stocks = self._panel()

        result = build_features(panel, stocks, label_horizon=2, label_threshold=0.0)

        self.assertAlmostEqual(float(result.loc[0, "future_return"]), 15.0 / 10.0 - 1.0)

    def test_cross_sectional_scores_are_stable_percentiles(self) -> None:
        scores = percentile_rank_scores(np.array([3.0, 1.0, 2.0], dtype=np.float32))
        demeaned = cross_sectional_demean(
            np.array([0.1, 0.2, 0.7, 2.0], dtype=np.float32),
            np.array(["2026-01-01", "2026-01-01", "2026-01-01", "2026-01-02"]),
        )

        np.testing.assert_allclose(scores, np.array([1.0, 1.0 / 3.0, 2.0 / 3.0]), rtol=1e-6)
        np.testing.assert_allclose(demeaned[:3].sum(), 0.0, atol=1e-6)
        self.assertAlmostEqual(float(demeaned[3]), 0.0)

    def test_topk_drop_replaces_only_configured_number(self) -> None:
        scored = pd.DataFrame(
            {
                "code": ["A", "B", "C", "D", "E", "F"],
                "score": [1.0, 0.9, 0.8, 0.7, 0.6, 0.5],
            }
        )

        picks = select_topk_drop_picks(
            scored,
            held_symbols={"C", "D", "E", "F"},
            top_k=4,
            max_drop=1,
        )

        self.assertEqual(set(picks["code"]), {"A", "C", "D", "E"})

    def test_catalog_adds_medium_profile_without_changing_active_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "model_profiles.json").write_text(
                (ROOT / "run" / "model_profiles.json").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            settings = SimpleNamespace(run_dir=run_dir)
            with mock.patch.object(model_profiles_service, "get_settings", return_value=settings):
                catalog = model_profiles_service.get_model_profile_catalog()

        profile = next(item for item in catalog["profiles"] if item["name"] == "medium_10d_v2")
        self.assertEqual(catalog["active_profile"], "short_3d")
        self.assertEqual(profile["model_objective"], "regression")
        self.assertEqual(profile["label_threshold"], 0.0)
        self.assertEqual(profile["backtest_max_drop"], 4)


if __name__ == "__main__":
    unittest.main()
