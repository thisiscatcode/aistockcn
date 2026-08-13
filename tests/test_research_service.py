from __future__ import annotations

import sys
import unittest
import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.services import research as research_service
from app.services import research_chunking as research_chunking_service
from app.services import research_financials as research_financials_service
from app.services import research_filing_changes as research_filing_changes_service
from app.services import research_sec as research_sec_service


class ResearchServiceTests(unittest.TestCase):
    def _filing_pair(self, *, older: str, newer: str, similarity: float) -> dict[str, object]:
        return {
            "older_chunk_id": "old-chunk",
            "older_document_id": "old-document",
            "older_page_number": 8,
            "older_locator_type": "page",
            "older_locator": "page 8",
            "older_content": older,
            "older_filename": "FY2024.pdf",
            "older_document_type": "annual_report",
            "older_filing_date": date(2025, 2, 1),
            "older_fiscal_year": 2024,
            "older_source_url": "https://example.com/2024.pdf",
            "older_native_page_numbers": True,
            "newer_chunk_id": "new-chunk",
            "newer_document_id": "new-document",
            "newer_page_number": 11,
            "newer_locator_type": "page",
            "newer_locator": "page 11",
            "newer_content": newer,
            "newer_filename": "FY2025.pdf",
            "newer_document_type": "annual_report",
            "newer_filing_date": date(2026, 2, 1),
            "newer_fiscal_year": 2025,
            "newer_source_url": "https://example.com/2025.pdf",
            "newer_native_page_numbers": True,
            "similarity_score": similarity,
        }

    def test_filing_change_detection_keeps_bilateral_source_evidence(self) -> None:
        older = "Customer demand may fluctuate and could affect revenue. " * 8
        newer = "A severe and increasingly significant demand decline will materially adversely affect revenue. " * 8
        candidates = research_filing_changes_service.build_change_candidates([
            (self._filing_pair(older=older, newer=newer, similarity=0.72), "older_to_newer")
        ])
        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertEqual(candidate["change_type"], "strengthened")
        self.assertEqual(candidate["older_evidence"]["document_id"], "old-document")
        self.assertEqual(candidate["older_evidence"]["page_number"], 8)
        self.assertEqual(candidate["newer_evidence"]["document_id"], "new-document")
        self.assertEqual(candidate["newer_evidence"]["page_number"], 11)
        self.assertIn("pending until a person", candidate["rationale"])

    def test_filing_change_detection_is_reproducible_and_ignores_unchanged_text(self) -> None:
        text = "Cybersecurity risk may materially affect operations and customer trust. " * 8
        pair = self._filing_pair(older=text, newer=text, similarity=0.999)
        first = research_filing_changes_service.build_change_candidates([(pair, "older_to_newer")])
        second = research_filing_changes_service.build_change_candidates([(pair, "older_to_newer")])
        self.assertEqual(first, second)
        self.assertEqual(first, [])

    def test_filing_change_detection_classifies_additions_and_deletions_by_direction(self) -> None:
        older = "Competition risk may reduce market share and adversely affect revenue. " * 8
        newer = "Cybersecurity threats could materially disrupt operations and customer data. " * 8
        pair = self._filing_pair(older=older, newer=newer, similarity=0.31)
        deleted = research_filing_changes_service.build_change_candidates([(pair, "older_to_newer")])
        added = research_filing_changes_service.build_change_candidates([(pair, "newer_to_older")])
        self.assertEqual(deleted[0]["change_type"], "deleted")
        self.assertEqual(added[0]["change_type"], "added")
        self.assertEqual(deleted[0]["older_evidence"]["document_id"], "old-document")
        self.assertEqual(added[0]["newer_evidence"]["document_id"], "new-document")

    def test_filing_change_detection_requires_relevant_disclosure_topic(self) -> None:
        older = "The registered office is located at the following postal address. " * 8
        newer = "The mailing address uses a different building and postal code. " * 8
        candidates = research_filing_changes_service.build_change_candidates([
            (self._filing_pair(older=older, newer=newer, similarity=0.2), "older_to_newer")
        ])
        self.assertEqual(candidates, [])

    def test_sec_companyfacts_normalization_preserves_numeric_lineage(self) -> None:
        payload = {
            "entityName": "Example Corporation",
            "facts": {
                "us-gaap": {
                    "RevenueFromContractWithCustomerExcludingAssessedTax": {
                        "label": "Revenue",
                        "description": "Revenue from contracts with customers.",
                        "units": {
                            "USD": [
                                {
                                    "start": "2024-01-01", "end": "2024-12-31", "val": 1000,
                                    "accn": "0000000001-25-000001", "fy": 2024, "fp": "FY",
                                    "form": "10-K", "filed": "2025-02-01", "frame": "CY2024",
                                },
                                {
                                    "start": "2025-01-01", "end": "2025-03-31", "val": 300,
                                    "accn": "0000000001-25-000002", "fy": 2025, "fp": "Q1",
                                    "form": "10-Q", "filed": "2025-05-01", "frame": "CY2025Q1",
                                },
                            ]
                        },
                    },
                    "Assets": {
                        "label": "Assets",
                        "description": "Total assets.",
                        "units": {
                            "USD": [{
                                "end": "2024-12-31", "val": 2500,
                                "accn": "0000000001-25-000001", "fy": 2024, "fp": "FY",
                                "form": "10-K", "filed": "2025-02-01", "frame": "CY2024Q4I",
                            }]
                        },
                    },
                }
            },
        }
        rows = research_financials_service.normalize_companyfacts_payload(
            symbol="aapl", cik="0000320193", payload=payload
        )
        self.assertEqual(len(rows), 3)
        annual = next(row for row in rows if row["period_kind"] == "annual")
        quarter = next(row for row in rows if row["period_kind"] == "quarter")
        instant = next(row for row in rows if row["period_kind"] == "instant")
        self.assertEqual(annual["metric"], "revenue")
        self.assertEqual(annual["value"], 1000)
        self.assertEqual(quarter["fiscal_period"], "Q1")
        self.assertEqual(instant["metric"], "assets")
        self.assertIn("0000000001-25-000001-index.html", annual["source_url"])
        self.assertEqual(annual["taxonomy"], "us-gaap")
        self.assertEqual(annual["concept"], "RevenueFromContractWithCustomerExcludingAssessedTax")

    def test_financial_period_calculates_margins_and_free_cash_flow(self) -> None:
        base = {
            "concept_priority": 0,
            "taxonomy": "us-gaap",
            "unit": "USD",
            "start_date": date(2024, 1, 1),
            "end_date": date(2024, 12, 31),
            "period_kind": "annual",
            "fiscal_year": 2024,
            "fiscal_period": "FY",
            "form": "10-K",
            "filed_date": date(2025, 2, 1),
            "accession_number": "0000000001-25-000001",
            "source_url": "https://www.sec.gov/example",
        }
        values = {
            "revenue": ("Revenue", "Revenue", 1000),
            "gross_profit": ("Gross profit", "GrossProfit", 400),
            "operating_income": ("Operating income", "OperatingIncomeLoss", 200),
            "net_income": ("Net income", "NetIncomeLoss", 150),
            "operating_cash_flow": ("Operating cash flow", "NetCashProvidedByUsedInOperatingActivities", 250),
            "capital_expenditure": ("Capital expenditure", "PaymentsToAcquirePropertyPlantAndEquipment", 80),
        }
        period = research_financials_service._period_record([
            {**base, "metric": metric, "metric_label": label, "concept": concept, "value": value}
            for metric, (label, concept, value) in values.items()
        ])
        self.assertEqual(period["derived"]["gross_margin_pct"], 40.0)
        self.assertEqual(period["derived"]["operating_margin_pct"], 20.0)
        self.assertEqual(period["derived"]["net_margin_pct"], 15.0)
        self.assertEqual(period["derived"]["free_cash_flow"], 170.0)

    def test_financial_answer_is_deterministic_and_source_grounded(self) -> None:
        locator = "us-gaap:Revenue · 10-K FY2025 · accession 0001"
        summary = {
            "latest_annual": {
                "fiscal_year": 2025,
                "end_date": date(2025, 12, 31),
                "metrics": {
                    "revenue": {"label": "Revenue", "value": 125_000_000_000, "unit": "USD", "locator": locator},
                    "net_income": {"label": "Net income", "value": 25_000_000_000, "unit": "USD", "locator": "net-income-locator"},
                },
                "derived": {"gross_margin_pct": 45.5, "operating_margin_pct": 30.0, "net_margin_pct": 20.0},
            },
            "annual_changes": {
                "revenue": 8.25,
                "net_income": -2.5,
                "gross_margin_pct": 1.25,
                "operating_margin_pct": -0.5,
                "net_margin_pct": -2.0,
            },
        }
        answer = research_service._deterministic_financial_answer(
            summary=summary, question="How did annual revenue, income and margins change?"
        )
        self.assertIn("$125.00 billion", answer)
        self.assertIn("up 8.25%", answer)
        self.assertIn("down 2.50%", answer)
        self.assertIn("Gross margin was 45.50%", answer)
        self.assertIn("up 1.25 percentage points", answer)
        self.assertIn(locator, answer)

    def test_financial_only_plan_uses_xbrl_without_document_search(self) -> None:
        with mock.patch.object(
            research_service,
            "_call_local_json_model",
            return_value={
                "tools": ["company_lookup", "hybrid_document_search"],
                "reason": "Retrieve financial evidence.",
            },
        ):
            plan = research_service.plan_research_tools(
                question="How did annual revenue and net income change?",
                settings=SimpleNamespace(),
            )
        self.assertIn("sec_financial_facts", plan["tools"])
        self.assertNotIn("hybrid_document_search", plan["tools"])

    def test_sec_html_extraction_omits_hidden_and_executable_content(self) -> None:
        payload = b"""
        <html><body>
          <h1>Risk Factors</h1>
          <script>secret_script_text()</script>
          <div style="display: none"><span>hidden fact</span></div>
          <ix:hidden><span>hidden xbrl fact</span></ix:hidden>
          <p>Revenue declined because demand softened.</p>
        </body></html>
        """
        text = research_sec_service.extract_sec_filing_text(payload)
        self.assertIn("Risk Factors", text)
        self.assertIn("Revenue declined because demand softened.", text)
        self.assertNotIn("secret_script_text", text)
        self.assertNotIn("hidden fact", text)
        self.assertNotIn("hidden xbrl fact", text)

    def test_sec_discovery_builds_official_archive_lineage(self) -> None:
        submissions = {
            "name": "Example Corporation",
            "filings": {
                "recent": {
                    "accessionNumber": ["0000320193-25-000079", "0000320193-25-000057"],
                    "filingDate": ["2025-10-31", "2025-08-01"],
                    "reportDate": ["2025-09-27", "2025-06-28"],
                    "form": ["10-K", "10-Q"],
                    "primaryDocument": ["example-20250927.htm", "example-20250628.htm"],
                    "primaryDocDescription": ["10-K", "10-Q"],
                    "isXBRL": [1, 1],
                    "isInlineXBRL": [1, 1],
                }
            },
        }
        with (
            mock.patch.object(research_sec_service, "_ticker_cik_map", return_value={"AAPL": "0000320193"}),
            mock.patch.object(
                research_sec_service,
                "_sec_request",
                return_value=json.dumps(submissions).encode("utf-8"),
            ) as request_mock,
        ):
            result = research_sec_service.discover_sec_filings(
                symbol="aapl", forms=["10-k", "10-q"], limit_per_form=1
            )

        self.assertEqual(result["symbol"], "AAPL")
        self.assertEqual(len(result["filings"]), 2)
        annual = result["filings"][0]
        self.assertEqual(annual["accession_number"], "0000320193-25-000079")
        self.assertEqual(annual["fiscal_year"], 2025)
        self.assertEqual(
            annual["source_url"],
            "https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/example-20250927.htm",
        )
        self.assertIn("CIK0000320193.json", request_mock.call_args.args[0])

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
                return_value={
                    "results": [{
                        "chunk_id": "chunk-sec-1",
                        "document_id": "doc-sec-1",
                        "content": "Revenue increased year over year.",
                        "filename": "NVDA-10-K.html",
                        "page_number": 0,
                        "locator": "SEC filing HTML · passage 14",
                        "locator_type": "html_passage",
                        "native_page_numbers": False,
                        "source_url": "https://www.sec.gov/example.htm",
                        "reranker_score": 0.91,
                    }], "retrieval": {"indexed_documents": 1}
                },
            ),
            mock.patch.object(
                research_service,
                "_generate_research_synthesis",
                return_value={"answer": "Market-data answer.", "model_inference": ["Momentum is positive."]},
            ),
            mock.patch.object(
                research_service,
                "_run_sec_financial_tool",
                return_value=({"coverage": {"fact_rows": 0}, "evidence": []}, None),
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
        self.assertEqual(len(result["document_evidence"]), 1)
        self.assertEqual(result["document_evidence"][0]["locator"], "SEC filing HTML · passage 14")
        self.assertIsNone(result["document_evidence"][0]["page_number"])
        self.assertEqual(len(result["data_evidence"]), 3)
        self.assertEqual(result["model_inference"], ["Momentum is positive."])
        self.assertEqual([step["tool"] for step in result["agent_steps"]], [
            "agent_planner",
            "company_lookup",
            "market_history",
            "financial_calculator",
            "sec_financial_facts",
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

    def test_synthesis_compacts_model_context_without_changing_evidence(self) -> None:
        passages = [
            {
                "filename": f"filing-{index}.html",
                "locator": f"SEC filing HTML · passage {index}",
                "source_url": "https://www.sec.gov/example.htm",
                "content": f"evidence-{index}-" + ("x" * 1400),
            }
            for index in range(6)
        ]
        with mock.patch.object(
            research_service,
            "_call_local_json_model",
            return_value={"answer": "Grounded answer.", "model_inference": []},
        ) as model_mock:
            result = research_service._generate_research_synthesis(
                question="What changed?",
                company={"symbol": "AAPL"},
                calculations={},
                document_context=passages,
                settings=SimpleNamespace(),
            )

        prompt = model_mock.call_args.kwargs["prompt"]
        self.assertEqual(result["answer"], "Grounded answer.")
        self.assertIn("evidence-0-", prompt)
        self.assertIn("evidence-3-", prompt)
        self.assertNotIn("evidence-4-", prompt)
        self.assertLess(len(prompt), 5000)


if __name__ == "__main__":
    unittest.main()
