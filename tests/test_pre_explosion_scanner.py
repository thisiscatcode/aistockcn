from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.services import pre_explosion as pre_explosion_service
from pre_explosion_scanner import (
    SMOKE_POSITIVE_WINDOWS,
    classify_pattern,
    enrich_stock_features,
    scan_stock,
)


def _base_row(**overrides: object) -> pd.Series:
    row = {
        "close": 12.0,
        "volume": 10_000_000,
        "amount": 620_000_000.0,
        "turnover_ma5": 4.2,
        "bias20": 0.03,
        "close_to_high20": -0.04,
        "close_to_low20": 0.22,
        "max_pct_chg_20d": 6.2,
        "max_amount_ratio20_20d": 1.8,
        "pct_chg": -1.0,
        "pct_chg_5d": -0.01,
        "pct_chg_20d": 0.08,
        "amount_ratio20": 1.3,
        "near_limit_up": False,
    }
    row.update(overrides)
    return pd.Series(row)


def _synthetic_kline(code: str, window_start: str, *, low_price: bool = False) -> pd.DataFrame:
    start = pd.Timestamp(window_start) - pd.Timedelta(days=32)
    dates = pd.date_range(start, periods=52, freq="D")
    base_price = 3.2 if low_price else 10.0
    rows: list[dict[str, object]] = []
    for index, trade_date in enumerate(dates):
        close = base_price * (1 + min(index, 28) * 0.004)
        if trade_date >= pd.Timestamp(window_start):
            close = base_price * 1.11
        pct_chg = 0.4
        amount = 80_000_000.0 if low_price else 620_000_000.0
        turnover = 0.8 if low_price else 4.2
        if index == 22:
            pct_chg = 6.0 if not low_price else 4.8
            amount *= 1.9
        rows.append(
            {
                "date": trade_date,
                "code": code,
                "exchange": "sh" if code.startswith("6") else "sz",
                "open": close * 0.99,
                "high": close * 1.02,
                "low": close * 0.94,
                "close": close,
                "volume": 10_000_000,
                "amount": amount,
                "turnover": turnover,
                "pct_chg": pct_chg,
            }
        )
    return pd.DataFrame(rows)


def test_pre_explosion_rolling_features_are_calculated() -> None:
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=25, freq="D"),
            "close": range(1, 26),
            "high": range(2, 27),
            "low": range(0, 25),
            "amount": [100.0] * 25,
            "turnover": [1.0] * 25,
            "volume": [10_000] * 25,
            "pct_chg": [1.0] * 25,
        }
    )

    enriched = enrich_stock_features(frame)
    latest = enriched.iloc[-1]

    assert latest["ma5"] == 23.0
    assert latest["ma10"] == 20.5
    assert latest["high20"] == 26
    assert latest["low20"] == 5
    assert latest["pct_chg_5d"] == 0.25
    assert latest["amount_ratio20"] == 1.0


def test_platform_washout_classifies_as_watch_candidate() -> None:
    result = classify_pattern(_base_row())

    assert result is not None
    assert result["setup_type"] == "platform_washout"
    assert result["entry_state"] == "WATCH"
    assert "platform" in result["reason_tags"]


def test_low_price_reversal_classifies_cheap_base() -> None:
    result = classify_pattern(
        _base_row(
            close=3.42,
            amount=70_000_000.0,
            turnover_ma5=0.8,
            close_to_high20=-0.05,
            max_pct_chg_20d=4.5,
        )
    )

    assert result is not None
    assert result["setup_type"] == "low_price_reversal"
    assert "low_price" in result["reason_tags"]


def test_extended_candidate_is_not_early_watch() -> None:
    result = classify_pattern(_base_row(pct_chg_5d=0.32))

    assert result is not None
    assert result["entry_state"] == "EXTENDED"


def test_smoke_positive_codes_enter_synthetic_pre_breakout_windows() -> None:
    for code, (start, end) in SMOKE_POSITIVE_WINDOWS.items():
        frame = scan_stock(
            _synthetic_kline(code, start, low_price=(code == "600162")),
            {"code": code, "exchange": "sh" if code.startswith("6") else "sz", "name": code, "industry": "SMOKE"},
        )
        window = frame[
            frame["date"].between(pd.Timestamp(start), pd.Timestamp(end))
            & frame["entry_state"].ne("EXTENDED")
        ]

        assert not window.empty, code
        if code == "600162":
            assert "low_price_reversal" in set(window["setup_type"])
        else:
            assert "platform_washout" in set(window["setup_type"])


def test_pre_explosion_service_returns_empty_rows_when_artifact_missing(tmp_path: Path) -> None:
    settings = SimpleNamespace(quant_dir=tmp_path)

    with mock.patch.object(pre_explosion_service, "get_settings", return_value=settings):
        result = pre_explosion_service.get_pre_explosion_watchlist(limit=20)

    assert result["rows"] == 0
    assert result["watchlist"] == []
    assert result["error"]


def test_pre_explosion_service_reads_artifact_and_reason_tags(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "pre_explosion"
    artifact_dir.mkdir()
    pd.DataFrame(
        [
            {
                "date": "2026-06-04",
                "code": "003026",
                "exchange": "sz",
                "name": "中晶科技",
                "amount": 650_000_000.0,
                "pre_explosion_score": 88,
                "setup_type": "platform_washout",
                "entry_state": "WATCH",
                "reason_tags": "platform|near_20d_high",
            }
        ]
    ).to_parquet(artifact_dir / "watchlist_latest.parquet", index=False)
    (artifact_dir / "summary_latest.json").write_text(json.dumps({"latest_date": "2026-06-04"}), encoding="utf-8")
    settings = SimpleNamespace(quant_dir=tmp_path)

    with mock.patch.object(pre_explosion_service, "get_settings", return_value=settings):
        result = pre_explosion_service.get_pre_explosion_watchlist(limit=20)

    assert result["rows"] == 1
    assert result["latest_date"] == "2026-06-04"
    assert result["watchlist"][0]["reason_tags"] == ["platform", "near_20d_high"]
