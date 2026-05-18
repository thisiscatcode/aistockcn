from __future__ import annotations

import sys
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
from backtest_walk_forward import annualized_return, max_drawdown
from build_inference_features import build_inference_frame
from download_data import build_valuation_df
from app.services import batch as batch_service
from app.services import model as model_service
from app.services import model_profiles as model_profiles_service
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

    def test_backtest_metric_helpers_report_drawdown_and_annualized_return(self) -> None:
        equity = pd.Series([1.0, 1.2, 0.9, 1.5])
        dates = pd.Series(pd.to_datetime(["2025-01-01", "2025-04-01", "2025-07-01", "2026-01-01"]))

        self.assertAlmostEqual(max_drawdown(equity), -0.25)
        self.assertGreater(annualized_return(equity, dates), 0.45)

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
            settings = SimpleNamespace(models_dir=models_dir, backtests_dir=backtests_dir, run_dir=run_dir)

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
            run_dir = root / "run"
            models_dir.mkdir(parents=True)
            (backtests_dir / "runs" / "latest_short_3d").mkdir(parents=True)
            run_dir.mkdir()
            (models_dir / "training_metadata.json").write_text(
                '{"profile_name":"short_5d","metrics":{"auc":0.59}}\n',
                encoding="utf-8",
            )
            (models_dir / "feature_importance.csv").write_text(
                "feature,importance_gain,importance_split\npct_chg,10,2\n",
                encoding="utf-8",
            )
            short_3d_summary = (
                '{"profile_name":"short_3d","profile_label":"3D Short",'
                '"portfolio_total_return":82.21915197894047}\n'
            )
            (backtests_dir / "runs" / "latest_short_3d" / "summary.json").write_text(short_3d_summary, encoding="utf-8")
            settings = SimpleNamespace(models_dir=models_dir, backtests_dir=backtests_dir, run_dir=run_dir)

            with mock.patch.object(model_service, "get_settings", return_value=settings):
                with mock.patch.object(model_profiles_service, "get_settings", return_value=settings):
                    overview = model_service.get_model_overview(profile_name="short_3d")

        self.assertEqual(overview["current_profile"], "short_3d")
        self.assertEqual(overview["training_metadata"], {})
        self.assertEqual(overview["top_features"], [])
        self.assertEqual(overview["backtest_summary"]["profile_name"], "short_3d")

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
            settings = SimpleNamespace(models_dir=models_dir, backtests_dir=backtests_dir, run_dir=run_dir)

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
