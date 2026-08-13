"use client";

import { useState } from "react";

import type { ResearchFinancialMetric, ResearchFinancialSummary } from "@/lib/api";


const DISPLAY_METRICS = [
  ["revenue", "Revenue"],
  ["gross_profit", "Gross profit"],
  ["operating_income", "Operating income"],
  ["net_income", "Net income"],
  ["eps_diluted", "Diluted EPS"],
  ["operating_cash_flow", "Operating cash flow"]
] as const;


function compactNumber(value: number | null | undefined, unit?: string) {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  if (unit === "USD/shares") return `$${value.toFixed(2)}`;
  return new Intl.NumberFormat("en-US", {
    notation: "compact",
    maximumFractionDigits: 2,
    style: unit === "USD" ? "currency" : "decimal",
    currency: unit === "USD" ? "USD" : undefined
  }).format(value);
}


function changeLabel(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(value)) return "No comparable period";
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}% YoY`;
}


export function ResearchFinancials({
  symbol,
  initialFinancials
}: {
  symbol: string;
  initialFinancials: ResearchFinancialSummary | null;
}) {
  const [financials, setFinancials] = useState(initialFinancials);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState("");
  const latest = financials?.latest_annual;

  async function sync() {
    if (syncing) return;
    setSyncing(true);
    setError("");
    try {
      const response = await fetch("/research/financials/sec", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbol })
      });
      const result = await response.json();
      if (!response.ok) {
        const detail = typeof result?.detail === "string" ? result.detail : result?.detail?.message;
        throw new Error(detail || "SEC financial sync failed");
      }
      setFinancials(result.financials as ResearchFinancialSummary);
    } catch (syncError) {
      setError(syncError instanceof Error ? syncError.message : "SEC financial sync failed");
    } finally {
      setSyncing(false);
    }
  }

  return (
    <section className="research-financials-panel">
      <div className="research-section-heading">
        <div>
          <h2>SEC Financials</h2>
        </div>
        <button type="button" onClick={sync} disabled={syncing}>
          {syncing ? "Syncing SEC…" : financials?.coverage.fact_rows ? "Refresh financials" : "Sync financials"}
        </button>
      </div>

      {error ? <p className="research-error" role="alert">{error}</p> : null}

      {latest ? (
        <>
          <div className="research-financial-period">
            <strong>FY{latest.fiscal_year ?? "—"}</strong>
            <span>Period ended {latest.end_date}</span>
            <small>{financials?.coverage.fact_rows ?? 0} canonical facts · {financials?.coverage.annual_periods ?? 0} annual periods</small>
          </div>
          <div className="research-financial-grid">
            {DISPLAY_METRICS.map(([key, label]) => {
              const fact = latest.metrics[key] as ResearchFinancialMetric | undefined;
              const change = financials?.annual_changes[key];
              return (
                <article key={key}>
                  <span>{label}</span>
                  <strong>{compactNumber(fact?.value, fact?.unit)}</strong>
                  <small className={change !== null && change !== undefined && change < 0 ? "is-negative" : "is-positive"}>
                    {changeLabel(change)}
                  </small>
                  {fact ? (
                    <a href={fact.source_url} target="_blank" rel="noreferrer" title={fact.locator}>
                      {fact.concept} ↗
                    </a>
                  ) : null}
                </article>
              );
            })}
          </div>
          <p className="research-financial-note">
            Values are normalized from SEC XBRL facts. Each metric retains its taxonomy concept, period,
            filing date and accession number; calculated changes are deterministic.
          </p>
        </>
      ) : (
        <p className="research-document-empty">
          Financial facts have not been synchronized for {symbol}. Sync once to enable standardized revenue,
          profitability, cash-flow and balance-sheet tools.
        </p>
      )}
    </section>
  );
}
