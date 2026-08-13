"use client";

import { FormEvent, useState } from "react";

import type { ResearchComparison } from "@/lib/api";


function metric(value: unknown, suffix = "") {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? `${parsed.toFixed(2)}${suffix}` : "—";
}


function compactFinancial(value: unknown) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return "—";
  return new Intl.NumberFormat("en-US", {
    notation: "compact",
    maximumFractionDigits: 2,
    style: "currency",
    currency: "USD"
  }).format(parsed);
}


export function ResearchComparisonPanel({ symbol }: { symbol: string }) {
  const [symbols, setSymbols] = useState(`${symbol}, MSFT`);
  const [question, setQuestion] = useState("Compare valuation, recent performance, risk evidence and management positioning.");
  const [result, setResult] = useState<ResearchComparison | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    const selected = symbols.split(/[\s,]+/).map((item) => item.trim().toUpperCase()).filter(Boolean);
    setLoading(true);
    setError("");
    try {
      const response = await fetch("/research/compare", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbols: selected, question: question.trim() })
      });
      const payload = await response.json();
      if (!response.ok) {
        const detail = typeof payload?.detail === "string" ? payload.detail : payload?.detail?.message;
        throw new Error(detail || "Comparison agent failed");
      }
      setResult(payload as ResearchComparison);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Comparison agent failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="research-comparison-panel">
      <div className="research-section-heading">
        <div>
          <p className="research-kicker">Multi-company task</p>
          <h2>Compare two or three companies</h2>
        </div>
        <span>Agent</span>
      </div>
      <form className="research-comparison-form" onSubmit={submit}>
        <label>
          <span>Tickers</span>
          <input value={symbols} onChange={(event) => setSymbols(event.target.value)} placeholder="AAPL, MSFT, GOOGL" />
        </label>
        <label>
          <span>Comparison objective</span>
          <input value={question} onChange={(event) => setQuestion(event.target.value)} maxLength={800} />
        </label>
        <button type="submit" disabled={loading}>{loading ? "Comparing…" : "Run comparison"}</button>
      </form>
      {error ? <p className="research-error" role="alert">{error}</p> : null}
      {result ? (
        <div className="research-comparison-result">
          <p>{result.answer}</p>
          <div className="research-comparison-table" role="table" aria-label="Company comparison">
            <div className="is-heading" role="row"><span>Company</span><span>P/E</span><span>EPS</span><span>20d return</span><span>Volatility</span></div>
            {result.companies.map((item) => (
              <div key={item.symbol} role="row">
                <strong>{item.symbol}</strong>
                <span>{metric(item.company.pe_ratio)}</span>
                <span>{metric(item.company.earnings_per_share)}</span>
                <span>{metric(item.calculations.return_20d_pct, "%")}</span>
                <span>{metric(item.calculations.annualized_volatility_pct, "%")}</span>
              </div>
            ))}
          </div>
          {result.companies.some((item) => item.financials) ? (
            <div className="research-comparison-table is-financial" role="table" aria-label="SEC financial comparison">
              <div className="is-heading" role="row"><span>Company</span><span>Revenue</span><span>Revenue YoY</span><span>Net income</span><span>Net income YoY</span><span>Gross margin</span></div>
              {result.companies.map((item) => (
                <div key={`${item.symbol}-financials`} role="row">
                  <strong>{item.symbol}</strong>
                  <span>{compactFinancial(item.financials?.metrics?.revenue?.value)}</span>
                  <span>{metric(item.financials?.annual_changes?.revenue, "%")}</span>
                  <span>{compactFinancial(item.financials?.metrics?.net_income?.value)}</span>
                  <span>{metric(item.financials?.annual_changes?.net_income, "%")}</span>
                  <span>{metric(item.financials?.derived?.gross_margin_pct, "%")}</span>
                </div>
              ))}
            </div>
          ) : null}
          <div className="research-answer-columns">
            <article className="research-proof-card is-evidence">
              <div><span>Document evidence</span><small>Page-grounded</small></div>
              {result.document_evidence.map((item) => (
                <section key={`${item.symbol}-${item.id}`}>
                  <p><strong>{item.symbol}</strong> · {item.claim}</p>
                  {item.document_id && item.page_number ? (
                    <a
                      className="research-source-link"
                      href={`/research/documents/${encodeURIComponent(item.document_id)}/file#page=${item.page_number}`}
                      target="_blank"
                      rel="noreferrer"
                    >
                      <cite>{item.source} · {item.locator} ↗</cite>
                    </a>
                  ) : <cite>{item.source} · {item.locator}</cite>}
                </section>
              ))}
              {!result.document_evidence.length ? <p>No relevant indexed passages were available.</p> : null}
            </article>
            {result.financial_evidence?.length ? (
              <article className="research-proof-card is-evidence">
                <div><span>SEC XBRL evidence</span><small>Standardized facts</small></div>
                {result.financial_evidence.map((item) => (
                  <section key={`${item.symbol}-${item.id}`}>
                    <p><strong>{item.symbol}</strong> · {item.claim}</p>
                    <a className="research-source-link" href={item.source_url ?? "#"} target="_blank" rel="noreferrer">
                      <cite>{item.source} · {item.locator} ↗</cite>
                    </a>
                  </section>
                ))}
              </article>
            ) : null}
            <article className="research-proof-card is-inference">
              <div><span>Model inference</span><small>{result.model.name}</small></div>
              <ul>{result.model_inference.map((item) => <li key={item}>{item}</li>)}</ul>
            </article>
          </div>
          <p className="research-comparison-trace">{result.agent_steps.map((step) => step.tool.replaceAll("_", " ")).join(" → ")}</p>
        </div>
      ) : null}
    </section>
  );
}
