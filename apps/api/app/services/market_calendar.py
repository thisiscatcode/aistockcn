"""Expected daily signal dates from the exchange calendar and update schedule."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pandas as pd

from app.config import Settings, get_settings
from app.services.files import read_json, write_json_atomic


def cache_china_trade_dates(values: pd.Series) -> None:
    dates = pd.to_datetime(values, errors="coerce").dropna()
    if dates.empty:
        return
    settings = get_settings()
    write_json_atomic(settings.quant_dir / "reference" / "cn_trade_calendar.json", {
        "trade_dates": sorted({value.date().isoformat() for value in dates}),
        "source": "akshare.tool_trade_date_hist_sina",
        "updated_at": datetime.now(UTC).isoformat(),
    })


def expected_china_signal_date(settings: Settings | None = None, *, now: datetime | None = None) -> str | None:
    resolved = settings or get_settings()
    local = (now or datetime.now(UTC)).astimezone(ZoneInfo("Asia/Shanghai"))
    today = local.date().isoformat()
    update_time = datetime.strptime(getattr(resolved, "pipeline_auto_run_time", "18:00"), "%H:%M").time()
    schedule_zone = ZoneInfo(getattr(resolved, "pipeline_auto_run_timezone", "Asia/Shanghai"))
    scheduled = datetime.combine(local.date(), update_time, tzinfo=schedule_zone)
    update_due = local >= scheduled
    calendar = read_json(resolved.quant_dir / "reference" / "cn_trade_calendar.json")
    dates = sorted(calendar.get("trade_dates") or [])
    if dates and dates[0] <= today <= dates[-1]:
        eligible = [value for value in dates if value <= today and (value != today or update_due)]
        return eligible[-1] if eligible else None
    # A provider outage must not turn calendar days into assumed trading days.
    # Use the scheduler's last verified exchange date when a cache is unavailable.
    state = read_json(resolved.pipeline_auto_run_state_path)
    readiness = state.get("last_readiness") or {}
    expected = readiness.get("expected_trade_date")
    if expected and (expected < today or (expected == today and update_due)):
        return expected
    return None
