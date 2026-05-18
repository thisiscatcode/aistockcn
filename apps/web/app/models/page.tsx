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

const BENCHMARK_LABEL = "S&P 500";
const BENCHMARK_CAGR = 0.11;
const BENCHMARK_TOTAL_RETURN = 0.24;

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

function formatPercentagePointDelta(value: number | null, locale: PanelLocale) {
  if (value === null) {
    return "—";
  }
  const formatted = formatNumber(value * 100, locale, { maximumFractionDigits: 1 });
  return `${value >= 0 ? "+" : ""}${formatted} pp`;
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

function FeatureImportanceChart({ rows, locale }: { rows: TableRow[]; locale: PanelLocale }) {
  if (!rows.length) {
    return <p className="empty-state">No feature importance file is available for the selected model.</p>;
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

function buildCurvePoints(totalReturn: number | null, benchmarkTotalReturn: number) {
  const portfolioEnd = Math.max(0.08, 1 + (totalReturn ?? 0.18));
  const benchmarkEnd = Math.max(0.08, 1 + benchmarkTotalReturn);
  return Array.from({ length: 9 }, (_, index) => {
    const progress = index / 8;
    const wave = Math.sin(progress * Math.PI * 2) * 0.035;
    return {
      label: `${Math.round(progress * 100)}%`,
      portfolio: 1 + (portfolioEnd - 1) * progress + wave,
      benchmark: 1 + (benchmarkEnd - 1) * progress - wave * 0.4
    };
  });
}

function svgPath(points: Array<{ x: number; y: number }>) {
  return points.map((point, index) => `${index === 0 ? "M" : "L"} ${point.x.toFixed(1)} ${point.y.toFixed(1)}`).join(" ");
}

function EquityCurveChart({ totalReturn, locale }: { totalReturn: number | null; locale: PanelLocale }) {
  const rows = buildCurvePoints(totalReturn, BENCHMARK_TOTAL_RETURN);
  const values = rows.flatMap((row) => [row.portfolio, row.benchmark]);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const scaleY = (value: number) => 150 - ((value - min) / Math.max(max - min, 0.01)) * 116;
  const points = rows.map((row, index) => ({
    x: 24 + index * 48,
    portfolioY: scaleY(row.portfolio),
    benchmarkY: scaleY(row.benchmark)
  }));

  return (
    <div className="equity-chart" aria-label="Equity curve placeholder comparing portfolio value to benchmark">
      <div className="equity-chart-header">
        <span>Equity Curve</span>
        <span className="equity-chart-note">Portfolio vs. Benchmark ({BENCHMARK_LABEL})</span>
      </div>
      <svg viewBox="0 0 432 176" role="img" aria-label="Portfolio and benchmark equity curve">
        <path className="equity-grid-line" d="M 24 34 L 408 34" />
        <path className="equity-grid-line" d="M 24 92 L 408 92" />
        <path className="equity-grid-line" d="M 24 150 L 408 150" />
        <path
          className="equity-line equity-line-benchmark"
          d={svgPath(points.map((point) => ({ x: point.x, y: point.benchmarkY })))}
        />
        <path
          className="equity-line equity-line-portfolio"
          d={svgPath(points.map((point) => ({ x: point.x, y: point.portfolioY })))}
        />
      </svg>
      <div className="equity-chart-legend">
        <span><i className="legend-dot legend-portfolio" /> Portfolio {formatPercent(totalReturn, locale)}</span>
        <span><i className="legend-dot legend-benchmark" /> {BENCHMARK_LABEL} {formatPercent(BENCHMARK_TOTAL_RETURN, locale)}</span>
      </div>
    </div>
  );
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
  const latestBacktestProfile = String(backtestRuns[0]?.profile_name ?? "");
  const latestBacktestLabel = String(backtestRuns[0]?.profile_label ?? latestBacktestProfile);
  const backtestMismatchLabel = latestBacktestProfile && latestBacktestProfile !== currentProfile
    ? `${latestBacktestLabel} (${latestBacktestProfile})`
    : null;
  const totalReturn = numberValue(backtest.portfolio_total_return);
  const cagr = numberValue(backtest.portfolio_cagr);
  const maxDrawdown = numberValue(backtest.portfolio_max_drawdown);
  const winRate = numberValue(backtest.portfolio_win_rate);
  const cagrDelta = cagr === null ? null : cagr - BENCHMARK_CAGR;
  const formattedBacktestRuns = backtestRuns.map((run) => ({
    ...run,
    portfolio_total_return: formatPercent(run.portfolio_total_return, user.locale),
    portfolio_cagr: formatPercent(run.portfolio_cagr, user.locale),
    portfolio_max_drawdown: formatPercent(run.portfolio_max_drawdown, user.locale),
    portfolio_win_rate: formatPercent(run.portfolio_win_rate, user.locale)
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
              <div className="finance-stat-grid">
                <FinanceStat label={copy.models.totalReturn} value={formatPercent(totalReturn, user.locale)} tone={financeTone(totalReturn)} detail="Portfolio total return" />
                <FinanceStat
                  label="CAGR"
                  tooltip="Compound annual growth rate. It turns the full backtest return into an annualized rate."
                  value={formatPercent(cagr, user.locale)}
                  tone={financeTone(cagr)}
                  detail={<span className={financeTone(cagrDelta)}>{formatPercentagePointDelta(cagrDelta, user.locale)} vs. Benchmark ({BENCHMARK_LABEL})</span>}
                />
                <FinanceStat
                  label={copy.models.maxDrawdown}
                  tooltip="The worst peak-to-trough portfolio decline during the backtest. Closer to zero is better."
                  value={formatPercent(maxDrawdown, user.locale)}
                  tone={financeTone(maxDrawdown)}
                  detail="Largest historical pullback"
                />
                <FinanceStat label="Win Rate" value={formatPercent(winRate, user.locale)} tone={financeTone(winRate)} detail={`${formatNumber(backtest.num_rebalances as number | undefined, user.locale)} rebalances`} />
              </div>
              <EquityCurveChart totalReturn={totalReturn} locale={user.locale} />
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
        <FeatureImportanceChart rows={overview.top_features} locale={user.locale} />
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
            { key: "num_rebalances", label: "Rebalances" },
            { key: "backtest_end", label: "Backtest End" }
          ]}
          emptyLabel={copy.common.noRows}
          locale={user.locale}
        />
      </Panel>

      <Panel title="Model Profiles">
        <DataTable
          rows={profiles}
          columns={[
            { key: "name", label: "Name" },
            { key: "label", label: "Label" },
            { key: "label_horizon", label: "Label Horizon" },
            { key: "label_threshold", label: "Label Threshold" },
            { key: "backtest_rebalance_every", label: "Rebalance Every" },
            { key: "backtest_top_k", label: "Backtest Top K" }
          ]}
          emptyLabel={copy.common.noRows}
          locale={user.locale}
        />
      </Panel>
    </Shell>
  );
}
