from __future__ import annotations

import sys
import urllib.error
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "apps" / "api"))

import scripts.import_stcn_average_trade as stcn_import
from app.services.fei_db_sync import _metric_readiness_publishable, _parse_spot_code, _stcn_summary_reaches_target
from scripts.import_daily_kline_to_postgres import rows_from_kline


def source_row(code: str) -> dict[str, str]:
    return {"secucode": code, "rq1": "2026-05-22", "bs1": "1234"}


def test_parse_market_rows_skips_excluded_stcn_codes() -> None:
    rows = stcn_import.parse_market_rows(
        {"exchange": "sz"},
        [
            source_row("200011"),
            source_row("201872"),
            source_row("689009"),
            source_row("900901"),
        ],
    )

    assert rows == []


def test_parse_market_rows_keeps_supported_a_share_prefixes() -> None:
    rows = stcn_import.parse_market_rows(
        {"exchange": "sz"},
        [
            source_row("000001"),
            source_row("002001"),
            source_row("300001"),
            source_row("600000"),
            source_row("688001"),
        ],
    )

    assert [(row.code, row.trade_date, row.average_trade) for row in rows] == [
        ("000001", date(2026, 5, 22), 1234),
        ("002001", date(2026, 5, 22), 1234),
        ("300001", date(2026, 5, 22), 1234),
        ("600000", date(2026, 5, 22), 1234),
        ("688001", date(2026, 5, 22), 1234),
    ]


def test_fetch_json_retries_with_backoff_and_success_sleep(monkeypatch) -> None:
    calls: list[tuple[str, float]] = []
    sleeps: list[float] = []

    def fake_fetch_once(url: str, *, timeout: float) -> dict[str, object]:
        calls.append((url, timeout))
        if len(calls) == 1:
            raise urllib.error.URLError("temporary block")
        return {"data": []}

    monkeypatch.setattr(stcn_import, "_fetch_json_once", fake_fetch_once)
    monkeypatch.setattr(stcn_import.time, "sleep", lambda seconds: sleeps.append(seconds))

    payload = stcn_import.fetch_json("http://example.test/data.json", timeout=10, retries=3, sleep_seconds=3)

    assert payload == {"data": []}
    assert calls == [("http://example.test/data.json", 10), ("http://example.test/data.json", 10)]
    assert sleeps == [3, 3]


def test_fei_sync_treats_stcn_no_update_for_target_date_as_imported() -> None:
    assert _stcn_summary_reaches_target(
        {"status": "no_update", "source_latest_trade_date": "2026-06-15"},
        "2026-06-15",
    )
    assert not _stcn_summary_reaches_target(
        {"status": "no_update", "source_latest_trade_date": "2026-06-12"},
        "2026-06-15",
    )


def test_fei_sync_metric_readiness_requires_complete_publish_coverage() -> None:
    assert _metric_readiness_publishable(
        {
            "close_rows": 5100,
            "volume_rows": 5100,
            "amount_rows": 5100,
            "turnover_rows": 5100,
            "average_trade_rows": 5100,
        },
        5000,
    )
    assert not _metric_readiness_publishable(
        {
            "close_rows": 5100,
            "volume_rows": 5100,
            "amount_rows": 5100,
            "turnover_rows": 4999,
            "average_trade_rows": 5100,
        },
        5000,
    )


def test_fei_sync_parses_akshare_spot_codes_for_supported_exchanges() -> None:
    assert _parse_spot_code("sz000001") == ("sz", "000001")
    assert _parse_spot_code("sh600000") == ("sh", "600000")
    assert _parse_spot_code("600000") == ("sh", "600000")
    assert _parse_spot_code("000001") == ("sz", "000001")
    assert _parse_spot_code("bj920000") == (None, None)
    assert _parse_spot_code("920000") == (None, None)


def test_daily_kline_rows_can_filter_one_target_date(tmp_path: Path) -> None:
    path = tmp_path / "000001.parquet"
    pd.DataFrame(
        [
            {"date": "2026-05-22", "code": "000001", "exchange": "sz", "close": 10.0, "turnover": 1.1},
            {"date": "2026-05-25", "code": "000001", "exchange": "sz", "close": 11.0, "turnover": 1.2},
        ]
    ).to_parquet(path, index=False)

    rows = rows_from_kline(path, target_date=date(2026, 5, 25))

    assert len(rows) == 1
    assert rows[0][0] == date(2026, 5, 25)
    assert rows[0][3] == 11.0
