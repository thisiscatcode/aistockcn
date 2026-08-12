from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.services import research as research_service
from app.services import research_chunking as research_chunking_service


class ResearchServiceTests(unittest.TestCase):
    def test_page_chunking_preserves_page_boundaries_and_overlap(self) -> None:
        text = " ".join(f"token-{index}" for index in range(500))
        chunks = research_chunking_service.chunk_page_text(text, chunk_size=180, overlap=30)
        self.assertGreater(len(chunks), 2)
        self.assertTrue(all(len(chunk) <= 180 for chunk in chunks))
        self.assertIn(chunks[0].split()[-1], chunks[1])

    def test_normalize_symbol_rejects_unsafe_values(self) -> None:
        self.assertEqual(research_service.normalize_us_symbol(" nvda "), "NVDA")
        with self.assertRaises(research_service.ResearchError):
            research_service.normalize_us_symbol("NVDA; drop table")

    def test_market_calculations_use_descending_history(self) -> None:
        history = [{"close": value} for value in [110, 100, 90, 80, 70, 55]]
        result = research_service._market_calculations(history)
        self.assertEqual(result["return_1d_pct"], 10.0)
        self.assertEqual(result["return_5d_pct"], 100.0)
        self.assertIsNotNone(result["annualized_volatility_pct"])

    def test_answer_keeps_data_evidence_separate_from_model_inference(self) -> None:
        history = [
            {"trade_date": f"2026-08-{10 - index:02d}", "close": 100 - index}
            for index in range(10)
        ]
        snapshot = {
            "company": {
                "symbol": "NVDA",
                "stock_name": "NVIDIA Corporation",
                "trade_date": "2026-08-10",
                "close": 100,
                "price_diff": 1.5,
                "volume": 1234,
                "pe_ratio": 30,
                "earnings_per_share": 3.2,
            },
            "history": history,
        }
        settings = SimpleNamespace(research_llm_model="qwen2.5:3b")
        with (
            mock.patch.object(research_service, "get_company_snapshot", return_value=snapshot),
            mock.patch.object(research_service, "get_settings", return_value=settings),
            mock.patch.object(
                research_service,
                "_retrieve_document_evidence",
                return_value={"results": [], "retrieval": {"indexed_documents": 0}},
            ),
            mock.patch.object(
                research_service,
                "_generate_research_synthesis",
                return_value={"answer": "Market-data answer.", "model_inference": ["Momentum is positive."]},
            ),
        ):
            result = research_service.answer_research_question(
                symbol="nvda",
                question="What can the current evidence support?",
                tool_plan={
                    "tools": list(research_service.RESEARCH_TOOLS),
                    "reason": "test plan",
                    "planner": "test",
                },
            )

        self.assertEqual(result["symbol"], "NVDA")
        self.assertEqual(result["document_evidence"], [])
        self.assertEqual(len(result["data_evidence"]), 3)
        self.assertEqual(result["model_inference"], ["Momentum is positive."])
        self.assertEqual([step["tool"] for step in result["agent_steps"]], [
            "agent_planner",
            "company_lookup",
            "market_history",
            "financial_calculator",
            "hybrid_document_search",
            "evidence_synthesis",
        ])

    def test_structured_planner_drops_unknown_tools(self) -> None:
        with mock.patch.object(
            research_service,
            "_call_local_json_model",
            return_value={
                "tools": ["company_lookup", "shell_exec", "hybrid_document_search", "shell_exec"],
                "reason": "Use company and filing evidence.",
            },
        ):
            plan = research_service.plan_research_tools(
                question="What filing risks matter?",
                settings=SimpleNamespace(),
            )
        self.assertEqual(plan["tools"], ["company_lookup", "hybrid_document_search"])
        self.assertNotIn("shell_exec", plan["tools"])


if __name__ == "__main__":
    unittest.main()
