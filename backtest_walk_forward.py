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

from train_lightgbm import build_category_mappings, build_feature_frame, choose_feature_columns, compute_metrics, load_frame
from trading_fees import DEFAULT_FEE_MODEL, FeeModel, transaction_fee


DEFAULT_TRAIN_PATH = "quant_data/ml_features_ready.parquet"
DEFAULT_OUTPUT_DIR = "quant_data/backtests"
BACKTEST_METHOD_VERSION = "purged_label_horizon_costs_v2"
DEFAULT_BACKTEST_INITIAL_CAPITAL = 1_000_000.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Strict walk-forward out-of-sample backtest.")
    parser.add_argument("--train-path", default=DEFAULT_TRAIN_PATH, help="Feature parquet with labels.")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="Directory for backtest outputs.")
    parser.add_argument("--min-train-days", type=int, default=252, help="Minimum unique trade dates before first rebalance.")
    parser.add_argument("--retrain-every", type=int, default=20, help="Retrain every N rebalance dates.")
    parser.add_argument("--rebalance-every", type=int, default=5, help="Rebalance every N trade dates.")
    parser.add_argument("--top-k", type=int, default=5, help="Hold top K stocks on each rebalance date.")
    parser.add_argument("--threshold", type=float, default=0.5, help="Classification threshold for OOS metrics.")
    parser.add_argument("--profile-name", default="", help="Optional model profile name for this backtest run.")
    parser.add_argument("--profile-label", default="", help="Optional display label for this backtest run.")
    parser.add_argument("--label-horizon", type=int, default=0, help="Optional label horizon metadata for this run.")
    parser.add_argument("--label-threshold", type=float, default=0.0, help="Optional label threshold metadata for this run.")
    parser.add_argument("--initial-capital", type=float, default=DEFAULT_BACKTEST_INITIAL_CAPITAL, help="RMB capital base used to estimate fixed trading fees.")
    parser.add_argument("--commission-rate", type=float, default=DEFAULT_FEE_MODEL.commission_rate)
    parser.add_argument("--min-commission", type=float, default=DEFAULT_FEE_MODEL.min_commission)
    parser.add_argument("--platform-fee", type=float, default=DEFAULT_FEE_MODEL.platform_fee)
    parser.add_argument("--tiny-fee-rate", type=float, default=DEFAULT_FEE_MODEL.tiny_fee_rate)
    parser.add_argument("--sell-stamp-duty-rate", type=float, default=DEFAULT_FEE_MODEL.sell_stamp_duty_rate)
    return parser.parse_args()


def build_model_params(*, scale_pos_weight: float) -> dict[str, object]:
    return {
        "objective": "binary",
        "learning_rate": 0.05,
        "num_leaves": 63,
        "colsample_bytree": 0.8,
        "force_col_wise": True,
        "num_threads": 1,
        "random_state": 42,
        "scale_pos_weight": scale_pos_weight,
    }


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
    summary_stats = {
        "num_rows": int(len(df)),
        "num_codes": int(df["code"].nunique()),
        "num_trade_dates": int(df["date"].nunique()),
    }
    meta_cols = [col for col in ["date", "code", "name", "industry"] if col in df.columns]
    prediction_cols = meta_cols + ["label", "future_return", "score"]
    trade_cols = ["rebalance_date"] + [col for col in ["code", "name", "industry"] if col in df.columns] + [
        "score",
        "future_return",
        "label",
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
    metric_label_chunks: list[np.ndarray] = []
    metric_score_chunks: list[np.ndarray] = []
    equity_rows: list[dict[str, object]] = []

    model: lgb.Booster | None = None
    rebalance_counter = 0
    equity_value = 1.0
    previous_symbols: set[str] = set()
    total_fee_paid = 0.0
    try:
        for rebalance_date in rebalance_dates:
            test_start = int(date_values.searchsorted(rebalance_date, side="left"))
            test_end = int(date_values.searchsorted(rebalance_date, side="right"))
            if test_start <= 0 or test_end <= test_start:
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
                y_train = label_values[:train_end]
                positive_count = int(y_train.sum())
                negative_count = int(len(y_train) - positive_count)
                scale_pos_weight = negative_count / max(positive_count, 1)

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
                    build_model_params(scale_pos_weight=scale_pos_weight),
                    train_data,
                    num_boost_round=500,
                    callbacks=[lgb.log_evaluation(0)],
                )
                del train_data
                gc.collect()

            test_slice = df.iloc[test_start:test_end]
            X_test = build_feature_frame(test_slice, feature_cols, categorical_cols, category_mappings)
            score_values = model.predict(X_test).astype(np.float32, copy=False)
            scored = test_slice.loc[:, meta_cols].copy()
            scored["label"] = label_values[test_start:test_end]
            scored["future_return"] = future_return_values[test_start:test_end]
            scored["score"] = score_values
            prediction_writer.write(scored.loc[:, prediction_cols].copy())
            metric_label_chunks.append(label_values[test_start:test_end].copy())
            metric_score_chunks.append(score_values.copy())

            picks = scored.nlargest(args.top_k, "score").copy()
            portfolio_return_gross = float(picks["future_return"].mean()) if not picks.empty else 0.0
            next_symbols = set(picks["code"].astype(str)) if "code" in picks.columns else set()
            portfolio_value_before_fees = equity_value * initial_capital
            fee_estimate = estimate_rebalance_fees(
                previous_symbols=previous_symbols,
                next_symbols=next_symbols,
                portfolio_value=portfolio_value_before_fees,
                fee_model=fee_model,
            )
            trading_fee = float(fee_estimate["total_fee"])
            total_fee_paid += trading_fee
            fee_return = trading_fee / portfolio_value_before_fees if portfolio_value_before_fees > 0 else 0.0
            portfolio_return_net = (1.0 - fee_return) * (1.0 + portfolio_return_gross) - 1.0
            equity_value *= 1.0 + portfolio_return_net

            equity_rows.append(
                {
                    "rebalance_date": rebalance_date,
                    "portfolio_return": portfolio_return_net,
                    "gross_portfolio_return": portfolio_return_gross,
                    "fee_return": fee_return,
                    "trading_fee": trading_fee,
                    "buy_fee": float(fee_estimate["buy_fee"]),
                    "sell_fee": float(fee_estimate["sell_fee"]),
                    "buy_count": int(fee_estimate["buy_count"]),
                    "sell_count": int(fee_estimate["sell_count"]),
                    "equity": equity_value,
                    "num_picks": int(len(picks)),
                }
            )

            if not picks.empty:
                picks.insert(0, "rebalance_date", rebalance_date)
                new_symbols = next_symbols - previous_symbols
                buy_notional = portfolio_value_before_fees / max(len(next_symbols), 1)
                picks["estimated_buy_notional"] = picks["code"].astype(str).apply(lambda code: buy_notional if code in new_symbols else 0.0)
                picks["estimated_buy_fee"] = picks["estimated_buy_notional"].apply(lambda value: transaction_fee("BUY", value, fee_model))
                trade_log_writer.write(picks.loc[:, trade_cols].copy())
            previous_symbols = next_symbols

            rebalance_counter += 1
            del test_slice
            del X_test
            del score_values
            del scored
            del picks
            gc.collect()
    finally:
        prediction_writer.close()
        trade_log_writer.close()

    if not metric_label_chunks or not equity_rows:
        raise SystemExit("Backtest produced no predictions.")

    metric_labels = np.concatenate(metric_label_chunks)
    metric_scores = np.concatenate(metric_score_chunks)
    metrics = compute_metrics(
        pd.Series(metric_labels),
        pd.Series(metric_scores),
        args.threshold,
    )
    del metric_labels
    del metric_scores
    gc.collect()

    equity_df = pd.DataFrame(equity_rows)
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_id": output_dir.name,
        "profile_name": args.profile_name.strip() or None,
        "profile_label": args.profile_label.strip() or None,
        "label_horizon": args.label_horizon if args.label_horizon > 0 else None,
        "label_threshold": args.label_threshold if args.label_threshold > 0 else None,
        "method_version": BACKTEST_METHOD_VERSION,
        "purge_days": int(max(args.label_horizon, 0)),
        "execution_assumption": "Research-only close-to-close return simulation with label-horizon purge; includes estimated A-share transaction fees, excludes slippage, limit-up/limit-down fill constraints, and liquidity constraints.",
        "train_path": str(train_path),
        "initial_capital": initial_capital,
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
