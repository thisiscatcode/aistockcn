from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.services import overview as overview_service


class PortfolioOverviewTests(unittest.TestCase):
    def test_portfolio_overview_uses_daily_snapshots_for_pnl_and_history(self) -> None:
        daily_history = {
            "rows": 2,
            "daily": [
                {
                    "trade_date": "2026-08-06",
                    "summary": {"total_assets": 105.0, "total_pnl": 5.0},
                },
                {
                    "trade_date": "2026-08-05",
                    "summary": {"total_assets": 100.0, "total_pnl": 0.0},
                },
            ],
        }
        paper_overview = {
            "live_summary": {"market_value": 25.0, "total_pnl": 10.0},
            "gateway": {"market": "CN"},
            "state": {"balance_metrics": {"total_assets": 110.0, "cash": 85.0}},
        }

        with (
            mock.patch.object(overview_service, "get_paper_trading_overview", return_value=paper_overview),
            mock.patch.object(overview_service, "get_paper_trading_daily_history", return_value=daily_history),
            mock.patch.object(overview_service, "get_paper_trading_targets", return_value={"targets": []}),
            mock.patch.object(overview_service, "get_latest_picks", return_value={"picks": []}),
            mock.patch.object(
                overview_service,
                "_benchmark_by_date",
                return_value={"2026-08-05": 100.0, "2026-08-06": 101.0},
            ),
        ):
            result = overview_service.get_portfolio_overview()

        self.assertEqual(result["account"]["today_pnl"], 10.0)
        self.assertAlmostEqual(result["account"]["today_pnl_pct"], 0.1)
        self.assertEqual(len(result["performance"]["points"]), 2)
        self.assertEqual(result["performance"]["points"][-1]["account_equity"], 105.0)
        self.assertNotIn("Portfolio performance history is unavailable.", result["warnings"])
        self.assertFalse(any("today_pnl is unavailable" in warning for warning in result["warnings"]))


if __name__ == "__main__":
    unittest.main()
