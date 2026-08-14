import { MetricCard, Panel } from "@/components/cards";
import { getUsPaperStatus } from "@/lib/api";
import { requireAuth } from "@/lib/auth";
import { GateChecklist, UsShell } from "../us-components";

export const dynamic = "force-dynamic";

export default async function UsPaperPage() {
  const user = await requireAuth();
  const paper = await getUsPaperStatus();
  const gate = paper.gate;

  return (
    <UsShell user={user} title="US Execution" subtitle="Readiness gates · no broker order submission">
      <section className="product-stage-heading">
        <div><span className="stage-icon">⇄</span><div><h1>Execution Readiness</h1><p>Validate the complete decision pipeline without representing a broker account or creating orders.</p></div></div>
        <span className="capability-label status-in_validation">In validation</span>
      </section>
      <section className="metrics-grid compact-metrics">
        <MetricCard label="Mode" value="Readiness only" />
        <MetricCard label="Currency" value="USD" />
        <MetricCard label="Broker Account" value="Not connected" />
        <MetricCard label="Order Submission" value="Disabled" />
      </section>

      <Panel title="Validation Gates" aside={<span className="pill">No order actions</span>}>
        <GateChecklist items={[
          { label: "Adjusted historical data", ready: gate.history_ready, detail: `${gate.available_trading_dates} / ${gate.required_trading_dates} dates; ${gate.available_symbols_with_history} / ${gate.required_symbols_with_history} symbols ready.` },
          { label: "US 5D model candidate", ready: gate.training_ready, detail: "The model, calendar and artifacts remain isolated from CN stock production." },
          { label: "Walk-forward passed", ready: gate.walk_forward_ready, detail: "Out-of-sample performance and costs must pass the published thresholds." },
          { label: "Registry activation", ready: gate.ready, detail: "Activation is atomic and validation-gated; it still cannot submit a broker order." },
          { label: "Broker order submission", ready: false, detail: "Intentionally disabled for the US market in this release." }
        ]} />
      </Panel>
    </UsShell>
  );
}
