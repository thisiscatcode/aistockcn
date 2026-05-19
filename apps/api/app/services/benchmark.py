from __future__ import annotations

import contextlib
import io
from datetime import UTC, datetime, timedelta
from importlib import import_module
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa

from app.config import get_settings
from app.serializers import to_jsonable

BENCHMARK_CODE = "000300.SH"
BENCHMARK_SYMBOL = "000300"
BAOSTOCK_BENCHMARK_CODE = "sh.000300"
BENCHMARK_NAME = "沪深300"
AKSHARE_SOURCE = "akshare.index_zh_a_hist"
BAOSTOCK_SOURCE = "baostock.query_history_k_data_plus"
BENCHMARK_SOURCE = AKSHARE_SOURCE
BENCHMARK_DEFAULT_START_DATE = "20050101"

AKSHARE_INDEX_COLUMNS = {
    "日期": "date",
    "开盘": "open",
    "收盘": "close",
    "最高": "high",
    "最低": "low",
    "成交量": "volume",
    "成交额": "amount",
    "振幅": "amplitude",
    "涨跌幅": "pct_chg",
    "涨跌额": "change",
    "换手率": "turnover",
}

BAOSTOCK_INDEX_COLUMNS = {
    "pctChg": "pct_chg",
    "turn": "turnover",
}

NUMERIC_COLUMNS = [
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "amplitude",
    "pct_chg",
    "change",
    "turnover",
]


def benchmark_history_path() -> Path:
    return get_settings().quant_dir / "index" / f"{BENCHMARK_CODE}.parquet"


def _safe_read_parquet(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_parquet(path)
    except (pa.ArrowException, OSError, ValueError):
        return pd.DataFrame()


def _compact_date(value: str | None) -> str | None:
    if value is None or not str(value).strip():
        return None
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        raise ValueError(f"Invalid date: {value}")
    return parsed.strftime("%Y%m%d")


def _iso_date(value: Any) -> str | None:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date().isoformat()


def _default_refresh_start(existing: pd.DataFrame) -> str:
    if existing.empty or "date" not in existing.columns:
        return BENCHMARK_DEFAULT_START_DATE

    latest = pd.to_datetime(existing["date"], errors="coerce").max()
    if pd.isna(latest):
        return BENCHMARK_DEFAULT_START_DATE
    return (latest - timedelta(days=10)).strftime("%Y%m%d")


def _load_akshare() -> Any:
    try:
        return import_module("akshare")
    except ImportError as exc:  # pragma: no cover - depends on runtime image
        raise RuntimeError("akshare dependency is unavailable") from exc


def _load_baostock() -> Any:
    try:
        return import_module("baostock")
    except ImportError as exc:  # pragma: no cover - depends on runtime image
        raise RuntimeError("baostock dependency is unavailable") from exc


def _normalize_index_history(frame: pd.DataFrame, *, source: str) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()

    renamed = frame.rename(
        columns={
            **AKSHARE_INDEX_COLUMNS,
            **BAOSTOCK_INDEX_COLUMNS,
            "trade_date": "date",
            "close_price": "close",
        }
    )
    if "date" not in renamed.columns or "close" not in renamed.columns:
        raise ValueError("Benchmark index history must include date and close columns.")

    selected_columns = ["date", *[column for column in NUMERIC_COLUMNS if column in renamed.columns]]
    normalized = renamed[selected_columns].copy()
    normalized["date"] = pd.to_datetime(normalized["date"], errors="coerce").dt.normalize()
    for column in NUMERIC_COLUMNS:
        if column in normalized.columns:
            normalized[column] = pd.to_numeric(normalized[column], errors="coerce")

    normalized = normalized.dropna(subset=["date", "close"])
    if normalized.empty:
        return pd.DataFrame()

    normalized["code"] = BENCHMARK_CODE
    normalized["name"] = BENCHMARK_NAME
    normalized["source"] = source
    normalized["updated_at"] = datetime.now(tz=UTC).replace(microsecond=0).isoformat()
    ordered_columns = ["date", "code", "name", *[column for column in NUMERIC_COLUMNS if column in normalized.columns], "source", "updated_at"]
    return normalized[ordered_columns].sort_values("date").drop_duplicates(subset=["date"], keep="last").reset_index(drop=True)


def normalize_akshare_index_history(frame: pd.DataFrame) -> pd.DataFrame:
    return _normalize_index_history(frame, source=AKSHARE_SOURCE)


def normalize_baostock_index_history(frame: pd.DataFrame) -> pd.DataFrame:
    return _normalize_index_history(frame, source=BAOSTOCK_SOURCE)


def merge_benchmark_history(existing: pd.DataFrame, fresh: pd.DataFrame) -> pd.DataFrame:
    frames = [frame for frame in [existing, fresh] if not frame.empty]
    if not frames:
        return pd.DataFrame()

    merged = pd.concat(frames, ignore_index=True, sort=False)
    merged["date"] = pd.to_datetime(merged["date"], errors="coerce").dt.normalize()
    merged = merged.dropna(subset=["date", "close"])
    merged = merged.sort_values("date").drop_duplicates(subset=["date"], keep="last")
    return merged.reset_index(drop=True)


def get_benchmark_history_status() -> dict[str, Any]:
    path = benchmark_history_path()
    frame = _safe_read_parquet(path)
    if frame.empty:
        return {
            "code": BENCHMARK_CODE,
            "name": BENCHMARK_NAME,
            "source": BENCHMARK_SOURCE,
            "path": str(path),
            "exists": path.exists(),
            "rows": 0,
            "first_date": None,
            "latest_date": None,
            "updated_at": None,
        }

    dates = pd.to_datetime(frame.get("date"), errors="coerce")
    updated_at = frame["updated_at"].dropna().iloc[-1] if "updated_at" in frame.columns and frame["updated_at"].dropna().size else None
    sources = sorted(str(source) for source in frame["source"].dropna().unique()) if "source" in frame.columns else []
    return {
        "code": BENCHMARK_CODE,
        "name": BENCHMARK_NAME,
        "source": sources[-1] if sources else BENCHMARK_SOURCE,
        "sources": sources,
        "path": str(path),
        "exists": True,
        "rows": int(len(frame)),
        "first_date": _iso_date(dates.min()),
        "latest_date": _iso_date(dates.max()),
        "updated_at": to_jsonable(updated_at),
    }


def _fetch_from_akshare(start_date: str, end_date: str) -> pd.DataFrame:
    ak = _load_akshare()
    raw = ak.index_zh_a_hist(
        symbol=BENCHMARK_SYMBOL,
        period="daily",
        start_date=start_date,
        end_date=end_date,
    )
    return normalize_akshare_index_history(raw)


def _baostock_result_to_frame(result: Any) -> pd.DataFrame:
    if getattr(result, "error_code", None) != "0":
        raise RuntimeError(f"baostock query failed: {getattr(result, 'error_msg', 'unknown error')}")
    fields = list(getattr(result, "fields", []) or [])
    rows: list[list[str]] = []
    while result.next():
        rows.append(result.get_row_data())
    return pd.DataFrame(rows, columns=fields or None)


def _fetch_from_baostock(start_date: str, end_date: str) -> pd.DataFrame:
    bs = _load_baostock()
    with contextlib.redirect_stdout(io.StringIO()):
        login_result = bs.login()
    if getattr(login_result, "error_code", None) != "0":
        raise RuntimeError(f"baostock login failed: {getattr(login_result, 'error_msg', 'unknown error')}")
    try:
        result = bs.query_history_k_data_plus(
            BAOSTOCK_BENCHMARK_CODE,
            "date,code,open,high,low,close,preclose,volume,amount,pctChg",
            start_date=pd.to_datetime(start_date, format="%Y%m%d").date().isoformat(),
            end_date=pd.to_datetime(end_date, format="%Y%m%d").date().isoformat(),
            frequency="d",
            adjustflag="3",
        )
        return normalize_baostock_index_history(_baostock_result_to_frame(result))
    finally:
        with contextlib.redirect_stdout(io.StringIO()):
            bs.logout()


def refresh_benchmark_history(
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    path = benchmark_history_path()
    existing = pd.DataFrame() if overwrite else _safe_read_parquet(path)
    fetch_start = _compact_date(start_date) or _default_refresh_start(existing)
    fetch_end = _compact_date(end_date) or datetime.now(tz=UTC).strftime("%Y%m%d")

    primary_error: str | None = None
    try:
        fresh = _fetch_from_akshare(fetch_start, fetch_end)
    except Exception as exc:
        primary_error = str(exc)
        fresh = _fetch_from_baostock(fetch_start, fetch_end)

    if fresh.empty:
        raise RuntimeError(f"No benchmark history returned for {BENCHMARK_CODE} between {fetch_start} and {fetch_end}.")

    merged = fresh if overwrite else merge_benchmark_history(existing, fresh)
    path.parent.mkdir(parents=True, exist_ok=True)
    merged.to_parquet(path, index=False)

    status = get_benchmark_history_status()
    status.update(
        {
            "refresh": {
                "requested_start_date": fetch_start,
                "requested_end_date": fetch_end,
                "fetched_rows": int(len(fresh)),
                "overwrite": overwrite,
                "source": str(fresh["source"].dropna().iloc[-1]) if "source" in fresh.columns and fresh["source"].dropna().size else None,
                "primary_source_error": primary_error,
            }
        }
    )
    return status
