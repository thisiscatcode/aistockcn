import { MetricCard, Panel } from "@/components/cards";
import { getUsPaperStatus } from "@/lib/api";
import { requireAuth } from "@/lib/auth";
import { formatNumber } from "@/lib/format";
import { GateChecklist, UsShell } from "../us-components";

export const dynamic = "force-dynamic";

export default async function UsPaperPage() {
  const user = await requireAuth();
  const paper = await getUsPaperStatus();
  const gate = paper.gate;

  return (
    <UsShell user={user} title="US Paper Trading" subtitle="USD simulation account">
      <section className="metrics-grid">
        <MetricCard label="Account" value="Not connected" />
        <MetricCard label="Positions" value={formatNumber(paper.positions.length, user.locale)} />
        <MetricCard label="Orders" value={formatNumber(paper.orders.length, user.locale)} />
        <MetricCard label="Currency" value="USD" />
        <MetricCard label="Status" value="Validation gated" />
      </section>

      <Panel title="Activation Gate" aside={<span className="pill">Disabled</span>}>
        <p className="panel-copy">{paper.message}</p>
        <GateChecklist items={[
          { label: "Historical data", ready: gate.history_ready, detail: `${gate.available_trading_dates} / ${gate.required_trading_dates} required trading days.` },
          { label: "US 5D model trained", ready: gate.training_ready, detail: "The model and artifacts must be independent from A-share production." },
          { label: "Walk-forward passed", ready: gate.walk_forward_ready, detail: "Out-of-sample performance and costs must pass the published thresholds." },
          { label: "US account enabled", ready: gate.ready, detail: "A separate market=US agent and account will be required." }
        ]} />
      </Panel>
    </UsShell>
  );
}
