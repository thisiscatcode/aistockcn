import type { Metadata } from "next";

import { AdminNavigation } from "@/components/admin-navigation";
import { AutoRefresh } from "@/components/auto-refresh";
import { MetricCard, Panel } from "@/components/cards";
import { Shell } from "@/components/shell";
import { DataTable } from "@/components/table";
import { getResearchCoverage } from "@/lib/api";
import { requireAdmin } from "@/lib/auth";
import { ResearchEvaluationPanel } from "@/app/research/research-evaluation";


export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Research Operations — AiStockCN",
  description: "Administrative coverage, ingestion and retrieval-quality operations."
};


function count(statuses: Record<string, number>, status: string) {
  return Number(statuses[status] ?? 0);
}


function statusTone(status: string) {
  if (status === "ready" || status === "completed" || status === "indexed") return "positive";
  if (status === "failed" || status === "partial" || status === "unsupported") return "negative";
  return "neutral";
}


export default async function ResearchOperationsPage() {
  const user = await requireAdmin();
  const coverage = await getResearchCoverage(100);
  const ready = count(coverage.status_counts, "ready");
  const active = count(coverage.status_counts, "syncing") + count(coverage.status_counts, "indexing");
  const attention = count(coverage.status_counts, "partial")
    + count(coverage.status_counts, "failed")
    + count(coverage.status_counts, "unsupported");
  const indexedDocuments = count(coverage.document_status_counts, "indexed");
  const totalDocuments = Object.values(coverage.document_status_counts).reduce((sum, value) => sum + Number(value), 0);
  const rows = coverage.companies.map((company) => ({
    priority_rank: company.priority_rank,
    symbol: company.symbol,
    symbol_href: `/research?symbol=${encodeURIComponent(company.symbol)}`,
    stock_name: company.stock_name ?? "",
    priority: company.is_fei_favorite ? "Fei favourite" : company.priority_reasons.join(", ").replaceAll("_", " "),
    status: company.status,
    status_tone: statusTone(company.status),
    annual_reports: `${company.annual_indexed} / ${company.target_annual_reports}`,
    recent_reports: `${company.recent_indexed} / ${company.target_recent_reports}`,
    financial_facts: company.xbrl_fact_count,
    job: company.job_status ?? "—",
    attempts: company.attempt_count ?? 0,
    error: company.last_error_code ?? "—"
  }));

  return (
    <Shell
      title="Research Operations"
      subtitle="Coverage, ingestion and retrieval quality"
      locale={user.locale}
      username={user.displayName}
      role={user.role}
      market="US"
    >
      <AdminNavigation active="research" />
      <AutoRefresh intervalSeconds={15} />

      <section className="metrics-grid research-operations-metrics">
        <MetricCard label="Core issuers" value={coverage.target} hint="Unique SEC CIK coverage" />
        <MetricCard label="Research ready" value={ready} hint={`${active} currently processing`} />
        <MetricCard label="Needs attention" value={attention} hint="Partial, failed or unsupported" />
        <MetricCard label="Indexed documents" value={`${indexedDocuments} / ${totalDocuments}`} hint={`${coverage.queued_documents} queued or processing`} />
        <MetricCard label="Retrieval chunks" value={coverage.chunk_count.toLocaleString()} hint="Stored document passages" />
        <MetricCard label="Financial facts" value={coverage.financial_fact_count.toLocaleString()} hint="SEC XBRL facts" />
      </section>

      <Panel
        title="Company coverage"
        aside={<span className="pill live">Refreshes every 15 seconds</span>}
      >
        <DataTable
          rows={rows}
          locale={user.locale}
          pageSize={25}
          columns={[
            { key: "priority_rank", label: "Rank" },
            { key: "symbol", label: "Company" },
            { key: "priority", label: "Priority source" },
            { key: "status", label: "Coverage" },
            { key: "annual_reports", label: "Annual" },
            { key: "recent_reports", label: "Recent" },
            { key: "financial_facts", label: "Facts" },
            { key: "job", label: "Job" },
            { key: "attempts", label: "Attempts" },
            { key: "error", label: "Last error" }
          ]}
        />
      </Panel>

      <ResearchEvaluationPanel />
    </Shell>
  );
}
