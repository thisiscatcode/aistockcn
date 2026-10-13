from datetime import datetime
import tempfile
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "apps" / "api")]
from app.services import auto_pipeline, source_readiness, batch
from paper_trade_futu import StaleSignalError, require_current_paper_signal, sync_once
from active_model_inference import StaleInferenceError


class CatchupTests(unittest.TestCase):
    def test_slow_universe_has_independent_budget_and_keeps_verified_date(self):
        with mock.patch.object(source_readiness, "bs", object()), mock.patch.object(source_readiness, "ak", object()), mock.patch.object(
            source_readiness, "_run_provider_probe", side_effect=[
                ("2026-10-12", True), "2026-10-12",
                {"latest_date": "2026-10-12", "row_count": 7425, "ready": True}, "2026-10-12",
            ],
        ) as probe:
            result = source_readiness.get_china_market_data_readiness(local_date="2026-10-12")
        self.assertTrue(result["ready"])
        self.assertEqual(probe.call_args_list[2].kwargs["timeout_seconds"], 90)

    def test_universe_timeout_keeps_calendar_and_daily_evidence(self):
        with mock.patch.object(source_readiness, "bs", object()), mock.patch.object(source_readiness, "ak", object()), mock.patch.object(
            source_readiness, "_run_provider_probe", side_effect=[
                ("2026-10-12", True), "2026-10-12",
                source_readiness.ProviderProbeTimeoutError("universe timeout"),
            ],
        ):
            result = source_readiness.get_china_market_data_readiness(local_date="2026-10-12")
        self.assertFalse(result["ready"])
        self.assertTrue(result["is_trading_day"])
        self.assertEqual(result["expected_trade_date"], "2026-10-12")
        self.assertEqual(result["baostock"]["daily_kline_date"], "2026-10-12")
        self.assertEqual(result["baostock"]["failed_probe"], "all_stock")

    def test_morning_scheduler_catches_up_previous_session(self):
        settings = SimpleNamespace(pipeline_auto_run_time="18:00", pipeline_auto_run_timezone="Asia/Shanghai")
        with mock.patch.object(auto_pipeline, "get_settings", return_value=settings), mock.patch.object(auto_pipeline, "_read_state", return_value={"last_trigger_trade_date": "2026-10-09"}), mock.patch.object(auto_pipeline, "_local_now", return_value=datetime.fromisoformat("2026-10-13T10:00:00+08:00")), mock.patch.object(auto_pipeline, "expected_china_signal_date", return_value="2026-10-12"), mock.patch.object(auto_pipeline, "_latest_score_date", return_value="2026-10-09"), mock.patch.object(auto_pipeline, "get_pipeline_run_status", return_value={"is_running": False, "status": "completed"}), mock.patch.object(auto_pipeline, "get_china_market_data_readiness", return_value={"ready": True, "is_trading_day": True, "expected_trade_date": "2026-10-12"}) as readiness, mock.patch.object(auto_pipeline, "start_pipeline_run", return_value={"ok": True}) as start, mock.patch.object(auto_pipeline, "_write_state") as write:
            auto_pipeline._maybe_start_pipeline()
        readiness.assert_called_once_with(local_date="2026-10-12")
        start.assert_called_once_with(trade_date="2026-10-12")
        self.assertEqual(write.call_args.args[0]["catchup_trade_date"], "2026-10-12")

    def test_downloader_uses_explicit_catchup_date(self):
        with mock.patch.object(batch, "get_settings", return_value=SimpleNamespace(state_file=Path("/nonexistent"))), mock.patch.dict("os.environ", {"PIPELINE_TARGET_TRADE_DATE": "2026-10-12"}):
            args = batch._default_batch_args()
        self.assertEqual(args["start_date"], "20261012")
        self.assertEqual(args["end_date"], "20261012")

    def test_freshness_checks_calendar_even_when_market_files_are_also_stale(self):
        config = SimpleNamespace(market="CN", paper_db_url="configured", scores_path=ROOT / "quant_data/model_inference/CN/model/2026-10-09/inference_scores_latest.parquet")
        with mock.patch("paper_trade_futu.expected_signal_date", return_value="2026-10-12"):
            with self.assertRaisesRegex(StaleSignalError, "expected 2026-10-12"):
                require_current_paper_signal(config, "2026-10-09")
            require_current_paper_signal(config, "2026-10-12")
        with mock.patch("paper_trade_futu.expected_signal_date", return_value=None):
            with self.assertRaisesRegex(StaleSignalError, "calendar is unavailable"):
                require_current_paper_signal(config, "2026-10-12")

    def test_stale_snapshot_cannot_contact_gateway_even_with_unchanged_signature(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = SimpleNamespace(
                state_dir=Path(tmp) / "paper", market="CN", paper_db_url="configured",
                scores_path=Path(tmp) / "quant_data/model_inference/CN/model/day/inference_scores_latest.parquet",
            )
            with mock.patch("paper_trade_futu.resolve_paper_model", return_value=(config, {})), mock.patch("paper_trade_futu.load_latest_scores", return_value=(None, "2026-10-09", "unchanged")), mock.patch("paper_trade_futu.expected_signal_date", return_value="2026-10-12"), mock.patch("paper_trade_futu.GatewayClient") as gateway:
                code, state = sync_once(config)
            self.assertEqual(code, 0)
            self.assertEqual(state["last_status"], "blocked")
            gateway.assert_not_called()

    def test_partial_pipeline_updates_block_without_error_ledger_or_gateway_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = SimpleNamespace(state_dir=Path(tmp) / "paper")
            with mock.patch("paper_trade_futu.resolve_paper_model", side_effect=StaleInferenceError("inference features are stale")), mock.patch("paper_trade_futu.GatewayClient") as gateway, mock.patch("paper_trade_futu.record_sync_history") as history:
                code, state = sync_once(config)
            self.assertEqual(code, 0)
            self.assertEqual(state["last_status"], "blocked")
            gateway.assert_not_called()
            history.assert_not_called()


if __name__ == "__main__":
    unittest.main()
