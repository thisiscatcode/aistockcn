"""Expected daily signal dates from the exchange calendar and update schedule."""

from __future__ import annotations

from datetime import UTC, datetime
import sys

import pandas as pd

from app.config import Settings, get_settings
from app.services.files import write_json_atomic

PROJECT_ROOT = get_settings().project_root
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from cn_signal_calendar import expected_signal_date


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
    return expected_signal_date(
        resolved.quant_dir, now=now,
        scheduled_time=getattr(resolved, "pipeline_auto_run_time", "18:00"),
        scheduled_timezone=getattr(resolved, "pipeline_auto_run_timezone", "Asia/Shanghai"),
        scheduler_state_path=resolved.pipeline_auto_run_state_path,
    )
