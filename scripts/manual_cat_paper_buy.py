#!/usr/bin/env python3
"""One-off Cat indicator paper buy runner.

This script is intentionally manual and idempotent for a single trade day. It
does not change the recurring top-picks paper trading daemon.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from execution_model import (  # noqa: E402
    buy_liquidity_skip_reason,
    execution_model_snapshot,
    execution_model_with_limit_bps,
    near_price_limit,
    previous_close_from_row,
)
from paper_trade_futu import (  # noqa: E402
    ACTIVE_TRADING_WINDOWS,
    BEIJING_TZ,
    DEFAULT_AGENT_ID,
    DEFAULT_AGENT_ID_HEADER,
    DEFAULT_AGENT_KEY,
    DEFAULT_AGENT_KEY_HEADER,
    DEFAULT_GATEWAY_BASE_URL,
    DEFAULT_MARKET,
    DEFAULT_SCORES_PATH,
    DEFAULT_STATE_DIR,
    GatewayClient,
    GatewayError,
    SyncConfig,
    build_marketable_limit_price,
    get_sina_latest_price,
    is_active_order,
    json_default,
    normalize_orders,
    normalize_symbol,
    now_iso,
    to_float,
    write_json,
)

DEFAULT_WATCHLIST_PATH = ROOT / "quant_data/pre_explosion/watchlist_latest.parquet"
DEFAULT_ENV_PATH = ROOT / "run/panel.env"
DEFAULT_OUTPUT_DIR = ROOT / "run"
DEFAULT_QUANTITY = 100
DEFAULT_LIMIT = 10
DEFAULT_BUY_LIMIT_BPS = 50.0
MANUAL_TAG_PREFIX = "manual_cat"
FAILED_OR_CANCELLED_STATUSES = {
    "CANCELLED",
    "CANCELLED_ALL",
    "CANCELLED_PART",
    "CANCELLED_PART_ALL",
    "DELETED",
    "DISABLED",
    "EXPIRED",
    "FAILED",
    "REJECTED",
    "SUBMIT_FAILED",
}

CAT_EARLY_MAX_DAILY_GAIN_PCT = 2.0
CAT_EARLY_MAX_5D_GAIN = 0.04
CAT_EARLY_MAX_20D_GAIN = 0.10
CAT_EARLY_MIN_20D_GAIN = -0.20
CAT_EARLY_MAX_BIAS20 = 0.06
CAT_EARLY_MAX_FROM_40D_LOW = 0.18
CAT_EARLY_MAX_FROM_20D_LOW = 0.16
CAT_EARLY_MIN_TO_20D_HIGH = -0.16
CAT_EARLY_MAX_TO_20D_HIGH = -0.03


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


def parse_optional_int(value: Any) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    return int(text)


def parse_float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def normalized_code(value: Any) -> str:
    return normalize_symbol(value).zfill(6)


def finite_number(value: Any) -> float | None:
    if value in (None, "", "NaN", "nan"):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def first_present(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and value == "":
            continue
        if isinstance(value, float) and value != value:
            continue
        return value
    return None


def first_tags(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        try:
            if not isinstance(value, str) and len(value) == 0:
                continue
        except TypeError:
            pass
        return value
    return None


def sort_number(value: Any) -> float:
    number = finite_number(value)
    return number if number is not None else float("-inf")


def tags_from_value(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return set()
        if text.startswith("["):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = [text]
            return tags_from_value(parsed)
        return {part.strip() for part in re.split(r"[|,]", text) if part.strip()}
    try:
        return {str(item).strip() for item in list(value) if str(item).strip()}
    except TypeError:
        return {str(value).strip()} if str(value).strip() else set()


def exceeds(value: Any, maximum: float) -> bool:
    number = finite_number(value)
    return number is not None and number > maximum


def below(value: Any, minimum: float) -> bool:
    number = finite_number(value)
    return number is not None and number < minimum


def is_cat_early_candidate(row: dict[str, Any]) -> bool:
    if str(row.get("entry_state") or row.get("pre_explosion_entry_state") or "").strip() != "WATCH":
        return False
    if exceeds(row.get("pct_chg"), CAT_EARLY_MAX_DAILY_GAIN_PCT):
        return False
    if exceeds(row.get("pct_chg_5d"), CAT_EARLY_MAX_5D_GAIN):
        return False
    if exceeds(row.get("pct_chg_20d"), CAT_EARLY_MAX_20D_GAIN):
        return False
    if below(row.get("pct_chg_20d"), CAT_EARLY_MIN_20D_GAIN):
        return False
    if exceeds(row.get("bias20"), CAT_EARLY_MAX_BIAS20):
        return False
    if exceeds(row.get("pct_from_40d_low_close"), CAT_EARLY_MAX_FROM_40D_LOW):
        return False
    if exceeds(row.get("close_to_low20"), CAT_EARLY_MAX_FROM_20D_LOW):
        return False
    if below(row.get("close_to_high20"), CAT_EARLY_MIN_TO_20D_HIGH):
        return False
    return not exceeds(row.get("close_to_high20"), CAT_EARLY_MAX_TO_20D_HIGH)


def cat_early_rank_score(row: dict[str, Any]) -> float:
    tags = tags_from_value(first_tags(row.get("reason_tags"), row.get("pre_explosion_reason_tags")))
    score = finite_number(row.get("pre_explosion_score")) or 0.0
    if tags.intersection({"washout", "pre_breakout_rest"}):
        score += 25.0
    if tags.intersection({"short_structure_ok", "base_intact"}):
        score += 8.0
    if tags.intersection({"within_platform", "range_recovery"}):
        score += 8.0
    if tags.intersection({"near_20d_high", "near_range_high"}):
        score -= 5.0

    daily_gain = finite_number(row.get("pct_chg"))
    if daily_gain is not None:
        if -5.0 <= daily_gain <= 0.0:
            score += 10.0
        elif 0.0 < daily_gain <= 1.5:
            score += 4.0
        elif daily_gain > 2.0:
            score -= 10.0

    score -= max(finite_number(row.get("pct_chg_5d")) or 0.0, 0.0) * 130.0
    score -= max(finite_number(row.get("pct_chg_20d")) or 0.0, 0.0) * 90.0
    score -= max(finite_number(row.get("bias20")) or 0.0, 0.0) * 130.0
    score -= max(finite_number(row.get("pct_from_40d_low_close")) or 0.0, 0.0) * 80.0
    score -= max(finite_number(row.get("close_to_low20")) or 0.0, 0.0) * 35.0

    close_to_high20 = finite_number(row.get("close_to_high20"))
    if close_to_high20 is not None:
        if -0.12 <= close_to_high20 <= -0.03:
            score += 8.0
        elif close_to_high20 > -0.02:
            score -= 8.0
        elif close_to_high20 < -0.18:
            score -= 6.0
    return score


def normalize_pick(row: dict[str, Any], rank: int | None = None) -> dict[str, Any]:
    code = normalized_code(row.get("code") or row.get("symbol"))
    pick = {
        **row,
        "rank": int(rank if rank is not None else row.get("rank") or 0),
        "code": code,
        "symbol": code,
        "exchange": str(row.get("exchange") or "").strip().lower(),
        "name": str(row.get("name") or "").strip(),
        "close": finite_number(row.get("close")),
        "amount": finite_number(first_present(row.get("amount"), row.get("pre_explosion_amount"))),
        "pct_chg": finite_number(first_present(row.get("pct_chg"), row.get("pre_explosion_pct_chg"))),
        "pre_explosion_score": finite_number(first_present(row.get("pre_explosion_score"), row.get("score"))),
        "early_score": finite_number(row.get("early_score")),
        "reason_tags": sorted(tags_from_value(first_tags(row.get("reason_tags"), row.get("tags"), row.get("pre_explosion_reason_tags")))),
    }
    if pick["early_score"] is None:
        pick["early_score"] = cat_early_rank_score(pick)
    return pick


def load_picks_from_file(path: Path, limit: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_picks = payload.get("picks") if isinstance(payload, dict) else payload
    if not isinstance(raw_picks, list):
        raise RuntimeError(f"{path} does not contain a picks list")
    picks = [normalize_pick(dict(row), idx + 1) for idx, row in enumerate(raw_picks[:limit])]
    return picks, dict(payload) if isinstance(payload, dict) else {"source": str(path)}


def load_picks_from_watchlist(path: Path, limit: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    frame = pd.read_parquet(path)
    rows = [dict(row) for row in frame.to_dict(orient="records")]
    candidates = [normalize_pick(row) for row in rows if is_cat_early_candidate(row)]
    candidates.sort(
        key=lambda row: (
            -sort_number(row.get("early_score")),
            -sort_number(row.get("pre_explosion_score")),
            f"{row.get('code')}-{row.get('exchange')}",
        )
    )
    picks = [normalize_pick(row, idx + 1) for idx, row in enumerate(candidates[:limit])]
    meta = {
        "source": str(path),
        "candidate_count": len(candidates),
        "latest_date": str(frame["date"].max()) if "date" in frame.columns and not frame.empty else None,
    }
    return picks, meta


def output_path_for(args: argparse.Namespace, trade_day: str) -> Path:
    if args.output_path:
        return Path(args.output_path)
    timestamp = datetime.now(BEIJING_TZ).strftime("%Y%m%d_%H%M%S")
    return DEFAULT_OUTPUT_DIR / f"manual_cat_paper_buy_{trade_day}_{timestamp}.json"


def next_trading_window_start(now: datetime) -> datetime | None:
    if now.weekday() >= 5:
        return None
    for start, end in ACTIVE_TRADING_WINDOWS:
        start_dt = datetime.combine(now.date(), start, tzinfo=BEIJING_TZ)
        end_dt = datetime.combine(now.date(), end, tzinfo=BEIJING_TZ)
        if now <= end_dt:
            return max(now, start_dt)
    return None


def wait_for_trading_window(output_path: Path, payload: dict[str, Any], poll_seconds: int) -> bool:
    while True:
        now = datetime.now(BEIJING_TZ)
        target = next_trading_window_start(now)
        if target is None:
            payload.update({"status": "skipped", "skip_reason": "NO_TRADING_WINDOW_LEFT_TODAY", "updated_at": now_iso()})
            write_json(output_path, payload)
            return False
        if target <= now + timedelta(seconds=1):
            return True
        payload.update(
            {
                "status": "scheduled",
                "scheduled_for": target.isoformat(),
                "seconds_until_window": int((target - now).total_seconds()),
                "updated_at": now_iso(),
            }
        )
        write_json(output_path, payload)
        time.sleep(min(max(int(poll_seconds), 5), max(int((target - now).total_seconds()), 5)))


def build_client(args: argparse.Namespace, execution_model: Any) -> GatewayClient:
    gateway_base_url = args.gateway_base_url or os.getenv("FUTU_GATEWAY_BASE_URL") or DEFAULT_GATEWAY_BASE_URL
    config = SyncConfig(
        scores_path=Path(DEFAULT_SCORES_PATH),
        state_dir=Path(DEFAULT_STATE_DIR),
        gateway_base_url=str(gateway_base_url).strip() or DEFAULT_GATEWAY_BASE_URL,
        market=(args.market or os.getenv("FUTU_GATEWAY_MARKET") or DEFAULT_MARKET).strip().upper(),
        agent_id=(args.agent_id or os.getenv("FUTU_GATEWAY_AGENT_ID") or DEFAULT_AGENT_ID).strip(),
        agent_key=(args.agent_key or os.getenv("FUTU_GATEWAY_AGENT_KEY") or DEFAULT_AGENT_KEY).strip(),
        agent_id_header=(os.getenv("FUTU_GATEWAY_AGENT_ID_HEADER") or DEFAULT_AGENT_ID_HEADER).strip(),
        agent_key_header=(os.getenv("FUTU_GATEWAY_AGENT_KEY_HEADER") or DEFAULT_AGENT_KEY_HEADER).strip(),
        account_id=parse_optional_int(args.account_id if args.account_id is not None else os.getenv("FUTU_GATEWAY_ACCOUNT_ID")),
        top_k=DEFAULT_LIMIT,
        min_score=0.0,
        lot_size=DEFAULT_QUANTITY,
        cash_buffer_pct=0.0,
        budget_total=None,
        max_buy_order_qty=0,
        max_sell_order_qty=0,
        cancel_open_orders=False,
        sync_existing_orders=True,
        force=False,
        dry_run=bool(args.dry_run),
        execution_model=execution_model,
    )
    return GatewayClient(config)


def existing_manual_symbols(orders: list[dict[str, Any]], trade_day: str) -> set[str]:
    marker = f"{MANUAL_TAG_PREFIX}_{trade_day}"
    symbols: set[str] = set()
    for order in normalize_orders(orders):
        remark = str(order.get("remark") or "")
        if marker not in remark:
            continue
        status = str(order.get("order_status") or "").upper()
        if status in FAILED_OR_CANCELLED_STATUSES:
            continue
        symbol = normalized_code(order.get("symbol"))
        if symbol:
            symbols.add(symbol)
    return symbols


def place_manual_orders(
    *,
    client: GatewayClient,
    picks: list[dict[str, Any]],
    quantity: int,
    trade_day: str,
    execution_model: Any,
    dry_run: bool,
) -> list[dict[str, Any]]:
    existing = existing_manual_symbols(client.get_agent_orders(), trade_day)
    results: list[dict[str, Any]] = []
    for pick in picks:
        symbol = normalized_code(pick.get("code"))
        result: dict[str, Any] = {
            "rank": pick.get("rank"),
            "symbol": symbol,
            "code": symbol,
            "exchange": pick.get("exchange"),
            "name": pick.get("name"),
            "quantity": quantity,
            "side": "BUY",
            "cat_score": pick.get("pre_explosion_score"),
            "cat_early_score": pick.get("early_score"),
        }
        if not symbol:
            result.update({"status": "skipped", "skip_reason": "MISSING_SYMBOL"})
            results.append(result)
            continue
        if symbol in existing:
            result.update({"status": "skipped", "skip_reason": "DUPLICATE_MANUAL_CAT_ORDER_TODAY"})
            results.append(result)
            continue
        try:
            latest_price = get_sina_latest_price(symbol, pick.get("exchange"))
            limit_price = build_marketable_limit_price(latest_price, "BUY", execution_model)
            previous_close = previous_close_from_row(pick)
            order_notional = quantity * limit_price
            result.update(
                {
                    "latest_price": latest_price,
                    "limit_price": limit_price,
                    "previous_close": previous_close,
                    "estimated_notional": order_notional,
                }
            )
            if near_price_limit(
                side="BUY",
                price=latest_price,
                previous_close=previous_close,
                symbol=symbol,
                name=pick.get("name"),
                model=execution_model,
            ):
                result.update({"status": "skipped", "skip_reason": "SKIP_NEAR_LIMIT_UP"})
                results.append(result)
                continue
            liquidity_reason = buy_liquidity_skip_reason(
                amount=pick.get("amount"),
                order_notional=order_notional,
                model=execution_model,
            )
            if liquidity_reason:
                result.update({"status": "skipped", "skip_reason": liquidity_reason})
                results.append(result)
                continue
            remark = f"{MANUAL_TAG_PREFIX}_{trade_day}_r{pick.get('rank')}_{symbol}"
            if dry_run:
                result.update({"status": "dry_run", "remark": remark})
            else:
                order = client.place_order(
                    symbol=symbol,
                    side="BUY",
                    quantity=quantity,
                    price=limit_price,
                    remark=remark,
                )
                result.update({"status": "submitted", "remark": remark, "order": order})
                existing.add(symbol)
                time.sleep(2.2)
        except Exception as exc:  # noqa: BLE001 - result JSON should retain all per-symbol failures.
            result.update({"status": "error", "error": str(exc)})
        results.append(result)
    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manual one-off Cat top-N paper buy runner.")
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_PATH))
    parser.add_argument("--picks-file", default="")
    parser.add_argument("--watchlist-path", default=str(DEFAULT_WATCHLIST_PATH))
    parser.add_argument("--output-path", default="")
    parser.add_argument("--gateway-base-url", default="")
    parser.add_argument("--market", default="")
    parser.add_argument("--agent-id", default="")
    parser.add_argument("--agent-key", default="")
    parser.add_argument("--account-id", default=None)
    parser.add_argument("--quantity", type=int, default=DEFAULT_QUANTITY)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--buy-limit-bps", type=float, default=None)
    parser.add_argument("--wait-until-open", action="store_true")
    parser.add_argument("--poll-seconds", type=int, default=60)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-live-gateway", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_env_file(Path(args.env_file))
    limit = max(int(args.limit), 1)
    quantity = max(int(args.quantity), 1)
    trade_day = datetime.now(BEIJING_TZ).strftime("%Y%m%d")
    output_path = output_path_for(args, trade_day)
    execution_model = execution_model_with_limit_bps(
        buy_limit_bps=args.buy_limit_bps if args.buy_limit_bps is not None else parse_float_env("PAPER_TRADING_BUY_LIMIT_BPS", DEFAULT_BUY_LIMIT_BPS),
        sell_limit_bps=parse_float_env("PAPER_TRADING_SELL_LIMIT_BPS", DEFAULT_BUY_LIMIT_BPS),
    )

    if args.picks_file:
        picks, pick_meta = load_picks_from_file(Path(args.picks_file), limit)
    else:
        picks, pick_meta = load_picks_from_watchlist(Path(args.watchlist_path), limit)
    if not picks:
        raise RuntimeError("no Cat picks available")

    client = build_client(args, execution_model)
    health = client.health()
    if health.get("simulate_only") is not True and not args.allow_live_gateway:
        raise RuntimeError("gateway is not simulate_only=true; refusing manual Cat paper buy")

    payload: dict[str, Any] = {
        "status": "planned",
        "generated_at": now_iso(),
        "trade_day": trade_day,
        "quantity": quantity,
        "limit": limit,
        "dry_run": bool(args.dry_run),
        "gateway": {
            "base_url": client.base_url,
            "market": client.market,
            "simulate_only": health.get("simulate_only"),
        },
        "execution_model": execution_model_snapshot(execution_model),
        "pick_meta": pick_meta,
        "picks": picks,
    }
    write_json(output_path, payload)

    if args.wait_until_open and not wait_for_trading_window(output_path, payload, args.poll_seconds):
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=json_default))
        return 1

    now = datetime.now(BEIJING_TZ)
    target = next_trading_window_start(now)
    if not args.wait_until_open and (target is None or target > now + timedelta(seconds=1)):
        payload["note"] = "outside active trading window; order submission still attempted because --wait-until-open was not set"

    submitted = place_manual_orders(
        client=client,
        picks=picks,
        quantity=quantity,
        trade_day=trade_day,
        execution_model=execution_model,
        dry_run=bool(args.dry_run),
    )
    orders_after = normalize_orders(client.get_agent_orders())
    payload.update(
        {
            "status": "dry_run_complete" if args.dry_run else "complete",
            "updated_at": now_iso(),
            "submitted_count": sum(1 for row in submitted if row.get("status") == "submitted"),
            "dry_run_count": sum(1 for row in submitted if row.get("status") == "dry_run"),
            "skipped_count": sum(1 for row in submitted if row.get("status") == "skipped"),
            "error_count": sum(1 for row in submitted if row.get("status") == "error"),
            "active_orders_after": sum(1 for row in orders_after if is_active_order(row.get("order_status"))),
            "results": submitted,
        }
    )
    write_json(output_path, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=json_default))
    return 0 if payload["error_count"] == 0 else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (GatewayError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
