"""Shared exchange-calendar deadline for API status and the paper executor."""

from datetime import UTC, datetime
import json
from pathlib import Path
from zoneinfo import ZoneInfo


def expected_signal_date(
    quant_dir: Path, *, now: datetime | None = None,
    scheduled_time: str = "18:00", scheduled_timezone: str = "Asia/Shanghai",
    scheduler_state_path: Path | None = None,
) -> str | None:
    local = (now or datetime.now(UTC)).astimezone(ZoneInfo("Asia/Shanghai"))
    today = local.date().isoformat()
    deadline = datetime.combine(
        local.date(), datetime.strptime(scheduled_time, "%H:%M").time(),
        tzinfo=ZoneInfo(scheduled_timezone),
    )
    update_due = local >= deadline
    path = quant_dir / "reference" / "cn_trade_calendar.json"
    calendar = json.loads(path.read_text()) if path.exists() else {}
    dates = sorted(calendar.get("trade_dates") or [])
    if dates and dates[0] <= today <= dates[-1]:
        eligible = [d for d in dates if d < today or (d == today and update_due)]
        return eligible[-1] if eligible else None
    path = scheduler_state_path or quant_dir.parent / "run" / "pipeline_auto_run_state.json"
    state = json.loads(path.read_text()) if path.exists() else {}
    expected = (state.get("last_readiness") or {}).get("expected_trade_date")
    if expected and (expected < today or (expected == today and update_due)):
        return expected
    return None
