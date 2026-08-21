from __future__ import annotations

import sys
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.services import us_market as us_market_service


class _FakeCursor:
    def __init__(self, coverage: dict[str, object]) -> None:
        self.coverage = coverage

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, *_args, **_kwargs):
        return self

    def fetchone(self):
        return dict(self.coverage)


class _FakeConnection:
    def __init__(self, coverage: dict[str, object]) -> None:
        self.coverage = coverage

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def cursor(self):
        return _FakeCursor(self.coverage)


class UsMarketServiceTests(unittest.TestCase):
    def test_market_session_is_open_during_regular_hours(self) -> None:
        result = us_market_service._us_market_session_state(
            datetime(2026, 8, 21, 12, 13, tzinfo=ZoneInfo("America/New_York")),
            {},
        )
        self.assertEqual(result["status"], "open")
        self.assertEqual(result["label"], "US Market Open")
        self.assertEqual(result["next_transition"], "closes")
        self.assertTrue(str(result["next_transition_at"]).endswith("16:00:00-04:00"))

    def test_market_session_uses_early_close_calendar(self) -> None:
        result = us_market_service._us_market_session_state(
            datetime(2026, 11, 27, 12, 0, tzinfo=ZoneInfo("America/New_York")),
            {date(2026, 11, 27): "09:30-13:00"},
        )
        self.assertEqual(result["status"], "open")
        self.assertTrue(str(result["next_transition_at"]).endswith("13:00:00-05:00"))

    def test_market_session_skips_weekends_and_full_holidays(self) -> None:
        result = us_market_service._us_market_session_state(
            datetime(2026, 9, 4, 17, 0, tzinfo=ZoneInfo("America/New_York")),
            {date(2026, 9, 7): ""},
        )
        self.assertEqual(result["status"], "closed")
        self.assertEqual(result["next_transition"], "opens")
        self.assertTrue(str(result["next_transition_at"]).startswith("2026-09-08T09:30:00"))

    def test_symbol_validation_accepts_us_tickers_and_rejects_unsafe_input(self) -> None:
        self.assertEqual(us_market_service._normalize_symbol(" brk.b "), "BRK.B")
        with self.assertRaises(us_market_service.UsMarketError):
            us_market_service._normalize_symbol("AAPL; drop table")

    def test_model_gate_reports_real_history_shortfall(self) -> None:
        coverage = {
            "active_symbols": 5336,
            "latest_trade_date": "2026-08-11",
            "first_trade_date": "2026-05-12",
            "trading_dates": 63,
            "total_bars": 333878,
            "latest_symbols": 5300,
        }
        with mock.patch.object(us_market_service, "_connect", return_value=_FakeConnection(coverage)):
            result = us_market_service.get_us_model_status()

        self.assertEqual(result["market"], "US")
        self.assertEqual(result["currency"], "USD")
        self.assertEqual(result["profile"]["name"], "us_5d_v1")
        self.assertEqual(result["profile"]["status"], "insufficient_history")
        self.assertFalse(result["gate"]["ready"])
        self.assertEqual(result["gate"]["available_trading_dates"], 63)
        self.assertEqual(result["gate"]["required_trading_dates"], 504)

    def test_model_remains_untrained_after_history_gate_passes(self) -> None:
        coverage = {
            "active_symbols": 5336,
            "latest_trade_date": "2026-08-11",
            "first_trade_date": "2024-01-02",
            "trading_dates": 510,
            "total_bars": 2_500_000,
            "latest_symbols": 5336,
        }
        with mock.patch.object(us_market_service, "_connect", return_value=_FakeConnection(coverage)):
            result = us_market_service.get_us_model_status()

        self.assertTrue(result["gate"]["history_ready"])
        self.assertFalse(result["gate"]["training_ready"])
        self.assertEqual(result["profile"]["status"], "not_trained")


if __name__ == "__main__":
    unittest.main()
