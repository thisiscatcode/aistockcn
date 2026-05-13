from __future__ import annotations

import contextlib
import io
import multiprocessing as mp
import queue
from datetime import date
from typing import Any

import pandas as pd

try:
    import akshare as ak
except ImportError:  # pragma: no cover - depends on image build
    ak = None

try:
    import baostock as bs
except ImportError:  # pragma: no cover - depends on image build
    bs = None

BAOSTOCK_PROBE_CODE = "sh.600000"
AKSHARE_PROBE_SYMBOL = "600000"
PROVIDER_PROBE_TIMEOUT_SECONDS = 30.0


class ProviderProbeTimeoutError(TimeoutError):
    pass


def _to_date_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value[:10]
    if isinstance(value, date):
        return value.isoformat()
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date().isoformat()


def _quiet_baostock_login() -> None:
    if bs is None:
        raise RuntimeError("baostock dependency is unavailable")
    with contextlib.redirect_stdout(io.StringIO()):
        login_result = bs.login()
    if getattr(login_result, "error_code", None) != "0":
        raise RuntimeError(f"baostock login failed: {getattr(login_result, 'error_msg', 'unknown error')}")


def _quiet_baostock_logout() -> None:
    if bs is None:
        return
    with contextlib.redirect_stdout(io.StringIO()):
        bs.logout()


def _baostock_result_to_df(result: Any) -> pd.DataFrame:
    if getattr(result, "error_code", None) != "0":
        raise RuntimeError(f"baostock query failed: {getattr(result, 'error_msg', 'unknown error')}")
    fields = list(getattr(result, "fields", []) or [])
    rows: list[list[str]] = []
    while result.next():
        rows.append(result.get_row_data())
    if not rows:
        return pd.DataFrame(columns=fields)
    return pd.DataFrame(rows, columns=fields or None)


def _trade_calendar_status(local_date: str) -> tuple[str | None, bool]:
    if ak is None:
        raise RuntimeError("akshare dependency is unavailable")
    end_ts = pd.to_datetime(local_date, format="%Y-%m-%d")
    start_ts = end_ts - pd.Timedelta(days=30)
    df = ak.tool_trade_date_hist_sina()
    if df.empty or "trade_date" not in df.columns:
        return None, False
    trade_dates = pd.to_datetime(df["trade_date"], errors="coerce").dropna()
    trade_dates = trade_dates[(trade_dates >= start_ts) & (trade_dates <= end_ts)]
    if trade_dates.empty:
        return None, False
    latest_trade_date = trade_dates.max().date().isoformat()
    return latest_trade_date, latest_trade_date == local_date


def _probe_baostock_daily_kline(trade_date: str) -> str | None:
    if bs is None:
        raise RuntimeError("baostock dependency is unavailable")
    df = _baostock_result_to_df(
        bs.query_history_k_data_plus(
            BAOSTOCK_PROBE_CODE,
            "date,code,close",
            start_date=trade_date,
            end_date=trade_date,
            frequency="d",
            adjustflag="2",
        )
    )
    if df.empty:
        return None
    return _to_date_text(df.iloc[-1]["date"])


def _probe_baostock_all_stock(trade_date: str) -> dict[str, Any]:
    if bs is None:
        raise RuntimeError("baostock dependency is unavailable")
    df = _baostock_result_to_df(bs.query_all_stock(trade_date))
    row_count = int(len(df))
    return {
        "ready": row_count > 0,
        "latest_date": trade_date if row_count > 0 else None,
        "row_count": row_count,
    }


def _probe_akshare_market_cap() -> str | None:
    if ak is None:
        raise RuntimeError("akshare dependency is unavailable")
    df = ak.stock_value_em(symbol=AKSHARE_PROBE_SYMBOL)
    if df.empty or "数据日期" not in df.columns:
        return None
    latest_value = pd.to_datetime(df["数据日期"], errors="coerce").max()
    if pd.isna(latest_value):
        return None
    return latest_value.date().isoformat()


def _probe_baostock_readiness(local_date: str) -> dict[str, Any]:
    expected_trade_date, is_trading_day = _trade_calendar_status(local_date)
    payload: dict[str, Any] = {
        "expected_trade_date": expected_trade_date,
        "is_trading_day": bool(is_trading_day),
        "daily_kline_date": None,
        "all_stock_date": None,
        "all_stock_row_count": 0,
        "ready": False,
    }
    if not is_trading_day or expected_trade_date is None:
        return payload

    _quiet_baostock_login()
    try:
        daily_kline_date = _probe_baostock_daily_kline(expected_trade_date)
        all_stock_probe = _probe_baostock_all_stock(expected_trade_date)
        payload.update(
            {
                "daily_kline_date": daily_kline_date,
                "all_stock_date": all_stock_probe["latest_date"],
                "all_stock_row_count": all_stock_probe["row_count"],
                "ready": daily_kline_date == expected_trade_date and bool(all_stock_probe["ready"]),
            }
        )
        return payload
    finally:
        _quiet_baostock_logout()


def _provider_probe_entry(result_queue: Any, func: Any, args: tuple[Any, ...]) -> None:
    try:
        result_queue.put(("ok", func(*args)))
    except Exception as exc:
        result_queue.put(("error", str(exc)))


def _run_provider_probe(func: Any, *args: Any, timeout_seconds: float = PROVIDER_PROBE_TIMEOUT_SECONDS) -> Any:
    method = "fork" if "fork" in mp.get_all_start_methods() else "spawn"
    context = mp.get_context(method)
    result_queue = context.Queue(maxsize=1)
    process = context.Process(target=_provider_probe_entry, args=(result_queue, func, args), daemon=True)
    process.start()
    process.join(timeout_seconds)
    if process.is_alive():
        process.terminate()
        process.join(timeout=2)
        raise ProviderProbeTimeoutError(f"provider probe timed out after {timeout_seconds:g}s")

    try:
        status, payload = result_queue.get_nowait()
    except queue.Empty as exc:
        raise RuntimeError("provider probe exited without a result") from exc

    if status == "error":
        raise RuntimeError(str(payload))
    return payload


def get_china_market_data_readiness(*, local_date: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "local_date": local_date,
        "expected_trade_date": None,
        "is_trading_day": False,
        "ready": False,
        "pending_sources": [],
        "baostock": {
            "probe_code": BAOSTOCK_PROBE_CODE,
            "daily_kline_date": None,
            "all_stock_date": None,
            "all_stock_row_count": 0,
            "ready": False,
            "error": None,
        },
        "akshare": {
            "probe_symbol": AKSHARE_PROBE_SYMBOL,
            "market_cap_date": None,
            "ready": False,
            "error": None,
        },
        "reason": None,
    }

    if bs is None or ak is None:
        result["reason"] = "data_source_dependencies_unavailable"
        if bs is None:
            result["baostock"]["error"] = "baostock dependency is unavailable"
        if ak is None:
            result["akshare"]["error"] = "akshare dependency is unavailable"
        return result

    try:
        baostock_probe = _run_provider_probe(_probe_baostock_readiness, local_date)
        expected_trade_date = baostock_probe["expected_trade_date"]
        result["expected_trade_date"] = expected_trade_date
        result["is_trading_day"] = bool(baostock_probe["is_trading_day"])
        result["baostock"]["daily_kline_date"] = baostock_probe["daily_kline_date"]
        result["baostock"]["all_stock_date"] = baostock_probe["all_stock_date"]
        result["baostock"]["all_stock_row_count"] = baostock_probe["all_stock_row_count"]
        result["baostock"]["ready"] = bool(baostock_probe["ready"])
        if not result["is_trading_day"]:
            result["reason"] = "non_trading_day"
            return result
    except ProviderProbeTimeoutError as exc:
        result["reason"] = "baostock_probe_timeout"
        result["baostock"]["error"] = str(exc)
        return result
    except Exception as exc:
        error_text = str(exc)
        result["reason"] = (
            "baostock_login_failed"
            if error_text.startswith("baostock login failed")
            else "baostock_probe_failed"
        )
        result["baostock"]["error"] = str(exc)
        return result

    try:
        market_cap_date = _run_provider_probe(_probe_akshare_market_cap)
        result["akshare"]["market_cap_date"] = market_cap_date
        result["akshare"]["ready"] = market_cap_date == expected_trade_date
    except ProviderProbeTimeoutError as exc:
        result["reason"] = "akshare_probe_timeout"
        result["akshare"]["error"] = str(exc)
        return result
    except Exception as exc:
        result["reason"] = "akshare_probe_failed"
        result["akshare"]["error"] = str(exc)
        return result

    pending_sources: list[str] = []
    if result["baostock"]["daily_kline_date"] != expected_trade_date:
        pending_sources.append("baostock_daily_kline")
    if result["baostock"]["all_stock_date"] != expected_trade_date:
        pending_sources.append("baostock_all_stock")
    if result["akshare"]["market_cap_date"] != expected_trade_date:
        pending_sources.append("akshare_market_cap")

    result["pending_sources"] = pending_sources
    result["ready"] = not pending_sources
    result["reason"] = None if result["ready"] else "waiting_for_market_data"
    return result
