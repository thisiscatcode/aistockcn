import { MetricCard, Panel } from "@/components/cards";
import { DataTable } from "@/components/table";
import { getUsPipelineStatus } from "@/lib/api";
import { requireAdmin } from "@/lib/auth";
import { formatDate, formatNumber } from "@/lib/format";
import { UsShell } from "../us-components";

export const dynamic = "force-dynamic";

export default async function UsSystemMonitorPage() {
  const user = await requireAdmin();
  const status = await getUsPipelineStatus();
  const coverage = status.coverage;

  return (
    <UsShell user={user} title="US System Monitor" subtitle="Pipeline health and recent runs">
      <section className="metrics-grid">
        <MetricCard label="Pipeline" value={status.status} hint={status.is_running ? "A US lane is running" : "No US lane is running"} />
        <MetricCard label="Latest Date" value={formatDate(coverage.latest_trade_date, user.locale)} hint={`${coverage.latest_symbols} symbols`} />
        <MetricCard label="Coverage" value={`${formatNumber(coverage.latest_coverage_pct, user.locale, { maximumFractionDigits: 1 })}%`} hint="Latest daily universe" />
        <MetricCard label="Trading Days" value={formatNumber(coverage.trading_dates, user.locale)} hint="Stored US history" />
        <MetricCard label="Scheduler Zone" value="New York" hint={status.scheduler.timezone} />
      </section>

      <Panel title="Recent US Jobs" aside={<span className={`pill ${status.is_running ? "live" : ""}`}>{status.is_running ? "Running" : "Idle"}</span>}>
        <DataTable
          rows={status.recent_runs as unknown as Array<Record<string, unknown>>}
          columns={[
            { key: "lane", label: "Lane" },
            { key: "target_date", label: "Target Date" },
            { key: "status", label: "Status" },
            { key: "started_at", label: "Started" },
            { key: "completed_at", label: "Completed" },
            { key: "done_count", label: "Done" },
            { key: "failed_count", label: "Failed" },
            { key: "last_symbol", label: "Last Symbol" },
            { key: "last_error", label: "Last Error" }
          ]}
          locale={user.locale}
          pageSize={10}
          emptyLabel="No US pipeline runs have been recorded."
        />
      </Panel>
    </UsShell>
  );
}
