from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.services import market_capabilities


class MarketCapabilitiesTests(unittest.TestCase):
    def test_us_execution_is_readiness_only_even_when_model_passes(self) -> None:
        model = {
            "as_of": "2026-08-14",
            "gate": {"history_ready": True, "training_ready": True, "walk_forward_ready": True, "blockers": []},
        }
        with mock.patch.object(market_capabilities, "get_us_model_status", return_value=model), mock.patch.object(
            market_capabilities, "_deployment", return_value={"paper_enabled": True}
        ):
            result = market_capabilities.get_market_capabilities("US")
        execution = result["by_stage"]["execution"]
        self.assertEqual(execution["mode"], "readiness_only")
        self.assertEqual(execution["actions"], ["view_readiness_gates"])
        self.assertNotIn("submit_order", execution["actions"])

    def test_cn_execution_requires_registry_validation_and_permission(self) -> None:
        with mock.patch.object(
            market_capabilities,
            "_deployment",
            return_value={"validation_status": "passed", "paper_enabled": True, "updated_at": "2026-08-14"},
        ):
            result = market_capabilities.get_market_capabilities("CN")
        self.assertEqual(result["by_stage"]["execution"]["status"], "live")
        self.assertIn("control_daemon", result["by_stage"]["execution"]["actions"])

    def test_unknown_market_is_rejected(self) -> None:
        with self.assertRaises(market_capabilities.MarketCapabilityError):
            market_capabilities.get_market_capabilities("HK")


if __name__ == "__main__":
    unittest.main()
