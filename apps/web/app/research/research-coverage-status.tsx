"use client";

import { useEffect, useMemo, useState } from "react";

import type { ResearchCoverageSummary } from "@/lib/api";


function count(summary: ResearchCoverageSummary | null, status: string) {
  return Number(summary?.status_counts?.[status] ?? 0);
}


export function ResearchCoverageStatus({
  initialCoverage,
  selectedSymbol
}: {
  initialCoverage: ResearchCoverageSummary | null;
  selectedSymbol: string;
}) {
  const [coverage, setCoverage] = useState(initialCoverage);

  useEffect(() => {
    let active = true;
    const refresh = async () => {
      try {
        const response = await fetch("/research/coverage?limit=100", { cache: "no-store" });
        if (response.ok && active) setCoverage((await response.json()) as ResearchCoverageSummary);
      } catch {
        // Keep the latest successful snapshot visible while the API recovers.
      }
    };
    const interval = window.setInterval(refresh, 10_000);
    return () => {
      active = false;
      window.clearInterval(interval);
    };
  }, []);

  const selected = useMemo(
    () => coverage?.companies.find((company) => company.symbol === selectedSymbol),
    [coverage, selectedSymbol]
  );
  if (!coverage) return null;

  const activeCount = count(coverage, "syncing") + count(coverage, "indexing");
  const waitingCount = count(coverage, "queued");
  const attentionCount = count(coverage, "partial") + count(coverage, "failed") + count(coverage, "unsupported");

  return (
    <section className="research-coverage-panel" aria-live="polite">
      <div className="research-coverage-heading">
        <div>
          <p className="research-kicker">Core company knowledge base</p>
          <h2>{coverage.target} priority companies are being kept research-ready</h2>
        </div>
        <span>Updates automatically</span>
      </div>
      <div className="research-coverage-metrics">
        <article className="is-ready"><strong>{count(coverage, "ready")}</strong><span>Ready now</span></article>
        <article className={activeCount ? "is-active" : undefined}><strong>{activeCount}</strong><span>Downloading / indexing</span></article>
        <article><strong>{waitingCount}</strong><span>Queued</span></article>
        <article className={attentionCount ? "is-attention" : undefined}><strong>{attentionCount}</strong><span>Needs follow-up</span></article>
      </div>
      {selected ? (
        <div className="research-selected-coverage">
          <strong>{selected.symbol} · {selected.status.replace("_", " ")}</strong>
          <span>{selected.annual_indexed}/{selected.target_annual_reports} annual reports</span>
          <span>{selected.recent_indexed}/{selected.target_recent_reports} recent reports</span>
          <span>{selected.xbrl_fact_count.toLocaleString()} financial facts</span>
          {selected.is_fei_favorite ? <em>Favourite priority</em> : null}
        </div>
      ) : null}
    </section>
  );
}
