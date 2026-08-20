from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.services import us_selection_control


class UsSelectionSchedulerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.local_now = datetime(2026, 8, 20, 12, 0, tzinfo=ZoneInfo("America/New_York"))
        self.settings = SimpleNamespace(
            run_dir=Path("/tmp/aistockcn-test-run"),
            us_selection_price_time="23:59",
            us_selection_average_time="23:59",
            us_selection_details_time="03:00",
            us_selection_universe_time="23:59",
        )

    def _run_scheduler(self, state: dict[str, object]):
        with (
            mock.patch.object(us_selection_control, "get_settings", return_value=self.settings),
            mock.patch.object(us_selection_control, "_ny_now", return_value=self.local_now),
            mock.patch.object(us_selection_control, "read_json", return_value=state),
            mock.patch.object(us_selection_control, "_us_details_missing_count", return_value=5_090),
            mock.patch.object(us_selection_control, "_write_scheduler_state"),
            mock.patch.object(us_selection_control, "_maybe_start_scheduled_lane", return_value=state) as start_lane,
        ):
            us_selection_control._maybe_start_us_selection_jobs()
        return start_lane

    def test_details_lane_runs_at_most_once_per_local_day(self) -> None:
        start_lane = self._run_scheduler({"last_attempted_details_local_date": "2026-08-20"})
        start_lane.assert_not_called()

    def test_details_lane_starts_when_due_and_not_attempted_today(self) -> None:
        start_lane = self._run_scheduler({"last_attempted_details_local_date": "2026-08-19"})
        start_lane.assert_called_once()
        args = start_lane.call_args.args
        self.assertEqual(args[:3], ("details", None, "details_local_date"))


if __name__ == "__main__":
    unittest.main()
