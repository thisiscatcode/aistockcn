from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.services import market_calendar


class ChinaSignalCalendarTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.settings = SimpleNamespace(
            quant_dir=root / "quant_data", pipeline_auto_run_state_path=root / "scheduler.json",
            pipeline_auto_run_time="18:00", pipeline_auto_run_timezone="Asia/Shanghai",
        )
        with mock.patch.object(market_calendar, "get_settings", return_value=self.settings):
            market_calendar.cache_china_trade_dates(pd.Series([
                "2026-09-28", "2026-09-29", "2026-09-30", "2026-10-08", "2026-10-09", "2026-10-12"
            ]))

    def expected(self, timestamp):
        return market_calendar.expected_china_signal_date(self.settings, now=datetime.fromisoformat(timestamp).replace(tzinfo=ZoneInfo("Asia/Shanghai")))

    def test_national_day_and_first_session_before_daily_update_use_september_30(self):
        self.assertEqual(self.expected("2026-10-07T20:00"), "2026-09-30")
        self.assertEqual(self.expected("2026-10-08T14:00"), "2026-09-30")
        self.assertEqual(self.expected("2026-10-08T17:59"), "2026-09-30")

    def test_daily_update_deadline_advances_expected_session(self):
        self.assertEqual(self.expected("2026-10-08T18:00"), "2026-10-08")
        self.assertEqual(self.expected("2026-10-09T09:35"), "2026-10-08")

    def test_weekend_uses_friday_and_respects_custom_schedule(self):
        self.assertEqual(self.expected("2026-10-10T20:00"), "2026-10-09")
        self.settings.pipeline_auto_run_time = "19:30"
        self.assertEqual(self.expected("2026-10-08T19:29"), "2026-09-30")
        self.assertEqual(self.expected("2026-10-08T19:30"), "2026-10-08")

    def test_calendar_outage_uses_verified_scheduler_date_without_weekday_assumptions(self):
        (self.settings.quant_dir / "reference" / "cn_trade_calendar.json").unlink()
        self.settings.pipeline_auto_run_state_path.write_text(json.dumps({
            "last_readiness": {"expected_trade_date": "2026-09-30"}
        }))
        self.assertEqual(self.expected("2026-10-07T20:00"), "2026-09-30")
        self.settings.pipeline_auto_run_state_path.unlink()
        self.assertIsNone(self.expected("2026-10-07T20:00"))


if __name__ == "__main__":
    unittest.main()
