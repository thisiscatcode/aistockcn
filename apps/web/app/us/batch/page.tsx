import { MetricCard, Panel } from "@/components/cards";
import { getUsPipelineStatus } from "@/lib/api";
import { requireAdmin } from "@/lib/auth";
import { formatDate, formatDateTime, formatNumber } from "@/lib/format";
import { UsShell } from "../us-components";

export const dynamic = "force-dynamic";

export default async function UsBatchPage() {
  const user = await requireAdmin();
  const status = await getUsPipelineStatus();
  const latestByLane = new Map(status.recent_runs.map((run) => [run.lane, run]));

  return (
    <UsShell user={user} title="US Data Jobs" subtitle="New York market-data lanes">
      <section className="metrics-grid">
        <MetricCard label="Status" value={status.status} hint={status.is_running ? status.current_run?.lane ?? "Running" : "Scheduler watching"} />
        <MetricCard label="Latest Market Date" value={formatDate(status.coverage.latest_trade_date, user.locale)} hint={`${formatNumber(status.coverage.latest_symbols, user.locale)} symbols`} />
        <MetricCard label="Scheduler" value="Enabled" hint={status.scheduler.timezone} />
      </section>

      <section className="catalog-grid us-lane-grid">
        {status.scheduler.lanes.map((lane) => {
          const run = latestByLane.get(lane);
          return (
            <article className="panel" key={lane}>
              <div className="panel-header">
                <h2>{lane}</h2>
                <span className={`pill ${run?.status === "running" ? "live" : ""}`}>{run?.status ?? "pending"}</span>
              </div>
              <div className="summary-list">
                <div><span>Target</span><strong>{formatDate(run?.target_date, user.locale)}</strong></div>
                <div><span>Completed</span><strong>{formatNumber(run?.done_count, user.locale)}</strong></div>
                <div><span>Failed</span><strong>{formatNumber(run?.failed_count, user.locale)}</strong></div>
                <div><span>Last run</span><strong>{formatDateTime(run?.completed_at ?? run?.started_at, user.locale)}</strong></div>
              </div>
            </article>
          );
        })}
      </section>
    </UsShell>
  );
}
