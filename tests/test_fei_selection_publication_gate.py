from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.services import fei_selection


def test_latest_selection_is_scoped_to_published_trade_date(monkeypatch) -> None:
    calls: list[tuple[str | None, int]] = []

    monkeypatch.setattr(fei_selection, "get_published_trade_date", lambda: "2026-08-14")

    def fake_rows(*, as_of_date: str | None = None, limit: int = 6000):
        calls.append((as_of_date, limit))
        return [{"code": "000001", "exchange": "sz", "trade_date": date(2026, 8, 14)}]

    monkeypatch.setattr(fei_selection, "get_fei_selection_rows", fake_rows)

    payload = fei_selection.get_fei_selection(limit=123)

    assert calls == [("2026-08-14", 123)]
    assert payload["rows"] == 1
    assert payload["latest_date"] == "2026-08-14T00:00:00"
    assert payload["published_trade_date"] == "2026-08-14"


def test_latest_selection_falls_back_when_no_published_date_exists(monkeypatch) -> None:
    calls: list[str | None] = []

    monkeypatch.setattr(fei_selection, "get_published_trade_date", lambda: None)

    def fake_rows(*, as_of_date: str | None = None, limit: int = 6000):
        calls.append(as_of_date)
        return []

    monkeypatch.setattr(fei_selection, "get_fei_selection_rows", fake_rows)

    payload = fei_selection.get_fei_selection()

    assert calls == [None]
    assert payload["rows"] == 0
    assert payload["published_trade_date"] is None
