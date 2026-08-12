#!/usr/bin/env python3
"""Run a strict out-of-sample walk-forward backtest on engineered features."""

from __future__ import annotations

import argparse
import gc
import json
from datetime import datetime, timezone
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from train_lightgbm import (
    build_category_mappings,
    build_feature_frame,
    choose_feature_columns,
    compute_metrics,
    compute_regression_metrics,
    cross_sectional_demean,
    load_frame,
    percentile_rank_scores,
)
from execution_model import (
    DEFAULT_EXECUTION_MODEL,
    REALISTIC_BACKTEST_METHOD_VERSION,
    ExecutionModel,
    buy_liquidity_skip_reason,
    execution_model_snapshot,
    liquidity_cap_notional,
    near_price_limit,
    previous_close_from_row,
    slippage_price,
    to_float,
)
from trading_fees import DEFAULT_FEE_MODEL, FeeModel, transaction_fee


DEFAULT_TRAIN_PATH = "quant_data/ml_features_ready.parquet"
DEFAULT_OUTPUT_DIR = "quant_data/backtests"
BACKTEST_METHOD_VERSION = REALISTIC_BACKTEST_METHOD_VERSION
DEFAULT_BACKTEST_INITIAL_CAPITAL = 1_000_000.0
DEFAULT_BACKTEST_CASH_BUFFER_PCT = 0.05
DEFAULT_BACKTEST_LOT_SIZE = 100
DEFAULT_BACKTEST_MAX_BUY_ORDER_QTY = 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Strict walk-forward out-of-sample backtest.")
    parser.add_argument("--train-path", default=DEFAULT_TRAIN_PATH, help="Feature parquet with labels.")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="Directory for backtest outputs.")
    parser.add_argument("--min-train-days", type=int, default=252, help="Minimum unique trade dates before first rebalance.")
    parser.add_argument("--retrain-every", type=int, default=20, help="Retrain every N rebalance dates.")
    parser.add_argument("--rebalance-every", type=int, default=5, help="Rebalance every N trade dates.")
    parser.add_argument("--top-k", type=int, default=5, help="Hold top K stocks on each rebalance date.")
    parser.add_argument("--threshold", type=float, default=0.5, help="Classification threshold for OOS metrics.")
    parser.add_argument("--objective", choices=("binary", "regression"), default="binary")
    parser.add_argument("--cross-sectional-target", action="store_true")
    parser.add_argument("--max-drop", type=int, default=0, help="Maximum held symbols replaced per rebalance. 0 preserves legacy full Top-K replacement.")
    parser.add_argument("--profile-name", default="", help="Optional model profile name for this backtest run.")
    parser.add_argument("--profile-label", default="", help="Optional display label for this backtest run.")
    parser.add_argument("--label-horizon", type=int, default=0, help="Optional label horizon metadata for this run.")
    parser.add_argument("--label-threshold", type=float, default=0.0, help="Optional label threshold metadata for this run.")
    parser.add_argument("--initial-capital", type=float, default=DEFAULT_BACKTEST_INITIAL_CAPITAL, help="RMB capital base used to estimate fixed trading fees.")
    parser.add_argument("--budget-total", type=float, default=None, help="Optional RMB budget cap for realistic execution simulation.")
    parser.add_argument("--cash-buffer-pct", type=float, default=DEFAULT_BACKTEST_CASH_BUFFER_PCT)
    parser.add_argument("--lot-size", type=int, default=DEFAULT_BACKTEST_LOT_SIZE)
    parser.add_argument("--max-buy-order-qty", type=int, default=DEFAULT_BACKTEST_MAX_BUY_ORDER_QTY, help="Optional max buy quantity per order. 0 disables the cap.")
    parser.add_argument("--commission-rate", type=float, default=DEFAULT_FEE_MODEL.commission_rate)
    parser.add_argument("--min-commission", type=float, default=DEFAULT_FEE_MODEL.min_commission)
    parser.add_argument("--platform-fee", type=float, default=DEFAULT_FEE_MODEL.platform_fee)
    parser.add_argument("--tiny-fee-rate", type=float, default=DEFAULT_FEE_MODEL.tiny_fee_rate)
    parser.add_argument("--sell-stamp-duty-rate", type=float, default=DEFAULT_FEE_MODEL.sell_stamp_duty_rate)
    return parser.parse_args()


def build_model_params(*, objective: str, scale_pos_weight: float = 1.0) -> dict[str, object]:
    params: dict[str, object] = {
        "objective": "regression_l1" if objective == "regression" else "binary",
        "learning_rate": 0.05,
        "num_leaves": 63,
        "colsample_bytree": 0.8,
        "force_col_wise": True,
        "num_threads": 1,
        "random_state": 42,
        "verbosity": -1,
    }
    if objective == "binary":
        params["scale_pos_weight"] = scale_pos_weight
    return params


def select_topk_drop_picks(
    scored: pd.DataFrame,
    *,
    held_symbols: set[str],
    top_k: int,
    max_drop: int,
) -> pd.DataFrame:
    """Choose Top-K while replacing at most max_drop currently held symbols."""
    ranked = scored.copy()
    ranked["code"] = ranked["code"].astype(str)
    ranked = ranked.sort_values("score", ascending=False, kind="stable").drop_duplicates("code", keep="first")
    target_size = max(int(top_k), 1)
    drop_limit = max(int(max_drop), 0)
    if drop_limit <= 0 or not held_symbols:
        return ranked.head(target_size).copy()

    rank_by_symbol = {symbol: rank for rank, symbol in enumerate(ranked["code"].tolist())}
    available_held = [symbol for symbol in held_symbols if symbol in rank_by_symbol]
    must_drop_for_size = max(len(available_held) - target_size, 0)
    allowed_drop = max(drop_limit, must_drop_for_size)
    outside_topk = [symbol for symbol in available_held if rank_by_symbol[symbol] >= target_size]
    drop_symbols = set(
        sorted(outside_topk, key=lambda symbol: rank_by_symbol[symbol], reverse=True)[:allowed_drop]
    )
    retained = {symbol for symbol in available_held if symbol not in drop_symbols}

    selected: list[str] = list(retained)
    for symbol in ranked["code"]:
        if symbol in retained:
            continue
        selected.append(symbol)
        if len(selected) >= target_size:
            break
    selected_set = set(selected[:target_size])
    return ranked[ranked["code"].isin(selected_set)].head(target_size).copy()


def max_drawdown(equity_curve: pd.Series) -> float:
    running_max = equity_curve.cummax()
    drawdown = equity_curve / running_max - 1.0
    return float(drawdown.min())


def annualized_return(equity_curve: pd.Series, dates: pd.Series) -> float:
    if equity_curve.empty:
        return 0.0
    start = pd.to_datetime(dates.iloc[0])
    end = pd.to_datetime(dates.iloc[-1])
    total_days = max((end - start).days, 1)
    total_return = float(equity_curve.iloc[-1] / equity_curve.iloc[0] - 1.0)
    years = total_days / 365.25
    if years <= 0:
        return total_return
    return float((1.0 + total_return) ** (1.0 / years) - 1.0)


def training_end_for_rebalance(unique_dates: pd.Index, rebalance_date: object, label_horizon: int) -> object | None:
    """Return the first date to exclude from training for a purged walk-forward split."""
    rebalance_index = unique_dates.get_loc(rebalance_date)
    if isinstance(rebalance_index, slice) or not isinstance(rebalance_index, (int, np.integer)):
        return None
    cutoff_index = int(rebalance_index) - max(int(label_horizon), 0)
    if cutoff_index <= 0:
        return None
    return unique_dates[cutoff_index]


def estimate_rebalance_fees(
    *,
    previous_symbols: set[str],
    next_symbols: set[str],
    portfolio_value: float,
    fee_model: FeeModel,
) -> dict[str, float | int]:
    if portfolio_value <= 0 or not next_symbols:
        return {
            "buy_count": 0,
            "sell_count": 0,
            "buy_notional": 0.0,
            "sell_notional": 0.0,
            "buy_fee": 0.0,
            "sell_fee": 0.0,
            "total_fee": 0.0,
        }
    buy_symbols = next_symbols - previous_symbols
    sell_symbols = previous_symbols - next_symbols
    buy_notional_per_order = portfolio_value / max(len(next_symbols), 1)
    sell_notional_per_order = portfolio_value / max(len(previous_symbols), 1) if previous_symbols else 0.0
    buy_fee = sum(transaction_fee("BUY", buy_notional_per_order, fee_model) for _ in buy_symbols)
    sell_fee = sum(transaction_fee("SELL", sell_notional_per_order, fee_model) for _ in sell_symbols)
    return {
        "buy_count": int(len(buy_symbols)),
        "sell_count": int(len(sell_symbols)),
        "buy_notional": float(len(buy_symbols) * buy_notional_per_order),
        "sell_notional": float(len(sell_symbols) * sell_notional_per_order),
        "buy_fee": float(buy_fee),
        "sell_fee": float(sell_fee),
        "total_fee": float(buy_fee + sell_fee),
    }


def round_lot(quantity: int, lot_size: int) -> int:
    lots = max(int(quantity), 0) // max(int(lot_size), 1)
    return lots * max(int(lot_size), 1)


def affordable_lot_quantity(*, cash: float, price: float, lot_size: int, fee_model: FeeModel) -> int:
    if cash <= 0 or price <= 0:
        return 0
    lot = max(int(lot_size), 1)
    low = 0
    high = int(cash / price) // lot
    affordable = 0
    while low <= high:
        mid = (low + high) // 2
        quantity = mid * lot
        notional = quantity * price
        total_cost = notional + transaction_fee("BUY", notional, fee_model)
        if total_cost <= cash:
            affordable = quantity
            low = mid + 1
        else:
            high = mid - 1
    return affordable


def apply_optional_quantity_cap(quantity: int, max_quantity: int | None) -> int:
    normalized = int(max(quantity, 0))
    if normalized <= 0:
        return 0
    cap = int(max_quantity or 0)
    if cap <= 0:
        return normalized
    return min(normalized, cap)


def row_price(row: dict[str, object] | None, *, column: str, fallback: float = 0.0) -> float:
    if not row:
        return fallback
    value = to_float(row.get(column))
    return value if value > 0 else fallback


def mark_to_market(
    *,
    cash: float,
    positions: dict[str, int],
    rows_by_code: dict[str, dict[str, object]],
    fallback_prices: dict[str, float],
    price_column: str,
) -> float:
    total = float(cash)
    for symbol, quantity in positions.items():
        if quantity <= 0:
            continue
        price = row_price(rows_by_code.get(symbol), column=price_column, fallback=fallback_prices.get(symbol, 0.0))
        total += int(quantity) * max(price, 0.0)
    return float(total)


class IncrementalParquetWriter:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.writer: pq.ParquetWriter | None = None

    def write(self, frame: pd.DataFrame) -> None:
        if frame.empty:
            return
        table = pa.Table.from_pandas(frame, preserve_index=False)
        if self.writer is None:
            if self.path.exists():
                self.path.unlink()
            self.writer = pq.ParquetWriter(self.path, table.schema)
        self.writer.write_table(table)

    def close(self) -> None:
        if self.writer is not None:
            self.writer.close()
            self.writer = None


def main() -> int:
    args = parse_args()
    fee_model = FeeModel(
        commission_rate=max(float(args.commission_rate), 0.0),
        min_commission=max(float(args.min_commission), 0.0),
        platform_fee=max(float(args.platform_fee), 0.0),
        tiny_fee_rate=max(float(args.tiny_fee_rate), 0.0),
        sell_stamp_duty_rate=max(float(args.sell_stamp_duty_rate), 0.0),
    )
    initial_capital = max(float(args.initial_capital), 1.0)
    budget_total = max(float(args.budget_total), 1.0) if args.budget_total is not None else None
    cash_buffer_pct = max(min(float(args.cash_buffer_pct), 0.95), 0.0)
    lot_size = max(int(args.lot_size), 1)
    max_buy_order_qty = max(int(args.max_buy_order_qty), 0)
    max_drop = max(int(args.max_drop), 0)
    execution_model: ExecutionModel = DEFAULT_EXECUTION_MODEL
    train_path = Path(args.train_path)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    df = load_frame(train_path)
    df["date"] = pd.to_datetime(df["date"])
    # Keep rows ordered by trade date so each walk-forward split becomes a cheap prefix slice.
    df = df.sort_values("date", kind="stable").reset_index(drop=True)

    feature_cols, categorical_cols = choose_feature_columns(df)
    category_mappings = build_category_mappings(df, df, categorical_cols)
    date_values = df["date"].to_numpy()
    label_values = pd.to_numeric(df["label"], errors="coerce").fillna(0).to_numpy(dtype=np.int8)
    future_return_values = pd.to_numeric(df["future_return"], errors="coerce").astype(np.float32).to_numpy()
    if args.objective == "regression":
        target_values = future_return_values.copy()
        if args.cross_sectional_target:
            target_values = cross_sectional_demean(target_values, date_values)
    else:
        target_values = label_values
    summary_stats = {
        "num_rows": int(len(df)),
        "num_codes": int(df["code"].nunique()),
        "num_trade_dates": int(df["date"].nunique()),
    }
    meta_cols = [col for col in ["date", "code", "name", "industry"] if col in df.columns]
    prediction_cols = meta_cols + ["label", "future_return", "raw_score", "score"]
    trade_cols = ["rebalance_date"] + [col for col in ["code", "name", "industry"] if col in df.columns] + [
        "action",
        "score",
        "execution_date",
        "execution_price",
        "execution_quantity",
        "execution_notional",
        "execution_fee",
        "skip_reason",
        "future_return",
        "label",
        "amount",
        "liquidity_cap_notional",
        "estimated_buy_notional",
        "estimated_buy_fee",
    ]

    unique_dates = pd.Index(pd.unique(date_values[~pd.isna(date_values)]))
    if len(unique_dates) <= args.min_train_days:
        raise SystemExit("Not enough trading days to start walk-forward backtest.")

    rebalance_dates = unique_dates[args.min_train_days :: args.rebalance_every]
    if len(rebalance_dates) == 0:
        raise SystemExit("No rebalance dates are available for backtesting.")

    prediction_path = output_dir / "oos_predictions.parquet"
    trade_log_path = output_dir / "trade_log.parquet"
    equity_path = output_dir / "equity_curve.parquet"
    summary_path = output_dir / "summary.json"
    prediction_tmp_path = output_dir / "oos_predictions.tmp.parquet"
    trade_log_tmp_path = output_dir / "trade_log.tmp.parquet"
    equity_tmp_path = output_dir / "equity_curve.tmp.parquet"
    summary_tmp_path = output_dir / "summary.tmp.json"
    prediction_writer = IncrementalParquetWriter(prediction_tmp_path)
    trade_log_writer = IncrementalParquetWriter(trade_log_tmp_path)
    metric_target_chunks: list[np.ndarray] = []
    metric_score_chunks: list[np.ndarray] = []
    equity_rows: list[dict[str, object]] = []

    model: lgb.Booster | None = None
    rebalance_counter = 0
    cash = budget_total if budget_total is not None else initial_capital
    starting_capital = cash
    positions: dict[str, int] = {}
    fallback_prices: dict[str, float] = {}
    previous_equity = cash
    total_fee_paid = 0.0
    try:
        for rebalance_date in rebalance_dates:
            rebalance_position = unique_dates.get_loc(rebalance_date)
            if isinstance(rebalance_position, slice) or not isinstance(rebalance_position, (int, np.integer)):
                continue
            execution_position = int(rebalance_position) + 1
            if execution_position >= len(unique_dates):
                continue
            execution_date = unique_dates[execution_position]
            test_start = int(date_values.searchsorted(rebalance_date, side="left"))
            test_end = int(date_values.searchsorted(rebalance_date, side="right"))
            execution_start = int(date_values.searchsorted(execution_date, side="left"))
            execution_end = int(date_values.searchsorted(execution_date, side="right"))
            if test_start <= 0 or test_end <= test_start:
                continue
            if execution_start <= 0 or execution_end <= execution_start:
                continue

            if model is None or rebalance_counter % args.retrain_every == 0:
                train_cutoff_date = training_end_for_rebalance(unique_dates, rebalance_date, args.label_horizon)
                if train_cutoff_date is None:
                    continue
                train_end = int(date_values.searchsorted(train_cutoff_date, side="left"))
                if train_end <= 0:
                    continue
                train_slice = df.iloc[:train_end]
                X_train = build_feature_frame(train_slice, feature_cols, categorical_cols, category_mappings)
                y_train = target_values[:train_end]
                if args.objective == "binary":
                    positive_count = int(y_train.sum())
                    negative_count = int(len(y_train) - positive_count)
                    scale_pos_weight = negative_count / max(positive_count, 1)
                else:
                    scale_pos_weight = 1.0

                print(
                    f"retrain on {pd.Timestamp(rebalance_date).date()}: "
                    f"train_rows={len(X_train)} train_cutoff={pd.Timestamp(train_cutoff_date).date()} "
                    f"test_rows={test_end - test_start}"
                )
                train_data = lgb.Dataset(
                    X_train,
                    label=y_train,
                    categorical_feature=categorical_cols,
                    free_raw_data=True,
                )
                train_data.construct()
                del train_slice
                del X_train
                del y_train
                gc.collect()
                model = lgb.train(
                    build_model_params(objective=args.objective, scale_pos_weight=scale_pos_weight),
                    train_data,
                    num_boost_round=500,
                    callbacks=[lgb.log_evaluation(0)],
                )
                del train_data
                gc.collect()

            test_slice = df.iloc[test_start:test_end]
            X_test = build_feature_frame(test_slice, feature_cols, categorical_cols, category_mappings)
            raw_score_values = model.predict(X_test).astype(np.float32, copy=False)
            score_values = percentile_rank_scores(raw_score_values) if args.objective == "regression" else raw_score_values
            scored = test_slice.loc[:, meta_cols].copy()
            scored["label"] = label_values[test_start:test_end]
            scored["future_return"] = future_return_values[test_start:test_end]
            scored["raw_score"] = raw_score_values
            scored["score"] = score_values
            prediction_writer.write(scored.loc[:, prediction_cols].copy())
            metric_target_chunks.append(target_values[test_start:test_end].copy())
            metric_score_chunks.append(raw_score_values.copy())

            picks = select_topk_drop_picks(
                scored,
                held_symbols={symbol for symbol, quantity in positions.items() if quantity > 0},
                top_k=args.top_k,
                max_drop=max_drop,
            )
            execution_slice = df.iloc[execution_start:execution_end]
            execution_rows_by_code = {str(row["code"]): row for row in execution_slice.to_dict(orient="records")}
            signal_rows_by_code = {str(row["code"]): row for row in test_slice.to_dict(orient="records")}
            pre_trade_equity = mark_to_market(
                cash=cash,
                positions=positions,
                rows_by_code=execution_rows_by_code,
                fallback_prices=fallback_prices,
                price_column="open",
            )
            capital_base = min(pre_trade_equity, budget_total) if budget_total is not None else pre_trade_equity
            investable_capital = max(capital_base * (1.0 - cash_buffer_pct), 0.0)
            target_count = int(len(picks))
            target_value = investable_capital / target_count if target_count else 0.0
            target_qty_by_symbol: dict[str, int] = {}
            trade_rows: list[dict[str, object]] = []
            buy_fee = 0.0
            sell_fee = 0.0
            buy_count = 0
            sell_count = 0
            skip_count = 0

            for _, pick in picks.iterrows():
                symbol = str(pick.get("code"))
                if max_drop > 0 and int(positions.get(symbol, 0)) > 0:
                    target_qty_by_symbol[symbol] = int(positions[symbol])
                    continue
                execution_row = execution_rows_by_code.get(symbol)
                buy_base_price = row_price(execution_row, column="open")
                buy_price = slippage_price(buy_base_price, "BUY", execution_model)
                desired_quantity = round_lot(int(target_value / buy_price) if buy_price > 0 else 0, lot_size)
                target_qty_by_symbol[symbol] = apply_optional_quantity_cap(desired_quantity, max_buy_order_qty)

            for symbol in sorted(list(positions)):
                current_qty = int(positions.get(symbol, 0))
                desired_qty = int(target_qty_by_symbol.get(symbol, 0))
                sell_qty = max(current_qty - desired_qty, 0)
                if sell_qty <= 0:
                    continue
                execution_row = execution_rows_by_code.get(symbol)
                sell_base_price = row_price(execution_row, column="open", fallback=fallback_prices.get(symbol, 0.0))
                sell_price = slippage_price(sell_base_price, "SELL", execution_model)
                skip_reason = None
                if execution_row is None or sell_price <= 0:
                    skip_reason = "SKIP_NO_REFERENCE_DATA"
                elif near_price_limit(
                    side="SELL",
                    price=sell_base_price,
                    previous_close=previous_close_from_row(execution_row),
                    symbol=symbol,
                    name=execution_row.get("name"),
                    model=execution_model,
                ):
                    skip_reason = "SKIP_LIMIT_DOWN"
                if skip_reason is not None:
                    skip_count += 1
                    trade_rows.append(
                        {
                            "rebalance_date": rebalance_date,
                            "execution_date": execution_date,
                            "code": symbol,
                            "name": execution_row.get("name") if execution_row else None,
                            "industry": execution_row.get("industry") if execution_row else None,
                            "action": "SELL",
                            "score": None,
                            "execution_price": sell_price,
                            "execution_quantity": 0,
                            "execution_notional": 0.0,
                            "execution_fee": 0.0,
                            "skip_reason": skip_reason,
                            "future_return": None,
                            "label": None,
                            "amount": execution_row.get("amount") if execution_row else None,
                            "liquidity_cap_notional": liquidity_cap_notional(execution_row.get("amount"), execution_model) if execution_row else None,
                            "estimated_buy_notional": 0.0,
                            "estimated_buy_fee": 0.0,
                        }
                    )
                    continue
                notional = sell_qty * sell_price
                fee = transaction_fee("SELL", notional, fee_model)
                cash += max(notional - fee, 0.0)
                positions[symbol] = current_qty - sell_qty
                if positions[symbol] <= 0:
                    positions.pop(symbol, None)
                fallback_prices[symbol] = sell_price
                sell_fee += fee
                sell_count += 1
                total_fee_paid += fee
                trade_rows.append(
                    {
                        "rebalance_date": rebalance_date,
                        "execution_date": execution_date,
                        "code": symbol,
                        "name": execution_row.get("name") if execution_row else None,
                        "industry": execution_row.get("industry") if execution_row else None,
                        "action": "SELL",
                        "score": None,
                        "execution_price": sell_price,
                        "execution_quantity": sell_qty,
                        "execution_notional": notional,
                        "execution_fee": fee,
                        "skip_reason": None,
                        "future_return": None,
                        "label": None,
                        "amount": execution_row.get("amount") if execution_row else None,
                        "liquidity_cap_notional": liquidity_cap_notional(execution_row.get("amount"), execution_model) if execution_row else None,
                        "estimated_buy_notional": 0.0,
                        "estimated_buy_fee": 0.0,
                    }
                )

            for _, pick in picks.iterrows():
                symbol = str(pick.get("code"))
                desired_qty = int(target_qty_by_symbol.get(symbol, 0))
                current_qty = int(positions.get(symbol, 0))
                buy_qty = apply_optional_quantity_cap(max(desired_qty - current_qty, 0), max_buy_order_qty)
                if buy_qty <= 0:
                    continue
                execution_row = execution_rows_by_code.get(symbol)
                signal_row = signal_rows_by_code.get(symbol, {})
                buy_base_price = row_price(execution_row, column="open")
                buy_price = slippage_price(buy_base_price, "BUY", execution_model)
                buy_qty = round_lot(buy_qty, lot_size)
                notional = buy_qty * buy_price
                skip_reason = None
                if execution_row is None or buy_price <= 0:
                    skip_reason = "SKIP_NO_REFERENCE_DATA"
                elif near_price_limit(
                    side="BUY",
                    price=buy_base_price,
                    previous_close=previous_close_from_row(execution_row),
                    symbol=symbol,
                    name=pick.get("name"),
                    model=execution_model,
                ):
                    skip_reason = "SKIP_LIMIT_UP"
                else:
                    skip_reason = buy_liquidity_skip_reason(
                        amount=signal_row.get("amount"),
                        order_notional=notional,
                        model=execution_model,
                    )
                if skip_reason is None:
                    affordable_qty = affordable_lot_quantity(cash=cash, price=buy_price, lot_size=lot_size, fee_model=fee_model)
                    buy_qty = min(buy_qty, affordable_qty)
                    notional = buy_qty * buy_price
                    if buy_qty <= 0:
                        skip_reason = "SKIP_NO_CASH"
                if skip_reason is not None:
                    skip_count += 1
                    trade_rows.append(
                        {
                            "rebalance_date": rebalance_date,
                            "execution_date": execution_date,
                            "code": symbol,
                            "name": pick.get("name"),
                            "industry": pick.get("industry"),
                            "action": "BUY",
                            "score": pick.get("score"),
                            "execution_price": buy_price,
                            "execution_quantity": 0,
                            "execution_notional": 0.0,
                            "execution_fee": 0.0,
                            "skip_reason": skip_reason,
                            "future_return": pick.get("future_return"),
                            "label": pick.get("label"),
                            "amount": signal_row.get("amount"),
                            "liquidity_cap_notional": liquidity_cap_notional(signal_row.get("amount"), execution_model),
                            "estimated_buy_notional": notional,
                            "estimated_buy_fee": transaction_fee("BUY", notional, fee_model) if notional > 0 else 0.0,
                        }
                    )
                    continue
                fee = transaction_fee("BUY", notional, fee_model)
                cash -= notional + fee
                positions[symbol] = current_qty + buy_qty
                fallback_prices[symbol] = buy_price
                buy_fee += fee
                buy_count += 1
                total_fee_paid += fee
                trade_rows.append(
                    {
                        "rebalance_date": rebalance_date,
                        "execution_date": execution_date,
                        "code": symbol,
                        "name": pick.get("name"),
                        "industry": pick.get("industry"),
                        "action": "BUY",
                        "score": pick.get("score"),
                        "execution_price": buy_price,
                        "execution_quantity": buy_qty,
                        "execution_notional": notional,
                        "execution_fee": fee,
                        "skip_reason": None,
                        "future_return": pick.get("future_return"),
                        "label": pick.get("label"),
                        "amount": signal_row.get("amount"),
                        "liquidity_cap_notional": liquidity_cap_notional(signal_row.get("amount"), execution_model),
                        "estimated_buy_notional": notional,
                        "estimated_buy_fee": fee,
                    }
                )

            end_equity_actual = mark_to_market(
                cash=cash,
                positions=positions,
                rows_by_code=execution_rows_by_code,
                fallback_prices=fallback_prices,
                price_column="close",
            )
            for symbol, row in execution_rows_by_code.items():
                close_price = row_price(row, column="close")
                if close_price > 0:
                    fallback_prices[symbol] = close_price
            portfolio_return_net = end_equity_actual / previous_equity - 1.0 if previous_equity > 0 else 0.0
            trading_fee = buy_fee + sell_fee
            fee_return = trading_fee / max(pre_trade_equity, 1.0)
            gross_return = portfolio_return_net + fee_return
            previous_equity = end_equity_actual

            equity_rows.append(
                {
                    "rebalance_date": rebalance_date,
                    "execution_date": execution_date,
                    "portfolio_return": portfolio_return_net,
                    "gross_portfolio_return": gross_return,
                    "fee_return": fee_return,
                    "trading_fee": trading_fee,
                    "buy_fee": buy_fee,
                    "sell_fee": sell_fee,
                    "buy_count": buy_count,
                    "sell_count": sell_count,
                    "cash": cash,
                    "market_value": max(end_equity_actual - cash, 0.0),
                    "equity": end_equity_actual / starting_capital,
                    "equity_value": end_equity_actual,
                    "num_picks": int(len(picks)),
                    "skip_count": skip_count,
                    "position_count": int(sum(1 for quantity in positions.values() if quantity > 0)),
                }
            )

            if trade_rows:
                trade_df = pd.DataFrame(trade_rows).loc[:, trade_cols].copy()
                for column in ["code", "name", "industry", "action", "skip_reason"]:
                    if column in trade_df.columns:
                        trade_df[column] = trade_df[column].fillna("").astype("string")
                for column in [
                    "score",
                    "execution_price",
                    "execution_notional",
                    "execution_fee",
                    "future_return",
                    "label",
                    "amount",
                    "liquidity_cap_notional",
                    "estimated_buy_notional",
                    "estimated_buy_fee",
                ]:
                    if column in trade_df.columns:
                        trade_df[column] = pd.to_numeric(trade_df[column], errors="coerce").astype("float64")
                if "execution_quantity" in trade_df.columns:
                    trade_df["execution_quantity"] = pd.to_numeric(trade_df["execution_quantity"], errors="coerce").fillna(0).astype("int64")
                trade_log_writer.write(trade_df)

            rebalance_counter += 1
            del test_slice
            del X_test
            del score_values
            del raw_score_values
            del scored
            del picks
            gc.collect()
    finally:
        prediction_writer.close()
        trade_log_writer.close()

    if not metric_target_chunks or not equity_rows:
        raise SystemExit("Backtest produced no predictions.")

    metric_targets = np.concatenate(metric_target_chunks)
    metric_scores = np.concatenate(metric_score_chunks)
    if args.objective == "regression":
        metrics = compute_regression_metrics(metric_targets, metric_scores)
    else:
        metrics = compute_metrics(pd.Series(metric_targets), pd.Series(metric_scores), args.threshold)
    del metric_targets
    del metric_scores
    gc.collect()

    equity_df = pd.DataFrame(equity_rows)
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_id": output_dir.name,
        "profile_name": args.profile_name.strip() or None,
        "profile_label": args.profile_label.strip() or None,
        "label_horizon": args.label_horizon if args.label_horizon > 0 else None,
        "label_threshold": args.label_threshold if args.objective == "regression" or args.label_threshold > 0 else None,
        "model_objective": args.objective,
        "cross_sectional_target": bool(args.cross_sectional_target),
        "score_kind": "percentile_rank" if args.objective == "regression" else "probability",
        "method_version": BACKTEST_METHOD_VERSION,
        "purge_days": int(max(args.label_horizon, 0)),
        "execution_assumption": "Realistic T+1 open-proxy execution simulation with conservative slippage, fees, target-value lot sizing, cash buffer, optional max buy quantity cap, liquidity caps, and price-limit skip rules.",
        "train_path": str(train_path),
        "initial_capital": initial_capital,
        "starting_capital": starting_capital,
        "budget_total": budget_total,
        "cash_buffer_pct": cash_buffer_pct,
        "lot_size": lot_size,
        "max_buy_order_qty": max_buy_order_qty,
        "execution_model": execution_model_snapshot(execution_model),
        "fee_model": {
            "commission_rate": fee_model.commission_rate,
            "min_commission": fee_model.min_commission,
            "platform_fee": fee_model.platform_fee,
            "tiny_fee_rate": fee_model.tiny_fee_rate,
            "sell_stamp_duty_rate": fee_model.sell_stamp_duty_rate,
        },
        **summary_stats,
        "min_train_days": args.min_train_days,
        "retrain_every": args.retrain_every,
        "rebalance_every": args.rebalance_every,
        "top_k": args.top_k,
        "max_drop": max_drop,
        "threshold": args.threshold,
        "num_rebalances": int(len(equity_df)),
        "oos_metrics": metrics,
        "portfolio_total_return": float(equity_df["equity"].iloc[-1] - 1.0),
        "portfolio_cagr": annualized_return(equity_df["equity"], equity_df["rebalance_date"]),
        "portfolio_max_drawdown": max_drawdown(equity_df["equity"]),
        "portfolio_win_rate": float((equity_df["portfolio_return"] > 0).mean()),
        "portfolio_avg_return": float(equity_df["portfolio_return"].mean()),
        "portfolio_avg_gross_return": float(equity_df["gross_portfolio_return"].mean()),
        "total_trading_fee": total_fee_paid,
        "avg_fee_return": float(equity_df["fee_return"].mean()),
        "total_skip_count": int(equity_df.get("skip_count", pd.Series(dtype="int64")).sum()),
        "final_cash": float(equity_df["cash"].iloc[-1]) if "cash" in equity_df.columns else None,
        "final_market_value": float(equity_df["market_value"].iloc[-1]) if "market_value" in equity_df.columns else None,
        "portfolio_std_return": float(equity_df["portfolio_return"].std(ddof=0)),
        "backtest_start": str(pd.to_datetime(equity_df["rebalance_date"].min()).date()),
        "backtest_end": str(pd.to_datetime(equity_df["rebalance_date"].max()).date()),
    }

    equity_df.to_parquet(equity_tmp_path, index=False)
    summary_tmp_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    prediction_tmp_path.replace(prediction_path)
    trade_log_tmp_path.replace(trade_log_path)
    equity_tmp_path.replace(equity_path)
    summary_tmp_path.replace(summary_path)

    print("Strict OOS backtest completed.")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(equity_df.tail(10).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
