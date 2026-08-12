import Link from "next/link";
import { redirect } from "next/navigation";

import { Panel } from "@/components/cards";
import { CustomerSystemArchitecture } from "@/components/customer-system-architecture";
import { DataTable } from "@/components/table";
import {
  getBatchLogs,
  getBatchStatus,
  getDataSummary,
  getPicks,
  getStockDetail,
  getStocks
} from "@/lib/api";
import { getCurrentUser } from "@/lib/auth";
import { formatDate, formatDateRange, formatDateTime, formatNumber } from "@/lib/format";
import { getMessages } from "@/lib/i18n";

function formatShortKlineDate(value: unknown) {
  if (!value) {
    return "—";
  }
  const normalizedValue = typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value)
    ? `${value}T00:00:00Z`
    : String(value);
  const date = new Date(normalizedValue);
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
    timeZone: "UTC"
  }).format(date);
}

export async function CustomerHomePage() {
  const user = await getCurrentUser();
  if (user) {
    redirect("/overview");
  }

  const copy = getMessages("en");
  const [status, logs, data, picks, stocks] = await Promise.all([
    getBatchStatus().catch(() => null),
    getBatchLogs(16).catch(() => null),
    getDataSummary().catch(() => null),
    getPicks(10).catch(() => null),
    getStocks(12).catch(() => [])
  ]);

  const latestLines = logs?.lines.slice(-8) ?? [];
  const previewCode = stocks[0]?.code ?? data?.sample_codes[0] ?? "000001";
  const detail = await getStockDetail(previewCode).catch(() => null);
  const latestKlineRows = (detail?.kline.tail ?? []).slice().reverse();
  const klinePreviewColumns = detail?.kline.columns
    .slice(0, 8)
    .filter((column) => column !== "code" && column !== "exchange");
  const klinePreviewRows = latestKlineRows.map((row) => ({
    ...row,
    date_display: formatShortKlineDate(row.date)
  }));

  return (
    <div className="page-dark customer-home-page">
      <div className="shell shell-dark customer-home-shell">
        <header className="hero-landing customer-home-hero">
          <section className="hero-landing-stage">
            <div className="hero-landing-grid">
              <div className="hero-panel-copy-wrap">
                <p className="eyebrow hero-dark-eyebrow">{copy.brand}</p>
                <h1 className="text-gradient-accent">AiStockCN</h1>
                <p className="hero-platform-title">Systematic Equity Research Platform</p>
                <p className="hero-panel-copy hero-panel-copy-lead">
                  From raw data to live trades. Research market data, model signals, walk-forward results and
                  broker-connected paper execution from one operating platform.
                </p>
                <p className="hero-panel-note">
                  <span className="hero-stack-label">Core platform:</span> market-data pipelines, feature engineering,
                  LightGBM models, signal ranking, backtesting and paper-trading automation.
                </p>
              </div>

              <div className="hero-visual-stack">
                <div className="hero-panel-header hero-glass-card hero-snapshot-heading">
                  <div>
                    <p className="hero-panel-kicker">Live System Surface</p>
                    <h2>Quant Engine Snapshot</h2>
                  </div>
                  <Link
                    href="/login"
                    className="nav-link hero-login-button"
                    aria-label="Login to access the AiStockCN control panel"
                  >
                    <span className="hero-login-copy">
                      <span className="hero-login-meta">Secure Access</span>
                      <span className="hero-login-label">Login</span>
                    </span>
                    <span className="hero-login-arrow" aria-hidden="true">&rarr;</span>
                  </Link>
                </div>

                <div className="hero-panel-grid">
                  <div className="hero-panel-metric hero-live-card hero-glass-card hero-blue-top-card">
                    <span>{copy.overview.batchStatus}</span>
                    <strong className="metric-live-value">
                      <span className="metric-live-dot" aria-hidden="true" />
                      {copy.common.live}
                    </strong>
                  </div>
                  <div className="hero-panel-metric hero-glass-card hero-blue-top-card">
                    <span>{copy.overview.stocksInUniverse}</span>
                    <strong>{formatNumber(data?.stock_count, "en")}</strong>
                  </div>
                  <div className="hero-panel-metric hero-glass-card hero-blue-top-card">
                    <span>{copy.overview.topPicks}</span>
                    <strong>{formatNumber(picks?.rows, "en")}</strong>
                  </div>
                </div>
              </div>
            </div>
          </section>
        </header>

        <CustomerSystemArchitecture />

        <main className="page-content customer-home-content">
          <section className="two-col-grid">
            <Panel
              title={copy.overview.pulse}
              aside={(
                <span className={`pill ${status?.is_running ? "live" : ""}`}>
                  {status?.is_running ? copy.common.live : copy.common.idle}
                </span>
              )}
            >
              <div className="status-meta">
                <span>{copy.common.lastStateUpdate}: {formatDateTime(status?.updated_at, "en")}</span>
                <span>{copy.common.lastCode}: {status?.last_code ?? "—"}</span>
                <span>{copy.common.remaining}: {formatNumber(status?.remaining_count, "en")}</span>
                <span>{copy.common.logSource}: {logs?.source ?? "—"}</span>
              </div>
              <pre className="log-console">{latestLines.join("\n") || copy.common.noLogs}</pre>
            </Panel>

            <Panel
              title={`Latest Kline Preview · ${previewCode}`}
              aside={<span className="pill pill-preview">Visitor Preview</span>}
            >
              <div className="status-meta">
                <span>{copy.common.rows}: {formatNumber(detail?.kline.rows, "en")}</span>
                <span>Latest: {formatDate(detail?.kline.date_max, "en")}</span>
                <span>
                  {copy.common.dateRange}: {formatDateRange(
                    { date_min: detail?.kline.date_min, date_max: detail?.kline.date_max },
                    "en",
                    copy.common.to
                  )}
                </span>
              </div>
              <div className="landing-kline-table">
                <DataTable
                  rows={klinePreviewRows}
                  columns={klinePreviewColumns}
                  emptyLabel={copy.common.noRows}
                  locale="en"
                />
              </div>
            </Panel>
          </section>
        </main>
      </div>
    </div>
  );
}
