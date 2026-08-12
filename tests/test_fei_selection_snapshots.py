from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.services import fei_selection_snapshots as snapshots


def cat_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "code": "000001",
        "exchange": "sz",
        "pre_explosion_flg": True,
        "pre_explosion_entry_state": "WATCH",
        "pre_explosion_score": 80,
        "pre_explosion_reason_tags": ["washout", "short_structure_ok"],
        "pre_explosion_pct_chg": -1.0,
        "pre_explosion_pct_chg_5d": 0.01,
        "pre_explosion_pct_chg_20d": 0.02,
        "pre_explosion_bias20": 0.01,
        "pre_explosion_pct_from_40d_low_close": 0.08,
        "pre_explosion_close_to_low20": 0.08,
        "pre_explosion_close_to_high20": -0.08,
    }
    row.update(overrides)
    return row


def test_cat_early_candidate_accepts_watch_rows_inside_thresholds() -> None:
    assert snapshots.is_cat_early_candidate(cat_row())


def test_cat_early_candidate_rejects_extended_daily_gain() -> None:
    assert not snapshots.is_cat_early_candidate(cat_row(pre_explosion_pct_chg=3.0))


def test_cat_early_rank_score_rewards_washout_and_pullback() -> None:
    strong = snapshots.cat_early_rank_score(cat_row())
    weaker = snapshots.cat_early_rank_score(cat_row(pre_explosion_reason_tags=[], pre_explosion_pct_chg=1.0))

    assert strong > weaker


class FakeCursor:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    def execute(self, _sql: str, _params: list[object]) -> None:
        return None

    def fetchall(self) -> list[dict[str, object]]:
        return self.rows


def test_has_complete_snapshot_requires_all_three_lists() -> None:
    complete = FakeCursor(
        [
            {"list_type": "lobster", "rows": 50},
            {"list_type": "cat", "rows": 12},
            {"list_type": "quant", "rows": 50},
        ]
    )
    incomplete = FakeCursor([{"list_type": "lobster", "rows": 50}, {"list_type": "quant", "rows": 50}])

    assert snapshots._has_complete_snapshot(complete, "2026-06-09")
    assert not snapshots._has_complete_snapshot(incomplete, "2026-06-09")


def test_scheduled_snapshot_runs_once_after_six(monkeypatch) -> None:
    state: dict[str, object] = {}
    writes: list[dict[str, object]] = []
    calls: list[bool] = []

    monkeypatch.setattr(snapshots, "_read_state", lambda: state.copy())
    monkeypatch.setattr(snapshots, "_write_state", lambda payload: (writes.append(payload.copy()), state.update(payload)))
    monkeypatch.setattr(snapshots, "get_settings", lambda: SimpleNamespace(fei_selection_snapshot_time="06:00"))
    monkeypatch.setattr(snapshots, "_local_now", lambda: datetime.fromisoformat("2026-06-10T06:00:00+08:00"))

    def fake_refresh() -> dict[str, object]:
        calls.append(True)
        return {"ok": True, "status": "saved", "trade_date": "2026-06-09", "saved": True}

    monkeypatch.setattr(snapshots, "maybe_refresh_latest_snapshot", fake_refresh)

    snapshots._run_scheduled_once_if_due()
    snapshots._run_scheduled_once_if_due()

    assert len(calls) == 1
    assert state["last_trigger_local_date"] == "2026-06-10"
    assert state["last_saved_trade_date"] == "2026-06-09"
    assert writes[-1]["last_status"] == "saved"


def test_scheduled_snapshot_retries_same_day_until_saved(monkeypatch) -> None:
    state: dict[str, object] = {}
    writes: list[dict[str, object]] = []
    calls: list[bool] = []

    monkeypatch.setattr(snapshots, "_read_state", lambda: state.copy())
    monkeypatch.setattr(snapshots, "_write_state", lambda payload: (writes.append(payload.copy()), state.update(payload)))
    monkeypatch.setattr(snapshots, "get_settings", lambda: SimpleNamespace(fei_selection_snapshot_time="06:00"))
    monkeypatch.setattr(snapshots, "_local_now", lambda: datetime.fromisoformat("2026-06-10T06:00:00+08:00"))

    def fake_refresh() -> dict[str, object]:
        calls.append(True)
        if len(calls) == 1:
            return {
                "ok": False,
                "status": "not_ready",
                "trade_date": "2026-06-09",
                "reasons": ["quant_latest_date_mismatch"],
                "saved": False,
            }
        return {"ok": True, "status": "saved", "trade_date": "2026-06-09", "saved": True}

    monkeypatch.setattr(snapshots, "maybe_refresh_latest_snapshot", fake_refresh)

    snapshots._run_scheduled_once_if_due()
    snapshots._run_scheduled_once_if_due()
    snapshots._run_scheduled_once_if_due()

    assert len(calls) == 2
    assert writes[0]["retry_pending"] is True
    assert writes[0]["last_pending_trade_date"] == "2026-06-09"
    assert state["retry_pending"] is False
    assert state["last_trigger_local_date"] == "2026-06-10"
    assert state["last_saved_trade_date"] == "2026-06-09"


def test_snapshot_coverage_payload_marks_missing_snapshot_lists() -> None:
    payload = snapshots._snapshot_coverage_payload(
        {
            "trade_date": "2026-06-23",
            "metric_rows": 5206,
            "average_trade_rows": 5192,
            "snapshot_row_count": 50,
            "snapshot_list_count": 1,
            "list_types": ["lobster"],
        }
    )

    assert payload["trade_date"] == "2026-06-23"
    assert payload["complete"] is False
    assert payload["missing_list_types"] == ["cat", "quant"]
