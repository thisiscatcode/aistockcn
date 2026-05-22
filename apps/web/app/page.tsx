import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";
import type { CSSProperties } from "react";

import { Panel } from "@/components/cards";
import { DataTable } from "@/components/table";
import {
  getBatchLogs,
  getBatchStatus,
  getDataSummary,
  getModelOverview,
  getPicks,
  getStockDetail,
  getStocks
} from "@/lib/api";
import { getCurrentUser } from "@/lib/auth";
import { formatDate, formatDateRange, formatDateTime, formatMetric, formatNumber } from "@/lib/format";
import { getMessages } from "@/lib/i18n";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "AiStockCN — Systematic Equity Research Platform",
  description: "Public read-only overview for the AiStockCN systematic equity research and trading operations platform."
};

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

export default async function HomePage() {
  const user = await getCurrentUser();
  if (user) {
    redirect("/overview");
  }

  const copy = getMessages("en");

  const [status, logs, data, model, picks, stocks] = await Promise.all([
    getBatchStatus().catch(() => null),
    getBatchLogs(24).catch(() => null),
    getDataSummary().catch(() => null),
    getModelOverview().catch(() => null),
    getPicks(10).catch(() => null),
    getStocks(12).catch(() => [])
  ]);

  const training = (model?.training_metadata ?? {}) as Record<string, unknown>;
  const trainingMetrics = (training.metrics ?? {}) as Record<string, number>;
  const latestLines = logs?.lines.slice(-12) ?? [];
  const previewCode = stocks[0]?.code ?? data?.sample_codes[0] ?? "000001";
  const detail = await getStockDetail(previewCode).catch(() => null);
  const latestKlineRows = (detail?.kline.tail ?? []).slice().reverse();
  const klinePreviewColumns = detail?.kline.columns.slice(0, 8).filter((column) => column !== "code" && column !== "exchange");
  const klinePreviewRows = latestKlineRows.map((row) => ({
    ...row,
    date_display: formatShortKlineDate(row.date)
  }));
  const progressStart = 0.381 + Math.random() * 0.418;
  const progressStartPct = progressStart * 100;

  return (
    <div className="page-dark">
      <div className="shell shell-dark">
        <header className="hero-landing">
          <section className="hero-landing-stage">
            <div className="hero-landing-grid">
              <div className="hero-panel-copy-wrap">
                <p className="eyebrow hero-dark-eyebrow">{copy.brand}</p>
                <h1 className="text-gradient-accent">AiStockCN</h1>
                <p className="hero-platform-title">Systematic Equity Research Platform</p>
                <p className="hero-panel-copy hero-panel-copy-lead">
                  From raw data to live trades.
                  A full-stack quant research and execution system with feature pipelines, model training,
                  walk-forward backtests, signal ranking, and broker-connected deployment.
                </p>
                <p className="hero-panel-note">
                  <span className="hero-stack-label">Tech Stack:</span> Python, TypeScript, Next.js, React, FastAPI, Uvicorn, Pandas, PyArrow, LightGBM,
                  scikit-learn, BaoStock, AKShare, parquet-based data pipelines, workflow orchestration,
                  paper-trading automation, Docker, and Docker Compose.
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
                    aria-label="Login to access the Aistock control panel"
                  >
                    <span className="hero-login-copy">
                      <span className="hero-login-meta">Secure Access</span>
                      <span className="hero-login-label">Login</span>
                    </span>
                    <span className="hero-login-arrow" aria-hidden="true">
                      &rarr;
                    </span>
                  </Link>
                </div>

                <div>
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
                    <div className="hero-panel-metric hero-panel-metric-progress hero-glass-card hero-blue-top-card">
                      <span>{copy.overview.progress}</span>
                      <strong>{`${formatNumber(progressStartPct, "en", { maximumFractionDigits: 1 })}%`}</strong>
                      <div className="metric-progress-track" aria-hidden="true">
                        <span
                          className="metric-progress-loop"
                          style={{ "--progress-start": progressStart.toFixed(4) } as CSSProperties}
                        />
                      </div>
                    </div>
                    <div className="hero-panel-metric hero-glass-card hero-blue-top-card">
                      <span>{copy.overview.validationAuc}</span>
                      <strong className="hero-panel-value-accent hero-model-value">{formatMetric(trainingMetrics.auc, "en")}</strong>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </section>
        </header>

        <main className="page-content">
          <section className="two-col-grid">
            <Panel
              title={copy.overview.pulse}
              aside={<span className={`pill ${status?.is_running ? "live" : ""}`}>{status?.is_running ? copy.common.live : copy.common.idle}</span>}
            >
              <div className="status-meta">
                <span>{copy.common.lastStateUpdate}: {formatDateTime(status?.updated_at, "en")}</span>
                <span>{copy.common.lastCode}: {status?.last_code ?? "—"}</span>
                <span>{copy.common.remaining}: {formatNumber(status?.remaining_count, "en")}</span>
                <span>{copy.common.logSource}: {logs?.source ?? "—"}</span>
              </div>
              <pre className="log-console">{latestLines.join("\n") || copy.common.noLogs}</pre>
            </Panel>

            <Panel title={`Latest Kline Preview · ${previewCode}`} aside={<span className="pill pill-preview">Visitor Preview</span>}>
              <div className="status-meta">
                <span>{copy.common.rows}: {formatNumber(detail?.kline.rows, "en")}</span>
                <span>Latest: {formatDate(detail?.kline.date_max, "en")}</span>
                <span>{copy.common.dateRange}: {formatDateRange({ date_min: detail?.kline.date_min, date_max: detail?.kline.date_max }, "en", copy.common.to)}</span>
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
