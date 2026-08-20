from __future__ import annotations

import importlib.util
import math
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "update_us_selection_data.py"

spec = importlib.util.spec_from_file_location("update_us_selection_market_cap", SCRIPT_PATH)
assert spec is not None
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
assert spec.loader is not None
spec.loader.exec_module(module)


class UsMarketCapPipelineTests(unittest.TestCase):
    def test_finnhub_million_usd_is_normalized_to_full_usd(self) -> None:
        value = module.finnhub_market_cap_usd(4_623_873.9321842445, "USD")
        self.assertAlmostEqual(value, 4_623_873_932_184.244)

    def test_invalid_provider_values_and_currency_are_rejected(self) -> None:
        for value in (None, "", 0, -1, float("nan"), float("inf")):
            self.assertIsNone(module.finnhub_market_cap_usd(value, "USD"))
        self.assertIsNone(module.finnhub_market_cap_usd(100, "EUR"))
        self.assertIsNone(module.finnhub_market_cap_usd(100, None))

    def test_provider_value_is_validated_against_price_and_shares(self) -> None:
        decision = module.resolve_market_cap(
            provider_value_millions=4_623_873.9321842445,
            currency="USD",
            close=316.83,
            shares_yi=146.8736,
        )
        self.assertEqual(decision.status, "validated")
        self.assertEqual(decision.source, "finnhub_profile2")
        self.assertFalse(decision.is_estimated)
        self.assertLess(decision.deviation_pct, 1)

    def test_large_provider_deviation_is_not_accepted(self) -> None:
        decision = module.resolve_market_cap(
            provider_value_millions=1_000_000,
            currency="USD",
            close=100,
            shares_yi=10,
        )
        self.assertEqual(decision.status, "rejected_deviation")
        self.assertIsNone(decision.value_usd)
        self.assertGreater(decision.deviation_pct, 20)

    def test_calculated_fallback_uses_latest_price_and_outstanding_shares(self) -> None:
        decision = module.resolve_market_cap(
            provider_value_millions=None,
            currency="USD",
            close=316.83,
            shares_yi=145.84,
        )
        self.assertEqual(decision.status, "calculated_fallback")
        self.assertEqual(decision.source, "close_x_outstanding_shares")
        self.assertTrue(decision.is_estimated)
        self.assertAlmostEqual(decision.value_usd, 4_620_648_720_000)

    def test_missing_calculation_inputs_do_not_create_fake_market_cap(self) -> None:
        for close, shares in ((None, 10), (100, None), (0, 10), (100, 0), (math.inf, 10)):
            decision = module.resolve_market_cap(
                provider_value_millions=None,
                currency="USD",
                close=close,
                shares_yi=shares,
            )
            self.assertEqual(decision.status, "insufficient_data")
            self.assertIsNone(decision.value_usd)


if __name__ == "__main__":
    unittest.main()
