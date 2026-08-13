from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.services.research_coverage import merge_priority_candidates
from app.services.research_financials import normalize_companyfacts_payload
from app.services.research_sec import FORM_DOCUMENT_TYPES, SUPPORTED_FORMS


class ResearchCoverageTests(unittest.TestCase):
    def test_coverage_priority_keeps_favorites_first_and_aggregates_reasons(self) -> None:
        companies, ineligible = merge_priority_candidates(
            favorites=["TSLA", "NO-CIK", "AAPL"],
            famous=["AAPL", "MSFT"],
            selections=["NVDA", "TSLA"],
            active=["AMD", "MSFT"],
            eligible={"TSLA", "AAPL", "MSFT", "NVDA", "AMD"},
            issuer_keys={"TSLA": "1", "AAPL": "2", "MSFT": "3", "NVDA": "4", "AMD": "5"},
            limit=5,
        )

        self.assertEqual([row["symbol"] for row in companies], ["TSLA", "AAPL", "MSFT", "NVDA", "AMD"])
        self.assertIs(companies[0]["is_fei_favorite"], True)
        self.assertEqual(companies[0]["priority_reasons"], ["fei_favorite", "current_selection"])
        self.assertEqual(companies[1]["priority_reasons"], ["fei_favorite", "famous"])
        self.assertEqual(ineligible, ["NO-CIK"])

    def test_coverage_counts_one_company_once_when_tickers_share_a_cik(self) -> None:
        companies, _ = merge_priority_candidates(
            favorites=["GOOG"],
            famous=["GOOGL", "MSFT"],
            selections=[],
            active=["AAPL"],
            eligible={"GOOG", "GOOGL", "MSFT", "AAPL"},
            issuer_keys={"GOOG": "1652044", "GOOGL": "1652044", "MSFT": "789019", "AAPL": "320193"},
            limit=3,
        )

        self.assertEqual([row["symbol"] for row in companies], ["GOOG", "MSFT", "AAPL"])

    def test_sec_forms_cover_us_and_foreign_issuers(self) -> None:
        self.assertTrue({"10-K", "10-Q", "8-K", "20-F", "40-F", "6-K"}.issubset(SUPPORTED_FORMS))
        self.assertEqual(FORM_DOCUMENT_TYPES["20-F"], "annual_report")
        self.assertEqual(FORM_DOCUMENT_TYPES["40-F"], "annual_report")
        self.assertEqual(FORM_DOCUMENT_TYPES["6-K"], "current_report")

    def test_ifrs_companyfacts_preserve_reporting_currency_and_20f_lineage(self) -> None:
        payload = {
            "facts": {
                "ifrs-full": {
                    "Revenue": {
                        "label": "Revenue",
                        "description": "Revenue for the period",
                        "units": {
                            "DKK": [{
                                "start": "2025-01-01", "end": "2025-12-31", "val": 1000,
                                "accn": "0000000000-26-000001", "fy": 2025, "fp": "FY",
                                "form": "20-F", "filed": "2026-02-01"
                            }]
                        },
                    }
                }
            }
        }

        rows = normalize_companyfacts_payload(symbol="NVO", cik="0000000000", payload=payload)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["taxonomy"], "ifrs-full")
        self.assertEqual(rows[0]["unit"], "DKK")
        self.assertEqual(rows[0]["form"], "20-F")
        self.assertEqual(rows[0]["period_kind"], "annual")


if __name__ == "__main__":
    unittest.main()
