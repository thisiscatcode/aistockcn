import assert from "node:assert/strict";
import test from "node:test";

import type { ResearchAnswer } from "../../lib/api.ts";
import {
  buildResearchAnswerView,
  documentEvidenceHref,
  presentationSourceHref,
} from "./research-answer-view.ts";


function answerFixture(): ResearchAnswer {
  return {
    symbol: "AAPL",
    question: "What changed?",
    answer: "Long raw answer with us_stock_daily_metrics and 6.80000000000001.",
    document_evidence: [{
      id: "chunk-1",
      citation_id: "D1",
      claim: "Revenue increased.",
      source: "Apple FY2025 10-K",
      locator: "passage 8",
      document_id: "doc-1",
      page_number: 12,
    }],
    data_evidence: [],
    model_inference: ["No additional inference was required."],
    limitations: [],
    agent_steps: [],
    model: { provider: "groq", name: "openai/gpt-oss-20b" },
    presentation: {
      version: "research_presentation_v1",
      kind: "financial_trend",
      takeaway: "Apple’s profitability improved faster than revenue, while operating cash flow declined.",
      takeaway_kind: "deterministic_summary",
      period: { basis: "annual", fiscal_year: 2025, end_date: "2025-09-27" },
      metrics: [{
        key: "revenue",
        label: "Revenue",
        value: 416_161_000_000,
        unit: "USD",
        formatted_value: "$416.16B",
        change: 6.43,
        change_unit: "percent",
        formatted_change: "↑ 6.43%",
        direction: "up",
        period_end: "2025-09-27",
        sources: [{
          provider: "SEC XBRL Company Facts",
          taxonomy: "us-gaap",
          concept: "RevenueFromContractWithCustomerExcludingAssessedTax",
          accession_number: "0000320193-25-000079",
          source_url: "https://www.sec.gov/example",
          raw_value: 416_161_000_000,
          raw_unit: "USD",
        }],
      }],
      interpretations: [],
      sources: [{
        id: "sec-xbrl-2025-09-27",
        label: "SEC XBRL · FY2025",
        provider: "SEC",
        period_end: "2025-09-27",
        source_url: "https://www.sec.gov/example",
        verified: true,
      }],
      source_verified: true,
    },
  };
}


test("uses server presentation fields instead of parsing the raw answer", () => {
  const view = buildResearchAnswerView(answerFixture());
  assert.equal(view.takeaway, "Apple’s profitability improved faster than revenue, while operating cash flow declined.");
  assert.equal(view.metrics[0].formatted_value, "$416.16B");
  assert.equal(view.metrics[0].formatted_change, "↑ 6.43%");
  assert.equal(view.takeaway.includes("us_stock_daily_metrics"), false);
  assert.equal(view.takeaway.includes("6.80000000000001"), false);
});


test("hides an empty model inference section", () => {
  const withoutPresentation = { ...answerFixture(), presentation: undefined };
  const view = buildResearchAnswerView(withoutPresentation);
  assert.equal(view.showInterpretation, false);
  assert.deepEqual(view.interpretations, []);
});


test("keeps technical audit metadata accessible in presentation sources", () => {
  const view = buildResearchAnswerView(answerFixture());
  const auditSource = view.metrics[0].sources[0];
  assert.equal(auditSource.taxonomy, "us-gaap");
  assert.equal(auditSource.accession_number, "0000320193-25-000079");
  assert.equal(view.showAdvancedAudit, true);
});


test("builds clickable internal and SEC source locators", () => {
  const answer = answerFixture();
  assert.equal(documentEvidenceHref(answer.document_evidence[0]), "/research/documents/doc-1/file#page=12");
  assert.equal(presentationSourceHref(answer.presentation!.sources[0]), "https://www.sec.gov/example");
});
