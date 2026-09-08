from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from paper_trade_futu import (  # noqa: E402
    SyncConfig,
    quant_dir_for_scores_path,
    score_file_signature,
    score_trading_dates,
    sync_once,
)


class PaperRebalanceCalendarTests(unittest.TestCase):
    def test_registry_score_uses_market_calendar_to_recover_missed_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            quant_dir = Path(tmp) / "quant_data"
            scores_path = (
                quant_dir
                / "model_registry"
                / "CN"
                / "candidate-v2"
                / "inference_scores_latest.parquet"
            )
            calendar_path = quant_dir / "daily_kline" / "000001.parquet"
            scores_path.parent.mkdir(parents=True)
            calendar_path.parent.mkdir(parents=True)
            pd.DataFrame([{"date": "2026-09-08", "score": 0.9}]).to_parquet(scores_path, index=False)
            pd.DataFrame(
                [
                    {"date": "2026-09-01"},
                    {"date": "2026-09-02"},
                    {"date": "2026-09-03"},
                    {"date": "2026-09-04"},
                    {"date": "2026-09-07"},
                    {"date": "2026-09-08"},
                ]
            ).to_parquet(calendar_path, index=False)

            dates = score_trading_dates(scores_path)

        self.assertEqual(quant_dir_for_scores_path(scores_path), quant_dir)
        self.assertEqual(
            dates,
            ["2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04", "2026-09-07", "2026-09-08"],
        )

    def test_recovered_due_snapshot_is_not_blocked_by_previous_signature(self) -> None:
        class Gateway:
            def __init__(self, _config: SyncConfig) -> None:
                pass

            def health(self):
                return {"status": "ok"}

            def sync_agent(self):
                return None

            def get_agent_positions(self):
                return []

            def get_agent_orders(self):
                return []

            def get_balance(self):
                return [{"cash": 100_000, "power": 100_000, "total_assets": 100_000}]

            def get_agent_summary(self):
                return {"total_assets": 100_000, "total_pnl": 0}

        with tempfile.TemporaryDirectory() as tmp:
            quant_dir = Path(tmp) / "quant_data"
            scores_path = quant_dir / "model_registry" / "CN" / "candidate-v2" / "inference_scores_latest.parquet"
            state_dir = quant_dir / "paper_trading"
            calendar_path = quant_dir / "daily_kline" / "000001.parquet"
            scores_path.parent.mkdir(parents=True)
            state_dir.mkdir(parents=True)
            calendar_path.parent.mkdir(parents=True)
            pd.DataFrame(
                [
                    {
                        "date": "2026-09-08",
                        "code": "000001",
                        "exchange": "SZ",
                        "name": "A",
                        "industry": "Bank",
                        "score": 0.9,
                        "close": 10.0,
                        "amount": 100_000_000.0,
                    }
                ]
            ).to_parquet(scores_path, index=False)
            pd.DataFrame(
                [{"date": value} for value in ["2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04", "2026-09-07", "2026-09-08"]]
            ).to_parquet(calendar_path, index=False)
            (scores_path.parent / "training_metadata.json").write_text(
                json.dumps({"profile_name": "medium_10d_v2", "label_horizon": 10}), encoding="utf-8"
            )
            signature = score_file_signature(scores_path)
            (state_dir / "state.json").write_text(
                json.dumps(
                    {
                        "last_applied_signal_date": "2026-09-01",
                        "last_score_signature": signature,
                    }
                ),
                encoding="utf-8",
            )
            config = SyncConfig(
                scores_path=scores_path,
                state_dir=state_dir,
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
                budget_total=100_000.0,
                max_buy_order_qty=1000,
                max_sell_order_qty=1000,
                cancel_open_orders=True,
                sync_existing_orders=True,
                force=False,
                dry_run=True,
            )
            plan = pd.DataFrame(
                [
                    {
                        "code": "000001",
                        "rank": 1,
                        "score": 0.9,
                        "buy_order_qty": 100,
                        "sell_order_qty": 0,
                        "action": "BUY",
                    }
                ]
            )
            with (
                mock.patch("paper_trade_futu.GatewayClient", Gateway),
                mock.patch(
                    "paper_trade_futu.build_plan",
                    return_value=(plan, {"buy_order_count": 1, "sell_order_count": 0}),
                ),
            ):
                code, state = sync_once(config)

        self.assertEqual(code, 0)
        self.assertEqual(state["last_status"], "dry_run")
        self.assertTrue(state["rebalance_due"])
        self.assertEqual(state["rebalance_wait_count"], 5)


if __name__ == "__main__":
    unittest.main()
