from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.services.research_coverage import merge_priority_candidates
from app.services.research_sec import FORM_DOCUMENT_TYPES, SUPPORTED_FORMS


class ResearchCoverageTests(unittest.TestCase):
    def test_coverage_priority_keeps_favorites_first_and_aggregates_reasons(self) -> None:
        companies, ineligible = merge_priority_candidates(
            favorites=["TSLA", "NO-CIK", "AAPL"],
            famous=["AAPL", "MSFT"],
            selections=["NVDA", "TSLA"],
            active=["AMD", "MSFT"],
            eligible={"TSLA", "AAPL", "MSFT", "NVDA", "AMD"},
            limit=5,
        )

        self.assertEqual([row["symbol"] for row in companies], ["TSLA", "AAPL", "MSFT", "NVDA", "AMD"])
        self.assertIs(companies[0]["is_fei_favorite"], True)
        self.assertEqual(companies[0]["priority_reasons"], ["fei_favorite", "current_selection"])
        self.assertEqual(companies[1]["priority_reasons"], ["fei_favorite", "famous"])
        self.assertEqual(ineligible, ["NO-CIK"])

    def test_sec_forms_cover_us_and_foreign_issuers(self) -> None:
        self.assertTrue({"10-K", "10-Q", "8-K", "20-F", "40-F", "6-K"}.issubset(SUPPORTED_FORMS))
        self.assertEqual(FORM_DOCUMENT_TYPES["20-F"], "annual_report")
        self.assertEqual(FORM_DOCUMENT_TYPES["40-F"], "annual_report")
        self.assertEqual(FORM_DOCUMENT_TYPES["6-K"], "current_report")


if __name__ == "__main__":
    unittest.main()
