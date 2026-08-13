import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";

import { Shell } from "@/components/shell";
import {
  getResearchCompanies,
  getResearchCompany,
  getResearchDocuments,
  getResearchFilingChangeRuns,
  getResearchFinancials,
  type ResearchCompany
} from "@/lib/api";
import { getCurrentUser } from "@/lib/auth";
import { ResearchCopilot } from "./research-copilot";
import { ResearchComparisonPanel } from "./research-comparison";
import { ResearchDocuments } from "./research-documents";
import { ResearchEvaluationPanel } from "./research-evaluation";
import { ResearchFinancials } from "./research-financials";
import { ResearchFilingChanges } from "./research-filing-changes";


export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Research Copilot — AiStockCN",
  description: "Source-grounded research across live US equity data with SEC filing ingestion in progress."
};


function displayName(company: ResearchCompany) {
  return company.stock_name || company.stock_name_zh || company.symbol;
}


function numberValue(value: unknown) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}


function formatMetric(value: unknown, options: Intl.NumberFormatOptions = {}) {
  const parsed = numberValue(value);
  if (parsed === null) {
    return "—";
  }
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 2, ...options }).format(parsed);
}


function formatDate(value: unknown) {
  if (!value) {
    return "—";
  }
  const date = new Date(String(value));
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }
  return new Intl.DateTimeFormat("en-GB", { day: "2-digit", month: "short", year: "numeric" }).format(date);
}


export default async function ResearchPage({
  searchParams
}: {
  searchParams?: Promise<{ q?: string; symbol?: string }>;
}) {
  const params = (await searchParams) ?? {};
  const query = String(params.q ?? "").trim();
  const symbol = String(params.symbol ?? "").trim().toUpperCase();
  const user = await getCurrentUser();
  if (!user) {
    const returnTo = `/research${symbol ? `?symbol=${encodeURIComponent(symbol)}` : query ? `?q=${encodeURIComponent(query)}` : ""}`;
    redirect(`/login?return_to=${encodeURIComponent(returnTo)}`);
  }

  const [searchResult, snapshot, documentResult, financialResult, filingChangeResult] = await Promise.all([
    getResearchCompanies(query, 12).catch(() => ({ query, rows: 0, total_active: 0, companies: [] })),
    symbol ? getResearchCompany(symbol, 30).catch(() => null) : Promise.resolve(null),
    symbol ? getResearchDocuments(symbol).catch(() => ({ rows: 0, documents: [] })) : Promise.resolve({ rows: 0, documents: [] }),
    symbol ? getResearchFinancials(symbol).catch(() => null) : Promise.resolve(null),
    symbol ? getResearchFilingChangeRuns(symbol).catch(() => ({ symbol, rows: 0, runs: [] })) : Promise.resolve({ symbol, rows: 0, runs: [] })
  ]);

  const company = snapshot?.company;
  const priceDiff = numberValue(company?.price_diff);

  return (
    <Shell
      title="Research Copilot"
      subtitle="Investigate US companies with live market evidence, deterministic calculations and traceable model reasoning."
      locale={user.locale}
      username={user.displayName}
      role={user.role}
      market="US"
    >
      <div className="research-page">
      <section className="research-command-panel">
        <div>
          <p className="research-kicker">Company intelligence workspace</p>
          <h2>Start with a company, not a blank chat.</h2>
          <p>
            Search the live US equity universe. Each research session stays attached to the selected company,
            its market data and its source documents.
          </p>
        </div>
        <form className="research-search-form" action="/research" method="get">
          <label htmlFor="research-company-search">Ticker or company name</label>
          <div>
            <input
              id="research-company-search"
              name="q"
              type="search"
              defaultValue={query}
              placeholder="NVDA, Microsoft, JPMorgan…"
              autoComplete="off"
            />
            <button type="submit">Find company</button>
          </div>
        </form>
      </section>

      <section className="research-layout">
        <aside className="research-company-panel">
          <div className="research-section-heading">
            <div>
              <p className="research-kicker">Live universe</p>
              <h2>{query ? `Results for “${query}”` : "Companies ready to explore"}</h2>
            </div>
            <span>{searchResult.rows}</span>
          </div>
          <div className="research-company-list">
            {searchResult.companies.map((item) => (
              <Link
                key={item.symbol}
                href={`/research?symbol=${encodeURIComponent(item.symbol)}`}
                className={`research-company-row${item.symbol === symbol ? " is-selected" : ""}`}
              >
                <span className="research-symbol">{item.symbol}</span>
                <span>
                  <strong>{displayName(item)}</strong>
                  <small>{item.market || "US"} · {item.stock_industry_en || item.stock_industry || "Industry pending"}</small>
                </span>
                <span className="research-row-price">{formatMetric(item.close, { minimumFractionDigits: 2 })}</span>
              </Link>
            ))}
            {searchResult.rows === 0 ? (
              <p className="research-empty">No matching active US company was found.</p>
            ) : null}
          </div>
        </aside>

        <div className="research-workspace">
          {company && snapshot ? (
            <>
              <section className="research-company-hero">
                <div>
                  <p className="research-kicker">{company.market || "US equity"}</p>
                  <h2>{company.symbol} <span>{displayName(company)}</span></h2>
                  <p>{company.stock_industry_en || company.stock_industry || "Industry classification pending"}</p>
                </div>
                <div className="research-price-block">
                  <strong>{formatMetric(company.close, { minimumFractionDigits: 2 })}</strong>
                  <span className={priceDiff !== null && priceDiff < 0 ? "is-negative" : "is-positive"}>
                    {priceDiff === null ? "—" : `${priceDiff >= 0 ? "+" : ""}${formatMetric(priceDiff)}`}
                  </span>
                  <small>{formatDate(company.trade_date)}</small>
                </div>
              </section>

              <section className="research-metric-grid">
                <article><span>P/E ratio</span><strong>{formatMetric(company.pe_ratio)}</strong></article>
                <article><span>EPS (TTM)</span><strong>{formatMetric(company.earnings_per_share)}</strong></article>
                <article><span>Latest volume</span><strong>{formatMetric(company.volume, { notation: "compact" })}</strong></article>
                <article><span>Market observations</span><strong>{formatMetric(snapshot.coverage.observations)}</strong></article>
              </section>

              <ResearchDocuments symbol={company.symbol} initialDocuments={documentResult.documents} />

              <ResearchFinancials symbol={company.symbol} initialFinancials={financialResult} />

              <ResearchFilingChanges
                symbol={company.symbol}
                documents={documentResult.documents}
                initialRuns={filingChangeResult.runs}
              />

              <ResearchCopilot symbol={company.symbol} />

              <ResearchComparisonPanel symbol={company.symbol} />

              <ResearchEvaluationPanel />

              <section className="research-evidence-panel">
                <div className="research-section-heading">
                  <div>
                    <p className="research-kicker">Evidence layer</p>
                    <h2>Research readiness</h2>
                  </div>
                </div>
                <div className="research-readiness-grid">
                  <article className="is-ready">
                    <span>01</span><strong>Market data</strong><small>Live · {formatDate(snapshot.coverage.date_max)}</small>
                  </article>
                  <article className={documentResult.documents.some((item) => ["text_ready", "indexed"].includes(item.status)) ? "is-ready" : undefined}>
                    <span>02</span><strong>Company documents</strong><small>{documentResult.rows ? `${documentResult.rows} uploaded` : "Upload PDF to begin"}</small>
                  </article>
                  <article className={financialResult?.coverage.fact_rows ? "is-ready" : undefined}>
                    <span>03</span><strong>Financial facts</strong><small>{financialResult?.coverage.fact_rows ? `${financialResult.coverage.fact_rows} SEC XBRL facts` : "Sync SEC facts to begin"}</small>
                  </article>
                  <article className="is-ready">
                    <span>04</span><strong>Grounded answers</strong><small>Live for market evidence</small>
                  </article>
                </div>
              </section>

              <section className="research-task-panel">
                <p className="research-kicker">Research workflow</p>
                <h2>Every answer will separate evidence from inference.</h2>
                <div className="research-task-grid">
                  <article><strong>Ask about the company</strong><span>Natural-language questions grounded in filings and financial facts.</span></article>
                  <article><strong>Compare companies</strong><span>Run the same evidence workflow across two or three issuers.</span></article>
                  <article><strong>Analyse change</strong><span>Track shifts in revenue, profit, risks and management language.</span></article>
                </div>
              </section>
            </>
          ) : (
            <section className="research-empty-state">
              <p className="research-kicker">Research Copilot</p>
              <h2>Select a US company to open its research workspace.</h2>
              <p>
                The company context becomes the boundary for document retrieval, financial tools,
                comparisons and source-grounded answers.
              </p>
            </section>
          )}
        </div>
      </section>
      </div>
    </Shell>
  );
}
