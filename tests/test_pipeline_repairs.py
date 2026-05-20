from __future__ import annotations

import sys
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "apps" / "api"))

from batch_download_all_a import merge_existing_output
from backtest_walk_forward import annualized_return, estimate_rebalance_fees, max_drawdown, training_end_for_rebalance
from build_inference_features import build_inference_frame
from download_data import build_valuation_df, reference_status_path, write_reference_status
from paper_trade_futu import (
    SyncConfig,
    build_plan,
    compute_affordable_buy_quantity,
    execute_plan,
    parse_sina_quote_price,
    persist_targets,
    sina_quote_code,
)
from trading_fees import DEFAULT_FEE_MODEL, transaction_fee
from app.services import batch as batch_service
from app.services import benchmark as benchmark_service
from app.services import model as model_service
from app.services import model_profiles as model_profiles_service
from app.services import paper as paper_service
from app.services import source_readiness
from app.services.log_translation import translate_log_line


class PipelineRepairTests(unittest.TestCase):
    def test_valuation_uses_latest_prior_share_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            reference_dir = data_dir / "reference" / "valuation_reference"
            reference_dir.mkdir(parents=True)
            pd.DataFrame(
                [
                    {
                        "date": "2026-03-25",
                        "code": "000001",
                        "total_market_cap": 200.0,
                        "float_market_cap": 150.0,
                        "total_shares": 10.0,
                        "float_shares": 8.0,
                    }
                ]
            ).to_parquet(reference_dir / "000001.parquet", index=False)

            bundle_df = pd.DataFrame(
                [
                    {"date": "2026-03-26", "code": "sz.000001", "close": 21.0, "pctChg": 1.0, "peTTM": 5, "pbMRQ": 1, "psTTM": 2, "pcfNcfTTM": 3},
                    {"date": "2026-03-27", "code": "sz.000001", "close": 22.0, "pctChg": 1.0, "peTTM": 5, "pbMRQ": 1, "psTTM": 2, "pcfNcfTTM": 3},
                ]
            )

            valuation_df, warning = build_valuation_df(
                bundle_df,
                "000001",
                start_date="20260326",
                end_date="20260327",
                data_dir=data_dir,
            )

            self.assertIn("reference_cache_stale_until:2026-03-25", warning or "")
            self.assertEqual(valuation_df["total_shares"].tolist(), [10.0, 10.0])
            self.assertEqual(valuation_df["float_shares"].tolist(), [8.0, 8.0])
            self.assertEqual(valuation_df["total_market_cap"].tolist(), [210.0, 220.0])
            self.assertEqual(valuation_df["float_market_cap"].tolist(), [168.0, 176.0])

    def test_reference_status_allows_recent_slow_reference_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            reference_dir = data_dir / "reference" / "valuation_reference"
            reference_dir.mkdir(parents=True)
            pd.DataFrame(
                [
                    {
                        "date": "2026-05-13",
                        "code": "000001",
                        "total_market_cap": 200.0,
                        "float_market_cap": 150.0,
                        "total_shares": 10.0,
                        "float_shares": 8.0,
                    }
                ]
            ).to_parquet(reference_dir / "000001.parquet", index=False)
            stock_df = pd.DataFrame([{"code": "000001", "exchange": "sz", "industry": "Bank"}])

            write_reference_status(data_dir, stock_df=stock_df, target_trade_date="2026-05-20")
            payload = json.loads(reference_status_path(data_dir).read_text(encoding="utf-8"))

            self.assertEqual(payload["industry_missing_count"], 0)
            self.assertEqual(payload["valuation_reference_ready_count"], 1)
            self.assertEqual(payload["valuation_reference_stale_count"], 0)
            self.assertEqual(payload["valuation_reference_stale_after_days"], 45)

    def test_reference_status_marks_old_slow_reference_cache_stale(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            reference_dir = data_dir / "reference" / "valuation_reference"
            reference_dir.mkdir(parents=True)
            pd.DataFrame(
                [
                    {
                        "date": "2026-03-01",
                        "code": "000001",
                        "total_market_cap": 200.0,
                        "float_market_cap": 150.0,
                        "total_shares": 10.0,
                        "float_shares": 8.0,
                    }
                ]
            ).to_parquet(reference_dir / "000001.parquet", index=False)
            stock_df = pd.DataFrame([{"code": "000001", "exchange": "sz", "industry": "Bank"}])

            write_reference_status(data_dir, stock_df=stock_df, target_trade_date="2026-05-20")
            payload = json.loads(reference_status_path(data_dir).read_text(encoding="utf-8"))

            self.assertEqual(payload["valuation_reference_ready_count"], 0)
            self.assertEqual(payload["valuation_reference_stale_count"], 1)

    def test_incremental_merge_preserves_existing_non_null_reference_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "valuation.parquet"
            pd.DataFrame(
                [
                    {
                        "date": "2026-03-25",
                        "code": "000001",
                        "close": 10.0,
                        "total_market_cap": 100.0,
                        "total_shares": 10.0,
                    }
                ]
            ).to_parquet(path, index=False)
            fresh_df = pd.DataFrame(
                [
                    {
                        "date": "2026-03-25",
                        "code": "000001",
                        "close": 11.0,
                        "total_market_cap": pd.NA,
                        "total_shares": pd.NA,
                    }
                ]
            )

            merged = merge_existing_output(path, fresh_df)

            self.assertEqual(float(merged.loc[0, "close"]), 11.0)
            self.assertEqual(float(merged.loc[0, "total_market_cap"]), 100.0)
            self.assertEqual(float(merged.loc[0, "total_shares"]), 10.0)

    def test_inference_keeps_rows_with_only_recoverable_reference_nulls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            (data_dir / "daily_kline").mkdir(parents=True)
            (data_dir / "daily_valuation").mkdir(parents=True)
            dates = pd.date_range("2026-03-18", periods=25, freq="B")
            pd.DataFrame([{"code": "000001", "exchange": "sz", "name": "Ping An", "industry": "Bank"}]).to_parquet(
                data_dir / "stock_list.parquet",
                index=False,
            )
            pd.DataFrame(
                {
                    "date": dates,
                    "code": "000001",
                    "exchange": "sz",
                    "open": range(10, 35),
                    "high": range(11, 36),
                    "low": range(9, 34),
                    "close": range(10, 35),
                    "volume": [1000] * len(dates),
                    "amount": [10000] * len(dates),
                    "turnover": [1.0] * len(dates),
                    "amplitude": [1.0] * len(dates),
                    "pct_chg": [0.1] * len(dates),
                    "change": [0.1] * len(dates),
                }
            ).to_parquet(data_dir / "daily_kline" / "000001.parquet", index=False)
            pd.DataFrame(
                {
                    "date": dates,
                    "code": "000001",
                    "exchange": "sz",
                    "close": range(10, 35),
                    "pct_chg": [0.1] * len(dates),
                    "total_market_cap": [pd.NA] * len(dates),
                    "float_market_cap": [pd.NA] * len(dates),
                    "total_shares": [pd.NA] * len(dates),
                    "float_shares": [pd.NA] * len(dates),
                    "pe_ttm": [5.0] * len(dates),
                    "pb": [1.0] * len(dates),
                    "ps": [2.0] * len(dates),
                    "pcf": [3.0] * len(dates),
                }
            ).to_parquet(data_dir / "daily_valuation" / "000001.parquet", index=False)

            inference_df = build_inference_frame(data_dir, limit=0, as_of_date=None)

            self.assertEqual(len(inference_df), 1)
            self.assertEqual(inference_df.loc[0, "code"], "000001")

    def test_provider_probe_timeout_is_reported(self) -> None:
        with mock.patch.object(source_readiness, "bs", object()), mock.patch.object(source_readiness, "ak", object()):
            with mock.patch.object(
                source_readiness,
                "_run_provider_probe",
                side_effect=source_readiness.ProviderProbeTimeoutError("provider probe timed out after 30s"),
            ):
                result = source_readiness.get_china_market_data_readiness(local_date="2026-05-12")

        self.assertEqual(result["reason"], "baostock_probe_timeout")
        self.assertIn("timed out", result["baostock"]["error"])

    def test_benchmark_history_normalizes_akshare_index_schema(self) -> None:
        raw = pd.DataFrame(
            [
                {"日期": "2026-05-18", "开盘": "3900.1", "收盘": "3910.2", "成交量": "100"},
                {"日期": "2026-05-19", "开盘": "3910.2", "收盘": "3920.3", "成交量": "110"},
            ]
        )

        normalized = benchmark_service.normalize_akshare_index_history(raw)

        self.assertEqual(normalized["code"].tolist(), ["000300.SH", "000300.SH"])
        self.assertEqual(normalized["source"].tolist(), ["akshare.index_zh_a_hist", "akshare.index_zh_a_hist"])
        self.assertEqual(normalized["close"].tolist(), [3910.2, 3920.3])

    def test_benchmark_refresh_merges_into_canonical_index_parquet(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            quant_dir = Path(tmp) / "quant_data"
            index_dir = quant_dir / "index"
            index_dir.mkdir(parents=True)
            path = index_dir / "000300.SH.parquet"
            pd.DataFrame(
                [
                    {
                        "date": pd.Timestamp("2026-05-18"),
                        "code": "000300.SH",
                        "name": "沪深300",
                        "close": 3910.2,
                        "source": "akshare.index_zh_a_hist",
                        "updated_at": "2026-05-18T00:00:00+00:00",
                    }
                ]
            ).to_parquet(path, index=False)

            fake_ak = SimpleNamespace(
                index_zh_a_hist=mock.Mock(
                    return_value=pd.DataFrame(
                        [
                            {"日期": "2026-05-18", "收盘": 3911.0},
                            {"日期": "2026-05-19", "收盘": 3920.3},
                        ]
                    )
                )
            )
            settings = SimpleNamespace(quant_dir=quant_dir)

            with mock.patch.object(benchmark_service, "get_settings", return_value=settings):
                with mock.patch.object(benchmark_service, "_load_akshare", return_value=fake_ak):
                    result = benchmark_service.refresh_benchmark_history(end_date="20260519")

            stored = pd.read_parquet(path).sort_values("date").reset_index(drop=True)
            self.assertEqual(result["rows"], 2)
            self.assertEqual(result["latest_date"], "2026-05-19")
            self.assertEqual(stored["close"].tolist(), [3911.0, 3920.3])

    def test_recent_state_file_mtime_prevents_false_stall_on_json_race(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / "run"
            logs_dir = root / "logs"
            quant_dir = root / "quant_data"
            run_dir.mkdir()
            logs_dir.mkdir()
            (quant_dir / "batch_state").mkdir(parents=True)

            state_file = quant_dir / "batch_state" / "all_a_3y_state.json"
            state_file.write_text("{", encoding="utf-8")
            (run_dir / "full_market_3y.pid").write_text("container-1\n", encoding="utf-8")
            log_file = logs_dir / "full_market_3y_20260513T100045Z.log"
            log_file.write_text("started\n", encoding="utf-8")
            old_ts = (datetime.now(timezone.utc) - timedelta(minutes=60)).timestamp()
            log_file.touch()
            import os

            os.utime(log_file, (old_ts, old_ts))

            settings = SimpleNamespace(
                state_file=state_file,
                run_dir=run_dir,
                logs_dir=logs_dir,
                stock_list_path=quant_dir / "stock_list.parquet",
            )
            container = {
                "container_id": "container-1",
                "container_name": "aistockcn-full-market-3y-test",
                "status": "running",
                "running_for": None,
                "started_at": None,
                "finished_at": None,
                "exit_code": None,
                "oom_killed": False,
                "is_running": True,
            }

            with mock.patch.object(batch_service, "get_settings", return_value=settings):
                with mock.patch.object(batch_service, "_get_container_info", return_value=container):
                    status = batch_service.get_batch_status()

        self.assertFalse(status["is_stalled"])
        self.assertEqual(status["state_file_updated_at"], status["last_activity_at"])

    def test_paper_targets_hide_noop_zero_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            targets_path = Path(tmp) / "targets_latest.parquet"
            pd.DataFrame(
                [
                    {
                        "signal_date": "2026-05-19",
                        "rank": None,
                        "code": "000010",
                        "name": None,
                        "score": None,
                        "close": 2.73,
                        "target_qty": 0,
                        "current_qty": 0,
                        "delta_qty": None,
                        "buy_order_qty": 0,
                        "sell_order_qty": 0,
                        "action": None,
                        "current_market_value": 0,
                    },
                    {
                        "signal_date": "2026-05-19",
                        "rank": 1,
                        "code": "688496",
                        "name": "*ST清越",
                        "score": 0.89,
                        "close": 1.51,
                        "target_qty": 100,
                        "current_qty": 0,
                        "delta_qty": 100,
                        "buy_order_qty": 100,
                        "sell_order_qty": 0,
                        "action": "BUY",
                        "current_market_value": 0,
                    },
                    {
                        "signal_date": "2026-05-19",
                        "rank": None,
                        "code": "002294",
                        "name": "002294",
                        "score": None,
                        "close": 38.96,
                        "target_qty": 0,
                        "current_qty": 100,
                        "delta_qty": -100,
                        "buy_order_qty": 0,
                        "sell_order_qty": 100,
                        "action": "SELL",
                        "current_market_value": 3896,
                    },
                ]
            ).to_parquet(targets_path, index=False)
            settings = SimpleNamespace(paper_trading_targets_path=targets_path)

            with mock.patch.object(paper_service, "get_settings", return_value=settings):
                result = paper_service.get_paper_trading_targets(limit=10)

        self.assertEqual(result["rows"], 2)
        self.assertEqual([row["code"] for row in result["targets"]], ["688496", "002294"])

    def test_paper_target_persistence_drops_noop_zero_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            targets_path = Path(tmp) / "targets_latest.parquet"
            plan = pd.DataFrame(
                [
                    {
                        "signal_date": "2026-05-19",
                        "rank": None,
                        "code": "000010",
                        "score": None,
                        "close": 2.73,
                        "target_qty": 0,
                        "current_qty": 0,
                        "delta_qty": None,
                        "sell_order_qty": 0,
                        "buy_order_qty": 0,
                        "action": "HOLD",
                        "current_market_value": 0,
                    },
                    {
                        "signal_date": "2026-05-19",
                        "rank": 1,
                        "code": "688496",
                        "score": 0.89,
                        "close": 1.51,
                        "target_qty": 100,
                        "current_qty": 0,
                        "delta_qty": 100,
                        "sell_order_qty": 0,
                        "buy_order_qty": 100,
                        "action": "BUY",
                        "current_market_value": 0,
                    },
                ]
            )

            persist_targets({"targets": targets_path}, plan)
            stored = pd.read_parquet(targets_path)

        self.assertEqual(stored["code"].tolist(), ["688496"])

    def test_transaction_fee_model_matches_a_share_rules(self) -> None:
        self.assertAlmostEqual(transaction_fee("BUY", 10_000.0), 20.4, places=6)
        self.assertAlmostEqual(transaction_fee("SELL", 10_000.0), 25.4, places=6)
        self.assertEqual(transaction_fee("BUY", 0.0), 0.0)

    def test_paper_plan_reserves_buy_fees_before_sizing_order(self) -> None:
        affordable = compute_affordable_buy_quantity(cash_available=1020.0, price=10.0, lot_size=100)
        self.assertEqual(affordable, 0)
        affordable = compute_affordable_buy_quantity(cash_available=1021.0, price=10.0, lot_size=100)
        self.assertEqual(affordable, 100)

    def test_paper_plan_records_estimated_order_fees(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = SyncConfig(
                scores_path=Path(tmp) / "scores.parquet",
                state_dir=Path(tmp),
                gateway_base_url="http://127.0.0.1:8080",
                market="CN",
                agent_id="agent",
                agent_key="key",
                agent_id_header="X-Agent-Id",
                agent_key_header="X-Agent-Key",
                account_id=None,
                top_k=1,
                min_score=0.5,
                lot_size=100,
                cash_buffer_pct=0.0,
                budget_total=None,
                max_order_qty=1000,
                cancel_open_orders=True,
                sync_existing_orders=True,
                force=False,
                dry_run=True,
            )
            latest_scores = pd.DataFrame(
                [
                    {
                        "date": "2026-05-19",
                        "rank": 1,
                        "code": "000001",
                        "exchange": "SZ",
                        "name": "Ping An Bank",
                        "industry": "Bank",
                        "score": 0.9,
                        "close": 10.0,
                    }
                ]
            )

            plan, summary = build_plan(
                config,
                latest_scores=latest_scores,
                positions={},
                balance_metrics={"power": 1021.0, "cash": 1021.0, "total_assets": 1021.0},
            )

        self.assertEqual(int(plan.loc[0, "buy_order_qty"]), 100)
        self.assertAlmostEqual(float(plan.loc[0, "estimated_order_fee"]), 20.04, places=6)
        self.assertAlmostEqual(float(summary["estimated_order_fee"]), 20.04, places=6)

    def test_sina_quote_parser_uses_latest_price_field(self) -> None:
        payload = 'var hq_str_sz000001="平安银行,10.860,10.860,10.770,10.880,10.760,10.770,10.780,74763214";'

        self.assertEqual(sina_quote_code("000001", "SZ"), "sz000001")
        self.assertEqual(sina_quote_code("600519", "SH"), "sh600519")
        self.assertAlmostEqual(parse_sina_quote_price(payload, "sz000001"), 10.77, places=6)

    def test_paper_execution_uses_sina_realtime_price_for_order_price(self) -> None:
        class OrderClient:
            def __init__(self) -> None:
                self.orders: list[dict[str, object]] = []

            def place_order(self, **kwargs: object) -> dict[str, object]:
                self.orders.append(dict(kwargs))
                return {"order_id": "order-1", "order_status": "SUBMITTED"}

        client = OrderClient()
        config = SimpleNamespace(cancel_open_orders=False, max_order_qty=1000)
        plan = pd.DataFrame(
            [
                {
                    "rank": 1,
                    "score": 0.9,
                    "code": "000001",
                    "close": 10.0,
                    "buy_limit_price": 10.0,
                    "sell_limit_price": 10.0,
                    "buy_order_qty": 100,
                    "sell_order_qty": 0,
                }
            ]
        )

        with mock.patch("paper_trade_futu.is_active_trading_hours", return_value=True):
            with mock.patch("paper_trade_futu.get_sina_latest_price", return_value=10.77) as get_price:
                result = execute_plan(client, config, plan=plan, signal_date="2026-05-20", active_orders=[])

        self.assertEqual(len(result["placed_orders"]), 1)
        self.assertEqual(result["skipped_orders"], [])
        get_price.assert_called_once_with("000001", None)
        self.assertEqual(client.orders[0]["symbol"], "000001")
        self.assertEqual(client.orders[0]["price"], 10.88)

    def test_backtest_rebalance_fees_count_buy_and_sell_orders(self) -> None:
        fees = estimate_rebalance_fees(
            previous_symbols={"000001", "000002"},
            next_symbols={"000002", "000003"},
            portfolio_value=10_000.0,
            fee_model=DEFAULT_FEE_MODEL,
        )

        self.assertEqual(fees["buy_count"], 1)
        self.assertEqual(fees["sell_count"], 1)
        self.assertAlmostEqual(float(fees["buy_fee"]), transaction_fee("BUY", 5_000.0), places=6)
        self.assertAlmostEqual(float(fees["sell_fee"]), transaction_fee("SELL", 5_000.0), places=6)

    def test_model_overview_returns_real_profile_equity_curve(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            models_dir = root / "quant_data" / "models"
            backtests_dir = root / "quant_data" / "backtests"
            run_dir = root / "run"
            short_3d_run = backtests_dir / "runs" / "20260518T090118Z__short_3d"
            models_dir.mkdir(parents=True)
            short_3d_run.mkdir(parents=True)
            run_dir.mkdir()
            (models_dir / "training_metadata.json").write_text(
                json.dumps({"profile_name": "short_5d"}),
                encoding="utf-8",
            )
            (short_3d_run / "summary.json").write_text(
                json.dumps(
                    {
                        "run_id": "20260518T090118Z__short_3d",
                        "profile_name": "short_3d",
                        "profile_label": "3D Short",
                        "portfolio_total_return": 0.2,
                    }
                ),
                encoding="utf-8",
            )
            pd.DataFrame(
                [
                    {"rebalance_date": "2026-05-18", "portfolio_return": 0.1, "equity": 1.1, "num_picks": 5},
                    {"rebalance_date": "2026-05-19", "portfolio_return": 0.2, "equity": 1.32, "num_picks": 5},
                ]
            ).to_parquet(short_3d_run / "equity_curve.parquet", index=False)
            settings = SimpleNamespace(models_dir=models_dir, backtests_dir=backtests_dir, run_dir=run_dir, quant_dir=root / "quant_data")

            with mock.patch.object(model_service, "get_settings", return_value=settings):
                with mock.patch.object(model_profiles_service, "get_settings", return_value=settings):
                    overview = model_service.get_model_overview(profile_name="short_3d")

        self.assertEqual(overview["backtest_summary"]["profile_name"], "short_3d")
        self.assertEqual([row["equity"] for row in overview["backtest_equity_curve"]], [1.1, 1.32])

    def test_model_overview_trusts_cost_adjusted_backtest_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            models_dir = root / "quant_data" / "models"
            backtests_dir = root / "quant_data" / "backtests"
            run_dir = root / "run"
            short_3d_run = backtests_dir / "runs" / "20260520T095341Z__short_3d"
            models_dir.mkdir(parents=True)
            short_3d_run.mkdir(parents=True)
            run_dir.mkdir()
            (models_dir / "training_metadata.json").write_text(
                json.dumps({"profile_name": "short_3d"}),
                encoding="utf-8",
            )
            (short_3d_run / "summary.json").write_text(
                json.dumps(
                    {
                        "run_id": "20260520T095341Z__short_3d",
                        "profile_name": "short_3d",
                        "profile_label": "3D Short",
                        "method_version": "purged_label_horizon_costs_v2",
                        "portfolio_total_return": 59.5,
                    }
                ),
                encoding="utf-8",
            )
            pd.DataFrame(
                [{"rebalance_date": "2026-05-20", "portfolio_return": 0.1, "equity": 1.1, "num_picks": 5}]
            ).to_parquet(short_3d_run / "equity_curve.parquet", index=False)
            settings = SimpleNamespace(models_dir=models_dir, backtests_dir=backtests_dir, run_dir=run_dir, quant_dir=root / "quant_data")

            with mock.patch.object(model_service, "get_settings", return_value=settings):
                with mock.patch.object(model_profiles_service, "get_settings", return_value=settings):
                    overview = model_service.get_model_overview(profile_name="short_3d")

        self.assertTrue(overview["backtest_summary"]["is_trustworthy"])
        self.assertNotIn("trust_warning", overview["backtest_summary"])

    def test_backtest_metric_helpers_report_drawdown_and_annualized_return(self) -> None:
        equity = pd.Series([1.0, 1.2, 0.9, 1.5])
        dates = pd.Series(pd.to_datetime(["2025-01-01", "2025-04-01", "2025-07-01", "2026-01-01"]))

        self.assertAlmostEqual(max_drawdown(equity), -0.25)
        self.assertGreater(annualized_return(equity, dates), 0.45)

    def test_backtest_training_split_purges_label_horizon(self) -> None:
        dates = pd.Index(pd.to_datetime(["2026-05-11", "2026-05-12", "2026-05-13", "2026-05-14", "2026-05-15"]))

        cutoff = training_end_for_rebalance(dates, dates[4], label_horizon=2)

        self.assertEqual(pd.Timestamp(cutoff).date().isoformat(), "2026-05-13")

    def test_model_overview_does_not_mix_training_and_backtest_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            models_dir = root / "quant_data" / "models"
            backtests_dir = root / "quant_data" / "backtests"
            run_dir = root / "run"
            models_dir.mkdir(parents=True)
            (backtests_dir / "runs" / "latest_short_3d").mkdir(parents=True)
            run_dir.mkdir()
            (models_dir / "training_metadata.json").write_text(
                '{"profile_name":"short_5d","metrics":{"auc":0.59}}\n',
                encoding="utf-8",
            )
            short_3d_summary = (
                '{"profile_name":"short_3d","profile_label":"3D Short",'
                '"portfolio_total_return":82.21915197894047}\n'
            )
            (backtests_dir / "summary.json").write_text(short_3d_summary, encoding="utf-8")
            (backtests_dir / "runs" / "latest_short_3d" / "summary.json").write_text(short_3d_summary, encoding="utf-8")
            settings = SimpleNamespace(models_dir=models_dir, backtests_dir=backtests_dir, run_dir=run_dir, quant_dir=root / "quant_data")

            with mock.patch.object(model_service, "get_settings", return_value=settings):
                with mock.patch.object(model_profiles_service, "get_settings", return_value=settings):
                    overview = model_service.get_model_overview()

        self.assertEqual(overview["current_profile"], "short_5d")
        self.assertEqual(overview["backtest_summary"], {})
        self.assertEqual(overview["backtest_runs"][0]["profile_name"], "short_3d")

    def test_model_overview_selected_profile_syncs_all_model_panels(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            models_dir = root / "quant_data" / "models"
            backtests_dir = root / "quant_data" / "backtests"
            profile_model_dir = root / "quant_data" / "model_profiles" / "short_3d" / "models"
            run_dir = root / "run"
            models_dir.mkdir(parents=True)
            profile_model_dir.mkdir(parents=True)
            (backtests_dir / "runs" / "latest_short_3d").mkdir(parents=True)
            run_dir.mkdir()
            (models_dir / "training_metadata.json").write_text(
                '{"profile_name":"short_5d","metrics":{"auc":0.59}}\n',
                encoding="utf-8",
            )
            (profile_model_dir / "training_metadata.json").write_text(
                '{"profile_name":"short_3d","metrics":{"auc":0.61},"train_rows":123}\n',
                encoding="utf-8",
            )
            (profile_model_dir / "feature_importance.csv").write_text(
                "feature,importance_gain,importance_split\npct_chg,10,2\n",
                encoding="utf-8",
            )
            short_3d_summary = (
                '{"profile_name":"short_3d","profile_label":"3D Short",'
                '"portfolio_total_return":82.21915197894047}\n'
            )
            (backtests_dir / "runs" / "latest_short_3d" / "summary.json").write_text(short_3d_summary, encoding="utf-8")
            settings = SimpleNamespace(models_dir=models_dir, backtests_dir=backtests_dir, run_dir=run_dir, quant_dir=root / "quant_data")

            with mock.patch.object(model_service, "get_settings", return_value=settings):
                with mock.patch.object(model_profiles_service, "get_settings", return_value=settings):
                    overview = model_service.get_model_overview(profile_name="short_3d")

        self.assertEqual(overview["current_profile"], "short_3d")
        self.assertEqual(overview["training_metadata"]["profile_name"], "short_3d")
        self.assertEqual(overview["top_features"][0]["feature"], "pct_chg")
        self.assertEqual(overview["backtest_summary"]["profile_name"], "short_3d")

    def test_latest_picks_can_read_profile_specific_scores(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            models_dir = root / "quant_data" / "models"
            profile_model_dir = root / "quant_data" / "model_profiles" / "short_3d" / "models"
            backtests_dir = root / "quant_data" / "backtests"
            run_dir = root / "run"
            profile_model_dir.mkdir(parents=True)
            models_dir.mkdir(parents=True)
            backtests_dir.mkdir(parents=True)
            run_dir.mkdir()
            pd.DataFrame(
                [
                    {"date": "2026-05-20", "code": "000001", "name": "A", "industry": "Bank", "score": 0.8, "close": 10.0},
                    {"date": "2026-05-20", "code": "000002", "name": "B", "industry": "Tech", "score": 0.9, "close": 20.0},
                ]
            ).to_parquet(profile_model_dir / "inference_scores_latest.parquet", index=False)
            settings = SimpleNamespace(
                models_dir=models_dir,
                backtests_dir=backtests_dir,
                run_dir=run_dir,
                quant_dir=root / "quant_data",
                stock_list_path=root / "missing_stock_list.parquet",
                stock_registry_path=root / "missing_stock_registry.parquet",
            )

            with mock.patch.object(model_service, "get_settings", return_value=settings):
                with mock.patch.object(model_profiles_service, "get_settings", return_value=settings):
                    picks = model_service.get_latest_picks(limit=1, profile_name="short_3d")

        self.assertEqual(picks["profile_name"], "short_3d")
        self.assertEqual(picks["picks"][0]["code"], "000002")

    def test_activate_model_for_paper_syncs_profile_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            models_dir = root / "quant_data" / "models"
            profile_model_dir = root / "quant_data" / "model_profiles" / "short_3d" / "models"
            backtests_dir = root / "quant_data" / "backtests"
            run_dir = root / "run"
            profile_model_dir.mkdir(parents=True)
            models_dir.mkdir(parents=True)
            backtests_dir.mkdir(parents=True)
            run_dir.mkdir()
            (run_dir / "model_profiles.json").write_text(
                json.dumps(
                    {
                        "default_profile": "short_5d",
                        "profiles": [
                            {"name": "short_5d", "label": "5D Short"},
                            {"name": "short_3d", "label": "3D Short"},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (profile_model_dir / "training_metadata.json").write_text('{"profile_name":"short_3d"}\n', encoding="utf-8")
            (profile_model_dir / "inference_scores_latest.parquet").write_bytes(b"score-bytes")
            (profile_model_dir / "feature_importance.csv").write_text("feature,importance_gain\nx,1\n", encoding="utf-8")
            settings = SimpleNamespace(models_dir=models_dir, backtests_dir=backtests_dir, run_dir=run_dir, quant_dir=root / "quant_data")

            with mock.patch.object(model_service, "get_settings", return_value=settings):
                with mock.patch.object(model_profiles_service, "get_settings", return_value=settings):
                    result = model_service.activate_model_for_paper("short_3d")

            self.assertEqual(result["profile_name"], "short_3d")
            self.assertEqual((models_dir / "training_metadata.json").read_text(encoding="utf-8").strip(), '{"profile_name":"short_3d"}')
            self.assertEqual((models_dir / "inference_scores_latest.parquet").read_bytes(), b"score-bytes")
            self.assertEqual(json.loads((run_dir / "model_profiles.json").read_text(encoding="utf-8"))["active_profile"], "short_3d")

    def test_model_overview_does_not_default_unprofiled_backtest_to_current_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            models_dir = root / "quant_data" / "models"
            backtests_dir = root / "quant_data" / "backtests"
            run_dir = root / "run"
            models_dir.mkdir(parents=True)
            backtests_dir.mkdir(parents=True)
            run_dir.mkdir()
            (models_dir / "training_metadata.json").write_text(
                '{"profile_name":"short_5d","metrics":{"auc":0.59}}\n',
                encoding="utf-8",
            )
            (backtests_dir / "summary.json").write_text(
                '{"portfolio_total_return":82.21915197894047}\n',
                encoding="utf-8",
            )
            settings = SimpleNamespace(models_dir=models_dir, backtests_dir=backtests_dir, run_dir=run_dir, quant_dir=root / "quant_data")

            with mock.patch.object(model_service, "get_settings", return_value=settings):
                with mock.patch.object(model_profiles_service, "get_settings", return_value=settings):
                    overview = model_service.get_model_overview()

        self.assertEqual(overview["current_profile"], "short_5d")
        self.assertEqual(overview["backtest_summary"], {})

    def test_legacy_provider_logs_are_translated_before_display(self) -> None:
        line = "\u8bf7\u6c42\u5931\u8d25\uff0c1.0 \u79d2\u540e\u91cd\u8bd5 (1/3): timeout"

        self.assertEqual(translate_log_line(line), "Request failed, retrying in 1.0s (1/3): timeout")

    def test_public_ui_sources_are_english_only(self) -> None:
        checked_roots = [ROOT / "apps" / "web" / "app", ROOT / "apps" / "web" / "lib"]
        offenders: list[str] = []
        for root in checked_roots:
            for path in root.rglob("*.ts*"):
                text = path.read_text(encoding="utf-8")
                if any("\u4e00" <= char <= "\u9fff" for char in text):
                    offenders.append(str(path.relative_to(ROOT)))

        self.assertEqual(offenders, [])

    def test_results_doc_uses_aggregate_metrics_only(self) -> None:
        results_doc = (ROOT / "docs" / "RESULTS.md").read_text(encoding="utf-8")

        self.assertIn("Production Research Results", results_doc)
        self.assertIn("Validation AUC", results_doc)
        self.assertIn("Walk-Forward OOS Backtest", results_doc)
        self.assertNotIn("FUTU_GATEWAY", results_doc)
        self.assertNotIn("account_id", results_doc.lower())


if __name__ == "__main__":
    unittest.main()
