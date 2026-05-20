import { ReactNode } from "react";
import { MetricCard, Panel } from "@/components/cards";
import { Shell } from "@/components/shell";
import { DataTable } from "@/components/table";
import { getModelOverview } from "@/lib/api";
import { requireAuth } from "@/lib/auth";
import { formatDateRange, formatMetric, formatNumber } from "@/lib/format";
import { getMessages, type PanelLocale } from "@/lib/i18n";
import { ProfileSelector } from "./profile-selector";

export const dynamic = "force-dynamic";

type TableRow = Record<string, unknown>;

function numberValue(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function formatPercent(value: unknown, locale: PanelLocale, options: Intl.NumberFormatOptions = {}) {
  const numeric = numberValue(value);
  if (numeric === null) {
    return "—";
  }
  return new Intl.NumberFormat(locale, {
    style: "percent",
    maximumFractionDigits: 1,
    ...options
  }).format(numeric);
}

function financeTone(value: unknown, invert = false) {
  const numeric = numberValue(value);
  if (numeric === null || numeric === 0) {
    return "finance-neutral";
  }
  const positive = invert ? numeric < 0 : numeric > 0;
  return positive ? "finance-positive" : "finance-negative";
}

function InfoLabel({ label, description }: { label: ReactNode; description: string }) {
  return (
    <span className="info-label">
      <span>{label}</span>
      <span className="info-tooltip" tabIndex={0} aria-label={description}>
        i
        <span className="info-tooltip-content" role="tooltip">
          {description}
        </span>
      </span>
    </span>
  );
}

function FinanceStat({
  label,
  value,
  detail,
  tone = "finance-neutral",
  tooltip
}: {
  label: ReactNode;
  value: ReactNode;
  detail?: ReactNode;
  tone?: string;
  tooltip?: string;
}) {
  return (
    <div className="finance-stat">
      <p className="finance-stat-label">
        {tooltip ? <InfoLabel label={label} description={tooltip} /> : label}
      </p>
      <p className={`finance-stat-value ${tone}`}>{value}</p>
      {detail ? <p className="finance-stat-detail">{detail}</p> : null}
    </div>
  );
}

function FeatureImportanceChart({ rows, locale, emptyLabel }: { rows: TableRow[]; locale: PanelLocale; emptyLabel: string }) {
  if (!rows.length) {
    return <p className="empty-state">{emptyLabel}</p>;
  }
  const chartRows = rows
    .map((row) => ({
      feature: String(row.feature ?? "Unknown"),
      gain: numberValue(row.importance_gain) ?? 0
    }))
    .sort((left, right) => right.gain - left.gain)
    .slice(0, 12);
  const maxGain = Math.max(...chartRows.map((row) => row.gain), 1);

  return (
    <div className="feature-chart" aria-label="Feature importance by gain">
      {chartRows.map((row) => (
        <div className="feature-chart-row" key={row.feature}>
          <span className="feature-chart-label" title={row.feature}>{row.feature}</span>
          <div className="feature-chart-track">
            <span className="feature-chart-bar" style={{ width: `${Math.max((row.gain / maxGain) * 100, 2)}%` }} />
          </div>
          <span className="feature-chart-value">{formatNumber(row.gain, locale, { maximumFractionDigits: 0 })}</span>
        </div>
      ))}
    </div>
  );
}

function svgPath(points: Array<{ x: number; y: number }>) {
  return points.map((point, index) => `${index === 0 ? "M" : "L"} ${point.x.toFixed(1)} ${point.y.toFixed(1)}`).join(" ");
}

function EquityCurveChart({ rows, totalReturn, locale }: { rows: TableRow[]; totalReturn: number | null; locale: PanelLocale }) {
  const chartRows = rows
    .map((row) => ({
      date: String(row.rebalance_date ?? ""),
      equity: numberValue(row.equity),
    }))
    .filter((row): row is { date: string; equity: number } => row.date.length > 0 && row.equity !== null);
  if (!chartRows.length) {
    return <p className="empty-state">No saved equity curve is available for this selected backtest.</p>;
  }
  const values = chartRows.map((row) => row.equity);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const scaleY = (value: number) => 150 - ((value - min) / Math.max(max - min, 0.01)) * 116;
  const step = chartRows.length > 1 ? 384 / (chartRows.length - 1) : 0;
  const points = chartRows.map((row, index) => ({
    x: 24 + index * step,
    portfolioY: scaleY(row.equity),
  }));
  const firstDate = chartRows[0]?.date ?? "";
  const lastDate = chartRows[chartRows.length - 1]?.date ?? "";

  return (
    <div className="equity-chart" aria-label="Portfolio equity curve from saved backtest">
      <div className="equity-chart-header">
        <span>Equity Curve</span>
        <span className="equity-chart-note">Portfolio equity from saved backtest</span>
      </div>
      <svg viewBox="0 0 432 176" role="img" aria-label="Portfolio equity curve">
        <path className="equity-grid-line" d="M 24 34 L 408 34" />
        <path className="equity-grid-line" d="M 24 92 L 408 92" />
        <path className="equity-grid-line" d="M 24 150 L 408 150" />
        <path
          className="equity-line equity-line-portfolio"
          d={svgPath(points.map((point) => ({ x: point.x, y: point.portfolioY })))}
        />
      </svg>
      <div className="equity-chart-legend">
        <span><i className="legend-dot legend-portfolio" /> Portfolio {formatPercent(totalReturn, locale)}</span>
        <span>{firstDate} to {lastDate}</span>
      </div>
    </div>
  );
}

function artifactLabel(value: unknown) {
  const record = value && typeof value === "object" && !Array.isArray(value) ? value as TableRow : {};
  return record.exists ? "Available" : "Missing";
}

function artifactHint(value: unknown) {
  const record = value && typeof value === "object" && !Array.isArray(value) ? value as TableRow : {};
  const path = String(record.path ?? "");
  if (!path) {
    return "No artifact for selected profile";
  }
  const updatedAt = String(record.updated_at ?? "");
  return updatedAt ? `${path} (${updatedAt})` : path;
}

export default async function ModelsPage({
  searchParams
}: {
  searchParams?: Promise<{ profile?: string }>;
}) {
  const user = await requireAuth();
  const copy = getMessages(user.locale);
  const params = (await searchParams) ?? {};
  const requestedProfile = typeof params.profile === "string" ? params.profile : undefined;
  const overview = await getModelOverview(requestedProfile);
  const training = (overview.training_metadata ?? {}) as TableRow;
  const metrics = (training.metrics ?? {}) as Record<string, number>;
  const backtest = (overview.backtest_summary ?? {}) as TableRow;
  const hasTrainingSnapshot = Object.keys(training).length > 0;
  const hasBacktestSnapshot = Object.keys(backtest).length > 0;
  const backtestRuns = Array.isArray(overview.backtest_runs)
    ? overview.backtest_runs as TableRow[]
    : [];
  const profiles = Array.isArray(overview.model_profiles)
    ? overview.model_profiles as TableRow[]
    : [];
  const currentProfile = String(overview.current_profile ?? training.profile_name ?? overview.default_profile ?? "short_5d");
  const currentProfileLabel = String(overview.current_profile_label ?? currentProfile);
  const activeProfile = String(overview.active_profile ?? overview.default_profile ?? "short_5d");
  const activeProfileLabel = String(overview.active_profile_label ?? activeProfile);
  const latestBacktestProfile = String(backtestRuns[0]?.profile_name ?? "");
  const latestBacktestLabel = String(backtestRuns[0]?.profile_label ?? latestBacktestProfile);
  const backtestMismatchLabel = latestBacktestProfile && latestBacktestProfile !== currentProfile
    ? `${latestBacktestLabel} (${latestBacktestProfile})`
    : null;
  const totalReturn = numberValue(backtest.portfolio_total_return);
  const cagr = numberValue(backtest.portfolio_cagr);
  const maxDrawdown = numberValue(backtest.portfolio_max_drawdown);
  const winRate = numberValue(backtest.portfolio_win_rate);
  const isTrustedBacktest = backtest.is_trustworthy === true;
  const backtestTrustWarning = String(backtest.trust_warning ?? "");
  const equityCurve = Array.isArray(overview.backtest_equity_curve)
    ? overview.backtest_equity_curve as TableRow[]
    : [];
  const artifactStatus = (overview.artifact_status ?? {}) as TableRow;
  const featureImportanceEmptyLabel = `No saved feature importance artifact exists for ${currentProfile}.`;
  const formattedBacktestRuns = backtestRuns.map((run) => ({
    ...run,
    portfolio_total_return: run.is_trustworthy ? formatPercent(run.portfolio_total_return, user.locale) : "Untrusted",
    portfolio_cagr: run.is_trustworthy ? formatPercent(run.portfolio_cagr, user.locale) : "Untrusted",
    portfolio_max_drawdown: run.is_trustworthy ? formatPercent(run.portfolio_max_drawdown, user.locale) : "Untrusted",
    portfolio_win_rate: run.is_trustworthy ? formatPercent(run.portfolio_win_rate, user.locale) : "Untrusted",
    is_trustworthy: run.is_trustworthy ? "Trusted" : "Legacy"
  }));

  return (
    <Shell
      title={copy.models.title}
      subtitle={copy.models.subtitle}
      locale={user.locale}
      username={user.username}
      role={user.role}
    >
      <section className="model-view-header">
        <div>
          <p className="model-view-kicker">Currently viewing model</p>
          <h2>{currentProfile} <span>{currentProfileLabel}</span></h2>
          <p className="panel-copy">Paper trading active model: {activeProfileLabel} ({activeProfile})</p>
        </div>
        <ProfileSelector profiles={profiles} selectedProfile={currentProfile} />
      </section>

      <section className="metrics-grid">
        <MetricCard
          label={<InfoLabel label={copy.models.auc} description="AUC measures how well the model ranks likely winners above likely losers. Higher is better; 0.50 is random." />}
          value={hasTrainingSnapshot ? formatMetric(metrics.auc, user.locale) : "—"}
          hint={`${currentProfile} validation ranking quality`}
        />
        <MetricCard label={copy.models.accuracy} value={hasTrainingSnapshot ? formatMetric(metrics.accuracy, user.locale) : "—"} hint={`${currentProfile} threshold hit rate`} />
        <MetricCard label={copy.models.trainRows} value={formatNumber(training.train_rows as number | undefined, user.locale)} hint={formatDateRange({ date_min: training.train_date_min as string | null | undefined, date_max: training.train_date_max as string | null | undefined }, user.locale, copy.common.to)} />
        <MetricCard label={copy.models.validRows} value={formatNumber(training.valid_rows as number | undefined, user.locale)} hint={formatDateRange({ date_min: training.valid_date_min as string | null | undefined, date_max: training.valid_date_max as string | null | undefined }, user.locale, copy.common.to)} />
      </section>

      <section className="two-col-grid">
        <Panel title={copy.models.trainingSnapshot} aside={<span className={`pill ${hasTrainingSnapshot ? "live" : "warn"}`}>{currentProfile}</span>}>
          {hasTrainingSnapshot ? (
            <div className="status-meta">
              <span>{copy.models.profile}: {currentProfile}</span>
              <span><InfoLabel label="Label Horizon" description="How many trading days ahead the model is trying to predict." />: {formatNumber(training.label_horizon as number | undefined, user.locale)}</span>
              <span>{copy.models.features}: {Array.isArray(training.feature_cols) ? formatNumber(training.feature_cols.length, user.locale) : "—"}</span>
              <span>{copy.models.categoricals}: {Array.isArray(training.categorical_cols) ? training.categorical_cols.join(", ") : "—"}</span>
              <span>{copy.models.threshold}: {formatMetric(training.threshold, user.locale)}</span>
              <span>{copy.models.validationDays}: {formatNumber(training.valid_days as number | undefined, user.locale)}</span>
            </div>
          ) : (
            <p className="empty-state">No saved training snapshot is available for this selected model.</p>
          )}
        </Panel>

        <Panel title={copy.models.backtestSnapshot} aside={<span className={`pill ${hasBacktestSnapshot ? "live" : "warn"}`}>{currentProfile}</span>}>
          {hasBacktestSnapshot ? (
            <div className="model-backtest-stack">
              {!isTrustedBacktest ? (
                <p className="banner banner-error">
                  {backtestTrustWarning || "Legacy backtest artifact. Rerun this profile before using these performance numbers."}
                </p>
              ) : null}
              <div className="finance-stat-grid">
                <FinanceStat label={copy.models.totalReturn} value={isTrustedBacktest ? formatPercent(totalReturn, user.locale) : "Rerun required"} tone={isTrustedBacktest ? financeTone(totalReturn) : "finance-neutral"} detail="Portfolio total return" />
                <FinanceStat
                  label="CAGR"
                  tooltip="Compound annual growth rate. It turns the full backtest return into an annualized rate."
                  value={isTrustedBacktest ? formatPercent(cagr, user.locale) : "Rerun required"}
                  tone={isTrustedBacktest ? financeTone(cagr) : "finance-neutral"}
                  detail="Annualized portfolio return"
                />
                <FinanceStat
                  label={copy.models.maxDrawdown}
                  tooltip="The worst peak-to-trough portfolio decline during the backtest. Closer to zero is better."
                  value={isTrustedBacktest ? formatPercent(maxDrawdown, user.locale) : "Rerun required"}
                  tone={isTrustedBacktest ? financeTone(maxDrawdown) : "finance-neutral"}
                  detail="Largest historical pullback"
                />
                <FinanceStat label="Win Rate" value={isTrustedBacktest ? formatPercent(winRate, user.locale) : "Rerun required"} tone={isTrustedBacktest ? financeTone(winRate) : "finance-neutral"} detail={`${formatNumber(backtest.num_rebalances as number | undefined, user.locale)} rebalances`} />
              </div>
              {isTrustedBacktest ? (
                <EquityCurveChart rows={equityCurve} totalReturn={totalReturn} locale={user.locale} />
              ) : (
                <p className="empty-state">Legacy equity curve hidden until this profile is rerun with the corrected backtest.</p>
              )}
            </div>
          ) : (
            <>
              <p className="empty-state">{copy.models.noMatchingBacktest}</p>
              {backtestMismatchLabel ? (
                <p className="panel-copy">{copy.models.latestBacktestDifferentProfile} Latest: {backtestMismatchLabel}.</p>
              ) : null}
            </>
          )}
        </Panel>
      </section>

      <Panel title={copy.models.topFeatureImportance} aside={<span className="pill">{currentProfile}</span>}>
        <FeatureImportanceChart rows={overview.top_features} locale={user.locale} emptyLabel={featureImportanceEmptyLabel} />
      </Panel>

      <Panel title="Artifact Coverage" aside={<span className="pill">{currentProfile}</span>}>
        <div className="status-meta">
          <span>Training metadata: {artifactLabel(artifactStatus.training_metadata)} - {artifactHint(artifactStatus.training_metadata)}</span>
          <span>Feature importance: {artifactLabel(artifactStatus.feature_importance)} - {artifactHint(artifactStatus.feature_importance)}</span>
          <span>Backtest summary: {artifactLabel(artifactStatus.backtest_summary)} - {artifactHint(artifactStatus.backtest_summary)}</span>
          <span>Equity curve: {artifactLabel(artifactStatus.backtest_equity_curve)} - {artifactHint(artifactStatus.backtest_equity_curve)}</span>
        </div>
      </Panel>

      <Panel title="Backtest Comparison">
        <DataTable
          rows={formattedBacktestRuns}
          columns={[
            { key: "run_id", label: "Run" },
            { key: "profile_label", label: "Model" },
            { key: "generated_at", label: "Generated" },
            { key: "portfolio_total_return", label: "Total Return" },
            { key: "portfolio_cagr", label: "CAGR" },
            { key: "portfolio_max_drawdown", label: "Max Drawdown" },
            { key: "portfolio_win_rate", label: "Win Rate" },
            { key: "is_trustworthy", label: "Trust" },
            { key: "num_rebalances", label: "Rebalances" },
            { key: "backtest_end", label: "Backtest End" }
          ]}
          emptyLabel={copy.common.noRows}
          locale={user.locale}
        />
      </Panel>

      <Panel title="Model Profiles">
        {profiles.length ? (
          <div className="data-table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Label</th>
                  <th>Label Horizon</th>
                  <th>Label Threshold</th>
                  <th>Rebalance Every</th>
                  <th>Backtest Top K</th>
                  <th>Paper</th>
                </tr>
              </thead>
              <tbody>
                {profiles.map((profile) => {
                  const name = String(profile.name ?? "");
                  const label = String(profile.label ?? name);
                  const isActive = name === activeProfile;
                  return (
                    <tr key={name}>
                      <td>{name}</td>
                      <td>{label}</td>
                      <td>{formatNumber(profile.label_horizon as number | undefined, user.locale)}</td>
                      <td>{formatMetric(profile.label_threshold, user.locale)}</td>
                      <td>{formatNumber(profile.backtest_rebalance_every as number | undefined, user.locale)}</td>
                      <td>{formatNumber(profile.backtest_top_k as number | undefined, user.locale)}</td>
                      <td>
                        {isActive ? (
                          <span className="pill live">Active</span>
                        ) : user.role === "admin" ? (
                          <form action="/models/activate" method="post">
                            <input type="hidden" name="profile" value={name} />
                            <button className="action-button secondary-button table-action-button" type="submit">Use For Paper Trading</button>
                          </form>
                        ) : (
                          <span className="pill">Available</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="empty-state">{copy.common.noRows}</p>
        )}
      </Panel>
    </Shell>
  );
}
