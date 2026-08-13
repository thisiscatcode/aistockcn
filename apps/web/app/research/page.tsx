import type { Metadata, Route } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";

import { Shell } from "@/components/shell";
import {
  getResearchCompanies,
  getResearchCompany,
  getResearchDocuments,
  getResearchFilingChangeRuns,
  getResearchFinancials,
  type ResearchCompany,
  type ResearchFinancialMetric
} from "@/lib/api";
import { getCurrentUser } from "@/lib/auth";
import { ResearchCopilot } from "./research-copilot";
import { ResearchComparisonPanel } from "./research-comparison";
import { ResearchDocuments } from "./research-documents";
import { ResearchFinancials } from "./research-financials";
import { ResearchFilingChanges } from "./research-filing-changes";


export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Company Research — AiStockCN",
  description: "Source-grounded company research across SEC filings and live US equity data."
};

const RESEARCH_VIEWS = [
  ["overview", "Summary", "◫"],
  ["ask", "Ask AI", "✦"],
  ["financials", "Financials", "▥"],
  ["filings", "Filings", "▤"],
  ["changes", "Changes", "↕"],
  ["compare", "Compare", "⇄"]
] as const;

type ResearchView = typeof RESEARCH_VIEWS[number][0];

const OVERVIEW_QUESTIONS = [
  "Generate an investment research summary covering revenue, profitability, risks, management outlook and current market signals.",
  "What changed in revenue, profitability and cash flow across the latest comparable periods?",
  "What are the most material risks in the latest filing, and which ones became more prominent?"
] as const;


function displayName(company: ResearchCompany) {
  return company.stock_name || company.stock_name_zh || company.symbol;
}


function numberValue(value: unknown) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}


function formatMetric(value: unknown, options: Intl.NumberFormatOptions = {}) {
  const parsed = numberValue(value);
  if (parsed === null) return "—";
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 2, ...options }).format(parsed);
}


function formatDate(value: unknown) {
  if (!value) return "—";
  const date = new Date(String(value));
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat("en-GB", { day: "2-digit", month: "short", year: "numeric" }).format(date);
}


function formatFinancialValue(value: unknown, unit?: string) {
  const parsed = numberValue(value);
  if (parsed === null) return "—";
  const formatted = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 2 }).format(parsed);
  const displayUnit = unit === "USD/shares" ? "USD/share" : unit;
  return displayUnit ? `${formatted} ${displayUnit}` : formatted;
}


function formatFinancial(metric?: ResearchFinancialMetric) {
  if (!metric) return "—";
  return formatFinancialValue(metric.value, metric.unit);
}


function formatChange(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return "No comparable period";
  return `${Number(value) >= 0 ? "+" : ""}${Number(value).toFixed(1)}% YoY`;
}


function viewHref(symbol: string, view: ResearchView, question?: string) {
  const params = new URLSearchParams({ symbol, view });
  if (question) params.set("question", question);
  return `/research?${params.toString()}` as Route;
}


function normalizeView(value: string): ResearchView {
  return RESEARCH_VIEWS.some(([key]) => key === value) ? value as ResearchView : "overview";
}


export default async function ResearchPage({
  searchParams
}: {
  searchParams?: Promise<{ q?: string; symbol?: string; view?: string; question?: string }>;
}) {
  const params = (await searchParams) ?? {};
  const query = String(params.q ?? "").trim();
  const symbol = String(params.symbol ?? "").trim().toUpperCase();
  const view = normalizeView(String(params.view ?? "overview"));
  const initialQuestion = String(params.question ?? "").trim();
  const user = await getCurrentUser();
  if (!user) {
    const returnParams = new URLSearchParams();
    if (symbol) returnParams.set("symbol", symbol);
    if (query) returnParams.set("q", query);
    if (view !== "overview") returnParams.set("view", view);
    if (initialQuestion) returnParams.set("question", initialQuestion);
    const returnTo = `/research${returnParams.size ? `?${returnParams.toString()}` : ""}`;
    redirect(`/login?return_to=${encodeURIComponent(returnTo)}`);
  }

  const [searchResult, snapshot, documentResult, financialResult, filingChangeResult] = await Promise.all([
    !symbol || query
      ? getResearchCompanies(query, 12).catch(() => ({ query, rows: 0, total_active: 0, companies: [] }))
      : Promise.resolve({ query, rows: 0, total_active: 0, companies: [] }),
    symbol ? getResearchCompany(symbol, 30).catch(() => null) : Promise.resolve(null),
    symbol ? getResearchDocuments(symbol).catch(() => ({ rows: 0, documents: [] })) : Promise.resolve({ rows: 0, documents: [] }),
    symbol ? getResearchFinancials(symbol).catch(() => null) : Promise.resolve(null),
    symbol ? getResearchFilingChangeRuns(symbol).catch(() => ({ symbol, rows: 0, runs: [] })) : Promise.resolve({ symbol, rows: 0, runs: [] })
  ]);

  const company = snapshot?.company;
  const priceDiff = numberValue(company?.price_diff);
  const latestAnnual = financialResult?.latest_annual;
  const revenue = latestAnnual?.metrics.revenue as ResearchFinancialMetric | undefined;
  const netIncome = latestAnnual?.metrics.net_income as ResearchFinancialMetric | undefined;
  const operatingCashFlow = latestAnnual?.metrics.operating_cash_flow as ResearchFinancialMetric | undefined;
  const operatingMargin = numberValue(latestAnnual?.derived.operating_margin_pct);
  const indexedDocuments = documentResult.documents.filter((document) => document.status === "indexed");
  const latestChangeRun = filingChangeResult.runs.find((run) => run.status === "completed");

  return (
    <Shell
      title="Company Research"
      subtitle="US equities · financials · filings"
      locale={user.locale}
      username={user.displayName}
      role={user.role}
      market="US"
    >
      <div className="research-page research-product-page">
        {!company || !snapshot ? (
          <>
            <section className="research-command-panel research-start-panel">
              <div>
                <h2>Research a company</h2>
              </div>
              <form className="research-search-form" action="/research" method="get">
                <label className="sr-only" htmlFor="research-company-search">Company or ticker</label>
                <div>
                  <input id="research-company-search" name="q" type="search" defaultValue={query} placeholder="Ticker or company name" autoComplete="off" autoFocus />
                  <button type="submit">Search</button>
                </div>
              </form>
            </section>

            <section className="research-company-panel research-company-browser">
              <div className="research-section-heading">
                <div>
                  <h2>{query ? `Results for “${query}”` : "Popular companies"}</h2>
                </div>
                <span>{searchResult.rows}</span>
              </div>
              <div className="research-company-list">
                {searchResult.companies.map((item) => (
                  <Link key={item.symbol} href={viewHref(item.symbol, "overview")} className="research-company-row">
                    <span className="research-symbol">{item.symbol}</span>
                    <span>
                      <strong>{displayName(item)}</strong>
                      <small>{item.stock_industry_en || item.stock_industry || item.market || "US equity"}</small>
                    </span>
                    <span className="research-row-price">{formatMetric(item.close, { minimumFractionDigits: 2 })}</span>
                  </Link>
                ))}
                {searchResult.rows === 0 ? <p className="research-empty">No matching active US company was found.</p> : null}
              </div>
            </section>
          </>
        ) : (
          <>
            <section className="research-company-toolbar">
              <Link href="/research" className="research-back-link">All companies</Link>
              <form className="research-inline-search" action="/research" method="get">
                <label className="sr-only" htmlFor="research-change-company">Change company</label>
                <input id="research-change-company" name="q" type="search" placeholder="Change company or ticker" autoComplete="off" />
                <button type="submit">Search</button>
              </form>
            </section>

            <section className="research-company-hero research-product-hero">
              <div>
                <h2>{company.symbol} <span>{displayName(company)}</span></h2>
                <p>{company.stock_industry_en || company.stock_industry || "Industry classification pending"}</p>
              </div>
              <div className="research-price-block">
                <strong>{formatMetric(company.close, { minimumFractionDigits: 2 })}</strong>
                <span className={priceDiff !== null && priceDiff < 0 ? "is-negative" : "is-positive"}>
                  {priceDiff === null ? "—" : `${priceDiff >= 0 ? "+" : ""}${formatMetric(priceDiff)}`}
                </span>
                <small>As of {formatDate(company.trade_date)}</small>
              </div>
              <div className="research-security-stats">
                <article><span>P/E</span><strong>{formatMetric(company.pe_ratio)}</strong></article>
                <article><span>EPS</span><strong>{formatMetric(company.earnings_per_share)}</strong></article>
                <article><span>Volume</span><strong>{formatMetric(company.volume, { notation: "compact" })}</strong></article>
              </div>
            </section>

            <nav className="research-view-tabs" aria-label={`${company.symbol} research sections`}>
              {RESEARCH_VIEWS.map(([key, label, icon]) => (
                <Link key={key} href={viewHref(company.symbol, key)} className={view === key ? "is-active" : undefined} aria-current={view === key ? "page" : undefined}>
                  <i className="research-view-icon" aria-hidden="true">{icon}</i>
                  {label}
                  {key === "filings" && indexedDocuments.length ? <span className="research-view-count">{indexedDocuments.length}</span> : null}
                  {key === "changes" && filingChangeResult.rows ? <span className="research-view-count">{filingChangeResult.rows}</span> : null}
                </Link>
              ))}
            </nav>

            <main className="research-view-content">
              {view === "overview" ? (
                <div className="research-overview-dashboard">
                  <section className="research-query-panel">
                    <form className="research-query-form" action="/research" method="get">
                      <input type="hidden" name="symbol" value={company.symbol} />
                      <input type="hidden" name="view" value="ask" />
                      <label className="sr-only" htmlFor="research-overview-question">Ask about {company.symbol}</label>
                      <input id="research-overview-question" name="question" type="search" placeholder={`Ask about ${company.symbol}: revenue, margins, risks or guidance`} autoComplete="off" />
                      <button type="submit"><span aria-hidden="true">✦</span> Ask AI</button>
                    </form>
                    <div className="research-query-shortcuts" aria-label="Common research questions">
                      {OVERVIEW_QUESTIONS.map((question, index) => (
                        <Link key={question} href={viewHref(company.symbol, "ask", question)}>
                          {index === 0 ? "Investment summary" : index === 1 ? "Financial trends" : "Material risks"}
                        </Link>
                      ))}
                    </div>
                  </section>

                  <section className="research-overview-section">
                    <div className="research-overview-heading">
                      <h2>{latestAnnual ? `FY${latestAnnual.fiscal_year ?? "—"} Financials` : "Financials"}</h2>
                      <Link href={viewHref(company.symbol, "financials")}>View all</Link>
                    </div>
                    {latestAnnual ? (
                      <div className="research-overview-financials">
                        <article><span>Revenue</span><strong>{formatFinancial(revenue)}</strong><small>{formatChange(financialResult?.annual_changes.revenue)}</small></article>
                        <article><span>Net income</span><strong>{formatFinancial(netIncome)}</strong><small>{formatChange(financialResult?.annual_changes.net_income)}</small></article>
                        <article><span>Operating margin</span><strong>{operatingMargin === null ? "—" : `${formatMetric(operatingMargin)}%`}</strong><small>Filed facts</small></article>
                        <article><span>Free cash flow</span><strong>{formatFinancialValue(latestAnnual.derived.free_cash_flow, operatingCashFlow?.unit)}</strong><small>OCF − capex</small></article>
                      </div>
                    ) : <p className="research-business-empty">Standardised annual financials are not available for this company yet.</p>}
                  </section>

                  <div className="research-overview-two-column">
                    <section className="research-overview-section">
                      <div className="research-overview-heading">
                        <h2>Latest Filings</h2>
                        <Link href={viewHref(company.symbol, "filings")}>View all</Link>
                      </div>
                      <div className="research-overview-filings">
                        {indexedDocuments.slice(0, 4).map((document) => (
                          <a key={document.id} href={`/research/documents/${encodeURIComponent(document.id)}/file`} target="_blank" rel="noreferrer">
                            <span>{document.document_type.replaceAll("_", " ")}</span><strong>{document.fiscal_year ? `FY${document.fiscal_year}` : formatDate(document.filing_date)}</strong><small>{formatDate(document.filing_date)} ↗</small>
                          </a>
                        ))}
                        {!indexedDocuments.length ? <p className="research-business-empty">No source filings are available yet.</p> : null}
                      </div>
                    </section>

                    <section className="research-overview-section">
                      <div className="research-overview-heading">
                        <h2>Filing Changes</h2>
                        <Link href={viewHref(company.symbol, "changes")}>Open</Link>
                      </div>
                      {latestChangeRun ? (
                        <div className="research-change-summary">
                          <strong>{latestChangeRun.older_fiscal_year ? `FY${latestChangeRun.older_fiscal_year}` : "Older filing"} → {latestChangeRun.newer_fiscal_year ? `FY${latestChangeRun.newer_fiscal_year}` : "Newer filing"}</strong>
                          <span>{latestChangeRun.result_count} material changes identified</span>
                          <small>{latestChangeRun.reviewed_count ?? 0} reviewed · completed {formatDate(latestChangeRun.completed_at)}</small>
                        </div>
                      ) : <p className="research-business-empty">No saved annual filing comparison yet.</p>}
                    </section>
                  </div>
                </div>
              ) : null}

              {view === "ask" ? <ResearchCopilot symbol={company.symbol} initialQuestion={initialQuestion} /> : null}
              {view === "financials" ? <ResearchFinancials symbol={company.symbol} initialFinancials={financialResult} /> : null}
              {view === "filings" ? <ResearchDocuments symbol={company.symbol} initialDocuments={documentResult.documents} /> : null}
              {view === "changes" ? <ResearchFilingChanges symbol={company.symbol} documents={documentResult.documents} initialRuns={filingChangeResult.runs} /> : null}
              {view === "compare" ? <ResearchComparisonPanel symbol={company.symbol} /> : null}
            </main>
          </>
        )}
      </div>
    </Shell>
  );
}
