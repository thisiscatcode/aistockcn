import { Shell } from "@/components/shell";
import { getPortfolioOverview, type OverviewPerformancePoint, type OverviewTopPick } from "@/lib/api";
import { requireAuth } from "@/lib/auth";
import { formatDate, formatDateTime, formatDisplayValue, formatNumber } from "@/lib/format";
import type { PanelLocale } from "@/lib/i18n";

export const dynamic = "force-dynamic";

function displayName(username: string) {
  return username
    .split(/[._\s-]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ") || "Portfolio Manager";
}

function chartPath(points: Array<{ x: number; y: number }>) {
  return points.map((point, index) => `${index === 0 ? "M" : "L"} ${point.x.toFixed(1)} ${point.y.toFixed(1)}`).join(" ");
}

function toneFromNumber(value: unknown) {
  if (typeof value !== "number" || Number.isNaN(value) || value === 0) {
    return "neutral";
  }
  return value > 0 ? "positive" : "negative";
}

function formatPercent(value: unknown, locale: PanelLocale) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "—";
  }
  return `${formatNumber(value * 100, locale, { maximumFractionDigits: 2 })}%`;
}

function scoreWidth(value: unknown) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return 0;
  }
  const percent = Math.abs(value) <= 1 ? value * 100 : value;
  return Math.max(0, Math.min(100, percent));
}

function formatScore(value: unknown, locale: PanelLocale) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "—";
  }
  const percent = Math.abs(value) <= 1 ? value * 100 : value;
  return `${formatNumber(percent, locale, { maximumFractionDigits: 1 })}%`;
}

function formatWeight(value: unknown, locale: PanelLocale) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "—";
  }
  return `${formatNumber(value * 100, locale, { maximumFractionDigits: 2 })}%`;
}

function PortfolioPerformanceChart({
  points,
  benchmarkName,
  locale
}: {
  points: OverviewPerformancePoint[];
  benchmarkName: string;
  locale: PanelLocale;
}) {
  const chartRows = points.filter((point) => typeof point.portfolio_value === "number" && !Number.isNaN(point.portfolio_value));

  if (chartRows.length < 2) {
    return (
      <div className="portfolio-chart-card">
        <div className="portfolio-card-header">
          <div>
            <p className="portfolio-section-kicker">Live Account Data</p>
            <h2>Portfolio Performance vs {benchmarkName}</h2>
          </div>
        </div>
        <p className="empty-state">No real performance history is available yet.</p>
      </div>
    );
  }

  const values = chartRows.flatMap((row) => {
    const rowValues = [row.portfolio_value as number];
    if (typeof row.benchmark_value === "number" && !Number.isNaN(row.benchmark_value)) {
      rowValues.push(row.benchmark_value);
    }
    return rowValues;
  });
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = Math.max(max - min, 1);
  const width = 960;
  const height = 330;
  const padding = { top: 28, right: 28, bottom: 42, left: 64 };
  const chartWidth = width - padding.left - padding.right;
  const chartHeight = height - padding.top - padding.bottom;
  const scaleX = (index: number) => padding.left + (chartWidth / (chartRows.length - 1)) * index;
  const scaleY = (value: number) => padding.top + (1 - (value - min) / range) * chartHeight;
  const portfolioPoints = chartRows.map((row, index) => ({ x: scaleX(index), y: scaleY(row.portfolio_value as number) }));
  const benchmarkPoints = chartRows
    .map((row, index) => (
      typeof row.benchmark_value === "number" && !Number.isNaN(row.benchmark_value)
        ? { x: scaleX(index), y: scaleY(row.benchmark_value) }
        : null
    ))
    .filter((point): point is { x: number; y: number } => point !== null);
  const first = chartRows[0];
  const last = chartRows[chartRows.length - 1];

  return (
    <div className="portfolio-chart-card">
      <div className="portfolio-card-header">
        <div>
          <p className="portfolio-section-kicker">Live Account Data</p>
          <h2>Portfolio Performance vs {benchmarkName}</h2>
        </div>
        <div className="portfolio-chart-legend" aria-label="Chart legend">
          <span><i className="portfolio-legend-line portfolio-legend-ai" /> Account Equity</span>
          <span><i className="portfolio-legend-line portfolio-legend-benchmark" /> {benchmarkName}</span>
        </div>
      </div>

      <svg className="portfolio-performance-svg" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`Line chart comparing account equity and ${benchmarkName}`}>
        {[0, 1, 2, 3].map((line) => {
          const y = padding.top + (chartHeight / 3) * line;
          return <path key={line} className="portfolio-grid-line" d={`M ${padding.left} ${y} L ${width - padding.right} ${y}`} />;
        })}
        {benchmarkPoints.length > 1 ? <path className="portfolio-benchmark-line" d={chartPath(benchmarkPoints)} /> : null}
        <path className="portfolio-ai-line" d={chartPath(portfolioPoints)} />
        {portfolioPoints.map((point, index) => (
          <circle key={`${chartRows[index].date ?? index}-${index}`} className="portfolio-ai-point" cx={point.x} cy={point.y} r="4.5" />
        ))}
        <text className="portfolio-axis-label" x={padding.left} y={height - 14} textAnchor="start">
          {formatDate(first.date, locale)}
        </text>
        <text className="portfolio-axis-label" x={width - padding.right} y={height - 14} textAnchor="end">
          {formatDate(last.date, locale)}
        </text>
        {[min, min + range / 2, max].map((tick) => (
          <text key={tick} className="portfolio-axis-label" x={14} y={scaleY(tick) + 4}>
            {formatNumber(tick, locale, { maximumFractionDigits: 1 })}
          </text>
        ))}
      </svg>
    </div>
  );
}

function KpiCard({
  label,
  value,
  detail,
  tone = "neutral"
}: {
  label: string;
  value: string;
  detail?: string;
  tone?: "positive" | "negative" | "neutral";
}) {
  return (
    <article className={`overview-kpi-card overview-kpi-${tone}`}>
      <p className="overview-kpi-label">{label}</p>
      <strong>{value}</strong>
      {detail ? <span>{detail}</span> : null}
    </article>
  );
}

function signalTone(signalType?: string | null) {
  const normalized = String(signalType ?? "").toUpperCase();
  if (normalized === "BUY") {
    return "signal-buy";
  }
  if (normalized === "SELL") {
    return "signal-short";
  }
  return "";
}

export default async function OverviewPage() {
  const user = await requireAuth();
  const name = displayName(user.username);
  const overview = await getPortfolioOverview();
  const benchmarkName = overview.performance.benchmark.name;
  const hasBlockingWarnings = overview.warnings.length > 0;

  return (
    <Shell
      title={`Good Morning, ${name} - Here is your portfolio summary.`}
      subtitle=""
      locale={user.locale}
      username={user.username}
      role={user.role}
    >
      <section className="overview-command-bar" aria-label="Overview status">
        <span className={`ai-health-badge ${hasBlockingWarnings ? "ai-health-badge-warn" : ""}`}>
          {hasBlockingWarnings ? "Overview Data: Check Needed" : "Overview Data: Live & Synced"}
        </span>
        <span className="overview-market-note">
          Data source: /api/overview/portfolio from paper account state, performance history, strategy targets, and model picks.
        </span>
      </section>

      {overview.warnings.length ? (
        <section className="portfolio-warning-list" aria-label="Overview data warnings">
          {overview.warnings.map((warning) => (
            <p key={warning}>{warning}</p>
          ))}
        </section>
      ) : null}

      <section className="overview-kpi-grid" aria-label="Portfolio key performance indicators">
        <KpiCard
          label="Account Equity"
          value={formatDisplayValue(overview.account.total_assets, { locale: user.locale, key: "total_assets" })}
          detail={`Updated ${formatDateTime(overview.account.updated_at ?? overview.generated_at, user.locale)}`}
        />
        <KpiCard
          label="Today P&L"
          value={formatDisplayValue(overview.account.today_pnl, { locale: user.locale, key: "today_pnl" })}
          detail={formatPercent(overview.account.today_pnl_pct, user.locale)}
          tone={toneFromNumber(overview.account.today_pnl)}
        />
        <KpiCard
          label="Holdings / Pending Buy / Pending Sell"
          value={`${formatNumber(overview.positions.holding_count, user.locale)} / ${formatNumber(overview.positions.pending_buy_count, user.locale)} / ${formatNumber(overview.positions.pending_sell_count, user.locale)}`}
          detail={`${formatNumber(overview.positions.open_order_count, user.locale)} open orders`}
        />
        <KpiCard
          label="Pending Actions"
          value={formatNumber(overview.signals.pending_actions, user.locale)}
          detail={`Signal date ${formatDate(overview.signals.latest_signal_date, user.locale)}`}
        />
      </section>

      <PortfolioPerformanceChart points={overview.performance.points} benchmarkName={benchmarkName} locale={user.locale} />

      <section className="portfolio-table-card">
        <div className="portfolio-card-header">
          <div>
            <p className="portfolio-section-kicker">Actionable Insights</p>
            <h2>Top AI Picks</h2>
          </div>
          <span className="portfolio-table-aside">Source: {overview.top_picks[0]?.source ?? "—"}</span>
        </div>

        <div className="portfolio-table-wrap">
          <table className="portfolio-picks-table">
            <thead>
              <tr>
                <th>Ticker/Symbol</th>
                <th>Company Name</th>
                <th>Signal Type</th>
                <th>AI Confidence Score</th>
                <th>Recommended Weight</th>
              </tr>
            </thead>
            <tbody>
              {overview.top_picks.map((pick: OverviewTopPick, index) => (
                <tr key={`${pick.code ?? "row"}-${index}`}>
                  <td><strong>{pick.code ?? "—"}</strong></td>
                  <td>{pick.name ?? "—"}</td>
                  <td>
                    <span className={`signal-badge ${signalTone(pick.signal_type)}`}>
                      {pick.signal_type ?? "—"}
                    </span>
                  </td>
                  <td>
                    <div className="confidence-cell">
                      <div className="confidence-track" aria-hidden="true">
                        <span style={{ width: `${scoreWidth(pick.confidence)}%` }} />
                      </div>
                      <strong>{formatScore(pick.confidence, user.locale)}</strong>
                    </div>
                  </td>
                  <td>{formatWeight(pick.recommended_weight, user.locale)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {overview.top_picks.length ? null : <p className="empty-state portfolio-empty-state">No real AI picks or target rows are available yet.</p>}
        </div>
      </section>
    </Shell>
  );
}
