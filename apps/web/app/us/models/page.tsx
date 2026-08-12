import { MetricCard, Panel } from "@/components/cards";
import { getUsModelStatus } from "@/lib/api";
import { requireAuth } from "@/lib/auth";
import { formatDate, formatNumber } from "@/lib/format";
import { GateChecklist, UsShell } from "../us-components";

export const dynamic = "force-dynamic";

export default async function UsModelsPage() {
  const user = await requireAuth();
  const model = await getUsModelStatus();
  const gate = model.gate;
  const progress = Math.min((gate.available_trading_dates / gate.required_trading_dates) * 100, 100);

  return (
    <UsShell user={user} title="US Models" subtitle="An independent United States model pipeline with honest data and validation gates.">
      <section className="metrics-grid">
        <MetricCard label="Profile" value={model.profile.name} hint="Independent from all A-share models" />
        <MetricCard label="Horizon" value={`${model.profile.horizon_trading_days} trading days`} hint="Next open to fifth close" />
        <MetricCard label="Benchmark" value={model.profile.benchmark.symbol} hint={model.profile.benchmark.name} />
        <MetricCard label="Available History" value={`${formatNumber(gate.available_trading_dates, user.locale)} days`} hint={`${formatNumber(gate.required_trading_dates, user.locale)} required`} />
        <MetricCard label="Status" value={model.profile.status.replaceAll("_", " ")} hint={`Market data ${formatDate(model.as_of, user.locale)}`} />
      </section>

      <Panel title="Model Readiness" aside={<span className="pill">{formatNumber(progress, user.locale, { maximumFractionDigits: 1 })}% history</span>}>
        <div className="metric-progress-track us-history-progress" aria-label={`${progress}% of required history`}>
          <span style={{ width: `${progress}%` }} />
        </div>
        <GateChecklist items={[
          { label: "Historical depth", ready: gate.history_ready, detail: `${gate.available_trading_dates} / ${gate.required_trading_dates} trading days.` },
          { label: "US-only training", ready: gate.training_ready, detail: "The model will train only on United States equities; A-share samples are never mixed in." },
          { label: "Walk-forward evaluation", ready: gate.walk_forward_ready, detail: "Out-of-sample rank IC, net return, Sharpe and drawdown must be published before activation." },
          { label: "Paper activation", ready: gate.ready, detail: "No US orders can be generated while any gate remains incomplete." }
        ]} />
      </Panel>

      <Panel title="Current Blockers">
        <ul className="us-blocker-list">
          {gate.blockers.map((blocker) => <li key={blocker}>{blocker}</li>)}
        </ul>
      </Panel>
    </UsShell>
  );
}
