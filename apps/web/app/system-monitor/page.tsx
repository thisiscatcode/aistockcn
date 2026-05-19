import { MetricCard, Panel } from "@/components/cards";
import { Shell } from "@/components/shell";
import { getBatchLogs, getBatchStatus, getDataSummary, getModelOverview, getPicks, getPipelineRunStatus, getPipelineSummary, getReferenceBatchStatus, getWorkflowStatus } from "@/lib/api";
import { requireAuth } from "@/lib/auth";
import { formatBytes, formatDate, formatDateTime, formatMetric, formatNumber } from "@/lib/format";
import { getMessages } from "@/lib/i18n";
import type { ReactNode } from "react";

export const dynamic = "force-dynamic";

function SnapshotRow({
  label,
  value,
  hint
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
}) {
  return (
    <div className="snapshot-row">
      <span className="snapshot-label">{label}</span>
      <strong className="snapshot-value">{value}</strong>
      {hint ? <span className="snapshot-hint">{hint}</span> : null}
    </div>
  );
}

function datasetValue(snapshot: { rows: number; code_count?: number | null } | null | undefined, locale: "en" | "zh-Hant") {
  if (!snapshot) {
    return "Missing";
  }
  return `${formatNumber(snapshot.rows, locale)} rows / ${formatNumber(snapshot.code_count, locale)} codes`;
}

function datasetDate(snapshot: { date_min?: string | null; date_max?: string | null } | null | undefined, locale: "en" | "zh-Hant") {
  if (!snapshot?.date_min && !snapshot?.date_max) {
    return "No date range";
  }
  if (snapshot.date_min && snapshot.date_max) {
    return `${formatDate(snapshot.date_min, locale)} to ${formatDate(snapshot.date_max, locale)}`;
  }
  return formatDate(snapshot.date_max ?? snapshot.date_min, locale);
}

export default async function OverviewPage() {
  const user = await requireAuth();
  const copy = getMessages(user.locale);

  const [status, logs, data, model, picks, workflow, pipelineRun, referenceStatus, pipelineSummary] = await Promise.all([
    getBatchStatus(),
    getBatchLogs(24),
    getDataSummary(),
    getModelOverview(),
    getPicks(10),
    getWorkflowStatus(),
    getPipelineRunStatus(),
    getReferenceBatchStatus(),
    getPipelineSummary()
  ]);

  const trainingMetrics = (model.training_metadata?.metrics ?? {}) as Record<string, number>;
  const latestLines = logs.lines.slice(-12);
  const runtimeByStep = new Map(workflow.steps.map((step) => [step.step, step]));
  const runningSteps = workflow.steps.filter((step) => step.is_running).length;
  const referenceSnapshot = data.reference_snapshot;
  const referenceWarningCount =
    referenceStatus.valuation_reference_missing_count +
    referenceStatus.valuation_reference_stale_count +
    referenceStatus.industry_missing_count;

  return (
    <Shell
      title={copy.systemMonitor.title}
      subtitle={copy.systemMonitor.subtitle}
      locale={user.locale}
      username={user.username}
      role={user.role}
    >
      <section className="metrics-grid">
        <MetricCard label="Daily Pipeline" value={pipelineRun.status_label} hint={pipelineRun.current_step_label ?? "Idle"} />
        <MetricCard label="Current Step" value={pipelineRun.current_step_label ?? "—"} hint={formatDateTime(pipelineRun.updated_at, user.locale)} />
        <MetricCard label="Step 1 Progress" value={`${formatNumber(status.done_count, user.locale)}/${formatNumber(status.total_codes, user.locale)}`} hint={typeof status.progress_pct === "number" ? `${formatNumber(status.progress_pct, user.locale, { maximumFractionDigits: 1 })}%` : "—"} />
        <MetricCard label="Last Code" value={status.last_code ?? "—"} hint={formatDateTime(status.updated_at, user.locale)} />
        <MetricCard label="Running Steps" value={formatNumber(runningSteps, user.locale)} hint={formatDateTime(workflow.generated_at, user.locale)} />
        <MetricCard label={copy.overview.batchStatus} value={status.is_running ? copy.common.live : copy.common.idle} hint={status.container_name ?? copy.overview.stateFileOnly} />
        <MetricCard label={copy.overview.progress} value={typeof status.progress_pct === "number" ? `${formatNumber(status.progress_pct, user.locale, { maximumFractionDigits: 1 })}%` : "—"} hint={`${formatNumber(status.done_count, user.locale)}/${formatNumber(status.total_codes, user.locale)} ${copy.overview.doneHint}`} />
        <MetricCard label="Reference Stale" value={formatNumber(referenceStatus.valuation_reference_stale_count, user.locale)} hint={`${formatNumber(referenceStatus.valuation_reference_ready_count, user.locale)} ready`} />
        <MetricCard label={copy.overview.dataFiles} value={formatNumber(data.paired_file_count, user.locale)} hint={`${formatNumber(data.total_size_mb, user.locale, { maximumFractionDigits: 1 })} MB ${copy.common.localStore}`} />
        <MetricCard label={copy.overview.topPicks} value={formatNumber(picks.rows, user.locale)} hint={picks.latest_date ? `${copy.overview.latestDateHint} ${formatDate(picks.latest_date, user.locale)}` : copy.overview.noInference} />
        <MetricCard label={copy.overview.validationAuc} value={formatMetric(trainingMetrics.auc, user.locale)} hint={copy.overview.latestTraining} />
        <MetricCard label="Backtest Artifact" value={formatBytes(runtimeByStep.get(5)?.artifact_size_bytes, user.locale)} hint={formatDateTime(runtimeByStep.get(5)?.artifact_updated_at, user.locale)} />
      </section>

      <section className="two-col-grid">
        <Panel title={copy.overview.pulse} aside={<span className={`pill ${status.is_running ? "live" : ""}`}>{status.is_running ? copy.common.live : copy.common.idle}</span>}>
          <div className="status-meta">
            <span>{copy.common.lastStateUpdate}: {formatDateTime(status.updated_at, user.locale)}</span>
            <span>{copy.common.lastCode}: {status.last_code ?? "—"}</span>
            <span>{copy.common.remaining}: {formatNumber(status.remaining_count, user.locale)}</span>
            <span>{copy.common.logSource}: {logs.source}</span>
          </div>
          <pre className="log-console">{latestLines.join("\n") || copy.common.noLogs}</pre>
        </Panel>

        <Panel
          title={copy.overview.snapshot}
          aside={<span className={`pill ${referenceWarningCount ? "warn" : "live"}`}>{referenceWarningCount ? `${formatNumber(referenceWarningCount, user.locale)} reference checks` : "Reference clean"}</span>}
        >
          <div className="snapshot-health-grid">
            <section className="snapshot-health-section">
              <h3>Universe</h3>
              <div className="snapshot-row-grid">
                <SnapshotRow label="Active universe" value={formatNumber(data.active_stock_count, user.locale)} hint="tradable stock_list.parquet rows" />
                <SnapshotRow label="Registry history" value={formatNumber(data.registry_stock_count, user.locale)} hint="stock_registry.parquet rows" />
                <SnapshotRow label="Listed universe" value={formatNumber(data.stock_count, user.locale)} hint="all listed records in current snapshot" />
                <SnapshotRow label="Sample codes" value={data.sample_codes.slice(0, 5).join(", ") || "—"} hint="quick coverage spot-check" />
              </div>
            </section>

            <section className="snapshot-health-section">
              <h3>Raw Coverage</h3>
              <div className="snapshot-row-grid">
                <SnapshotRow label="Paired file sets" value={formatNumber(data.paired_file_count, user.locale)} hint="K-line plus valuation pairs" />
                <SnapshotRow label="K-line files" value={formatNumber(data.kline_file_count, user.locale)} hint="daily adjusted OHLCV history" />
                <SnapshotRow label="Valuation files" value={formatNumber(data.valuation_file_count, user.locale)} hint="daily valuation panels" />
                <SnapshotRow label="Local footprint" value={formatBytes(data.total_size_mb * 1024 * 1024, user.locale)} hint="research data store" />
              </div>
            </section>

            <section className="snapshot-health-section">
              <h3>Research Artifacts</h3>
              <div className="snapshot-row-grid">
                <SnapshotRow label="Training features" value={datasetValue(pipelineSummary.training_features, user.locale)} hint={datasetDate(pipelineSummary.training_features, user.locale)} />
                <SnapshotRow label="Inference features" value={datasetValue(pipelineSummary.inference_features, user.locale)} hint={datasetDate(pipelineSummary.inference_features, user.locale)} />
                <SnapshotRow label="Inference scores" value={datasetValue(pipelineSummary.inference_scores, user.locale)} hint={datasetDate(pipelineSummary.inference_scores, user.locale)} />
                <SnapshotRow label="Top saved features" value={formatNumber(model.top_features.length, user.locale)} hint="latest model metadata" />
              </div>
            </section>

            <section className="snapshot-health-section">
              <h3>Reference Coverage</h3>
              <div className="snapshot-row-grid">
                <SnapshotRow label="Target trade date" value={referenceStatus.target_trade_date ?? referenceSnapshot?.target_trade_date ?? "—"} hint="slow-reference freshness target" />
                <SnapshotRow label="Ready / missing / stale" value={`${formatNumber(referenceStatus.valuation_reference_ready_count, user.locale)} / ${formatNumber(referenceStatus.valuation_reference_missing_count, user.locale)} / ${formatNumber(referenceStatus.valuation_reference_stale_count, user.locale)}`} hint="valuation reference cache" />
                <SnapshotRow label="Industry known / missing" value={`${formatNumber(referenceSnapshot?.industry_known_count, user.locale)} / ${formatNumber(referenceStatus.industry_missing_count, user.locale)}`} hint="industry metadata coverage" />
                <SnapshotRow label="Reference batch" value={referenceStatus.status_label} hint={formatDateTime(referenceStatus.updated_at ?? referenceStatus.reference_status_updated_at, user.locale)} />
              </div>
            </section>
          </div>
        </Panel>
      </section>
    </Shell>
  );
}
