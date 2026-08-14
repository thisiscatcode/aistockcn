import { MetricCard, Panel } from "@/components/cards";
import { DataTable } from "@/components/table";
import { getUsModelStatus, getUsPicks } from "@/lib/api";
import { requireAuth } from "@/lib/auth";
import { formatDate, formatNumber } from "@/lib/format";
import { UsShell } from "../us-components";

export const dynamic = "force-dynamic";

export default async function UsPortfolioPage() {
  const user = await requireAuth();
  const [selection, model] = await Promise.all([getUsPicks(25), getUsModelStatus()]);
  const targetReady = model.gate.training_ready && model.gate.walk_forward_ready;
  return (
    <UsShell user={user} title="US Portfolio" subtitle="Research baskets and validated model targets">
      <section className="product-stage-heading">
        <div><span className="stage-icon">◆</span><div><h1>Research Portfolio</h1><p>Current research basket; no broker account is connected.</p></div></div>
        <span className={`capability-label status-${targetReady ? "live" : "in_validation"}`}>{targetReady ? "Live" : "In validation"}</span>
      </section>
      <section className="metrics-grid compact-metrics">
        <MetricCard label="Research Basket" value={formatNumber(selection.rows, user.locale)} hint="Rules-based candidates" />
        <MetricCard label="As Of" value={formatDate(selection.data_freshness?.selection, user.locale)} />
        <MetricCard label="Model Target Basket" value={targetReady ? "Available" : "Validation gated"} />
        <MetricCard label="Broker Account" value="Not connected" />
      </section>
      <Panel title="Research Basket" aside={<span className="pill">Not an account position</span>}>
        <DataTable
          rows={selection.picks.map((item) => ({ rank: item.rank, symbol: item.symbol, company: item.name, industry: item.industry, score: item.score }))}
          columns={[{ key: "rank", label: "Rank" }, { key: "symbol", label: "Symbol" }, { key: "company", label: "Company" }, { key: "industry", label: "Industry" }, { key: "score", label: "Score" }]}
          locale={user.locale}
          emptyLabel="No research basket is currently available."
        />
      </Panel>
    </UsShell>
  );
}
