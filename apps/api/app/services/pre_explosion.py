from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from app.config import get_settings
from app.serializers import records_to_json
from app.services.files import read_json


WATCHLIST_COLUMNS = [
    "date",
    "code",
    "exchange",
    "name",
    "industry",
    "close",
    "amount",
    "turnover",
    "pct_chg",
    "pre_explosion_score",
    "pattern_name",
    "setup_type",
    "entry_state",
    "reason_tags",
    "ma5",
    "ma10",
    "ma20",
    "high20",
    "low20",
    "high40",
    "low40",
    "pct_chg_5d",
    "pct_chg_20d",
    "bias20",
    "close_to_high20",
    "close_to_low20",
    "close_to_high40",
    "close_to_low40",
    "pct_from_40d_low_close",
    "turnover_ma5",
    "amount_ma20",
    "amount_ratio20",
    "max_pct_chg_20d",
    "max_amount_ratio20_20d",
    "platform_drawdown_10d",
    "near_limit_up",
]


def _artifact_dir() -> Path:
    return get_settings().quant_dir / "pre_explosion"


def _normalize_reason_tags(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, tuple):
        return [str(item) for item in value if str(item).strip()]
    if pd.isna(value):
        return []
    text = str(value).replace(",", "|")
    return [part.strip() for part in text.split("|") if part.strip()]


def _read_watchlist(path: Path, *, limit: int) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    frame = pd.read_parquet(path)
    if frame.empty:
        return []
    for column in WATCHLIST_COLUMNS:
        if column not in frame.columns:
            frame[column] = None
    frame = frame[WATCHLIST_COLUMNS].copy()
    state_order = {"WATCH": 0, "TRIGGER": 1, "EXTENDED": 2}
    frame["_state_order"] = frame["entry_state"].map(state_order).fillna(9)
    frame = frame.sort_values(
        ["_state_order", "pre_explosion_score", "amount"],
        ascending=[True, False, False],
        na_position="last",
    ).drop(columns=["_state_order"])
    if limit:
        frame = frame.head(limit)
    records = records_to_json(frame.to_dict(orient="records"))
    for row in records:
        row["reason_tags"] = _normalize_reason_tags(row.get("reason_tags"))
    return records


def get_pre_explosion_watchlist(*, limit: int = 500) -> dict[str, Any]:
    artifact_dir = _artifact_dir()
    latest_path = artifact_dir / "watchlist_latest.parquet"
    summary_path = artifact_dir / "summary_latest.json"
    summary = read_json(summary_path)
    error: str | None = None

    try:
        rows = _read_watchlist(latest_path, limit=limit)
    except Exception as exc:
        rows = []
        error = str(exc)

    if not latest_path.exists():
        error = error or f"{latest_path} does not exist"

    latest_date = summary.get("latest_date")
    if not latest_date:
        latest_date = max((row.get("date") for row in rows if row.get("date")), default=None)

    return {
        "rows": len(rows),
        "latest_date": latest_date,
        "watchlist": rows,
        "summary": summary,
        "error": error,
    }
