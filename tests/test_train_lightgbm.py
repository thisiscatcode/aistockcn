from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from train_lightgbm import best_iteration_for_refit, build_model


class TrainLightgbmTests(unittest.TestCase):
    def test_best_iteration_for_refit_uses_early_stopping_result(self) -> None:
        self.assertEqual(best_iteration_for_refit(SimpleNamespace(best_iteration_=137), 500), 137)

    def test_best_iteration_for_refit_falls_back_to_configured_rounds(self) -> None:
        self.assertEqual(best_iteration_for_refit(SimpleNamespace(best_iteration_=0), 500), 500)
        self.assertEqual(best_iteration_for_refit(SimpleNamespace(), 500), 500)

    @mock.patch("train_lightgbm.lgb.LGBMRegressor")
    def test_production_regressor_uses_selected_iteration_count(self, regressor: mock.Mock) -> None:
        build_model("regression", {"n_estimators": 500, "random_state": 42}, n_estimators=137)

        regressor.assert_called_once_with(
            objective="regression_l1",
            n_estimators=137,
            random_state=42,
        )

    @mock.patch("train_lightgbm.lgb.LGBMClassifier")
    def test_production_classifier_preserves_balanced_weights(self, classifier: mock.Mock) -> None:
        build_model("binary", {"n_estimators": 500}, n_estimators=91)

        classifier.assert_called_once_with(
            objective="binary",
            class_weight="balanced",
            n_estimators=91,
        )


if __name__ == "__main__":
    unittest.main()
