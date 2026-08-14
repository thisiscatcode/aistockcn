import { MetricCard, Panel } from "@/components/cards";
import { DataTable } from "@/components/table";
import { getUsOverview } from "@/lib/api";
import { requireAuth } from "@/lib/auth";
import { formatDate, formatNumber } from "@/lib/format";
import { GateChecklist, UsShell } from "../us-components";

export const dynamic = "force-dynamic";

export default async function UsOverviewPage() {
  const user = await requireAuth();
  const overview = await getUsOverview();
  const coverage = overview.summary.coverage;
  const gate = overview.model.gate;
  const pickRows = overview.top_picks.map((pick) => ({
    rank: pick.rank,
    symbol: pick.symbol,
    symbol_href: `/us/research?symbol=${encodeURIComponent(pick.symbol)}`,
    name: pick.name,
    exchange: pick.exchange,
    industry: pick.industry,
    score: pick.score
  }));

  return (
    <UsShell
      user={user}
      title="US Market Overview"
      subtitle="Coverage, selection and readiness"
    >
      <section className="metrics-grid">
        <MetricCard label="Active Companies" value={formatNumber(coverage.active_symbols, user.locale)} hint="NASDAQ and NYSE" />
        <MetricCard label="Latest Market Date" value={formatDate(coverage.latest_trade_date, user.locale)} hint={`${formatNumber(coverage.latest_symbols, user.locale)} symbols`} />
        <MetricCard label="Daily Coverage" value={`${formatNumber(coverage.latest_coverage_pct, user.locale, { maximumFractionDigits: 1 })}%`} hint="Latest date / active universe" />
        <MetricCard label="Adjusted History" value={`${formatNumber(gate.available_trading_dates, user.locale)} days`} hint={`${formatNumber(gate.available_symbols_with_history, user.locale)} / ${formatNumber(gate.required_symbols_with_history, user.locale)} symbols ready`} />
        <MetricCard label="Selection" value={overview.selection.method === "rules_based" ? "Rules-based" : overview.selection.method} hint={formatDate(overview.selection.date, user.locale)} />
        <MetricCard label="US Paper" value="Gated" hint="Unlocks only after model validation" />
      </section>

      <section className="two-col-grid">
        <Panel title="US Data Readiness" aside={<span className={`pill ${coverage.latest_coverage_pct >= 95 ? "live" : ""}`}>{coverage.latest_coverage_pct >= 95 ? "Healthy" : "Partial"}</span>}>
          <GateChecklist items={[
            { label: "Current daily market data", ready: coverage.latest_coverage_pct >= 95, detail: `${coverage.latest_coverage_pct}% of the active universe is present on the latest date.` },
            { label: "Model training history", ready: gate.history_ready, detail: `${gate.available_trading_dates} / ${gate.required_trading_dates} adjusted dates; ${gate.available_symbols_with_history} / ${gate.required_symbols_with_history} symbols ready.` },
            { label: "US 5D model", ready: gate.training_ready, detail: "Training begins only after the historical-data gate passes." },
            { label: "Walk-forward validation", ready: gate.walk_forward_ready, detail: "Paper trading remains disabled until out-of-sample validation passes." }
          ]} />
        </Panel>

        <Panel title="Product Status">
          <div className="summary-list">
            <div><span>Market data</span><strong>Live</strong></div>
            <div><span>Rules-based screening</span><strong>Live</strong></div>
            <div><span>Research Copilot</span><strong>Live</strong></div>
            <div><span>US 5D model</span><strong>{overview.model.profile.status.replaceAll("_", " ")}</strong></div>
            <div><span>Paper trading</span><strong>Validation required</strong></div>
          </div>
        </Panel>
      </section>

      <Panel title="Latest US Selection" aside={<a className="panel-link" href="/us/quant?view=signals">View all signals →</a>}>
        <DataTable
          rows={pickRows}
          columns={[
            { key: "rank", label: "Rank" },
            { key: "symbol", label: "Symbol" },
            { key: "name", label: "Company" },
            { key: "exchange", label: "Exchange" },
            { key: "industry", label: "Industry" },
            { key: "score", label: "Score" }
          ]}
          locale={user.locale}
          emptyLabel="No US selection snapshot is available yet."
        />
      </Panel>
    </UsShell>
  );
}
