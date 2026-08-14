import Link from "next/link";

import { MetricCard, Panel } from "@/components/cards";
import { Shell } from "@/components/shell";
import { getPortfolioOverview } from "@/lib/api";
import { requireAuth } from "@/lib/auth";
import { formatDate, formatNumber } from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function CnOverviewPage() {
  const user = await requireAuth();
  const overview = await getPortfolioOverview();
  const account = overview.account;

  return (
    <Shell title="A-Share Overview" subtitle="Market and account context" locale={user.locale} username={user.displayName} role={user.role} market="CN">
      <section className="product-stage-heading">
        <div><span className="stage-icon">▦</span><div><h1>Market Overview</h1><p>Today&apos;s account state and direct access to the full investment workflow.</p></div></div>
        <span className="capability-label status-live">Live</span>
      </section>

      {overview.warnings.length ? <section className="portfolio-warning-list">{overview.warnings.map((warning) => <p key={warning}>{warning}</p>)}</section> : null}

      <section className="metrics-grid compact-metrics">
        <MetricCard label="Account Equity" value={formatNumber(account.total_assets, user.locale, { maximumFractionDigits: 0 })} hint={account.currency || "CNY"} />
        <MetricCard label="Cash" value={formatNumber(account.cash, user.locale, { maximumFractionDigits: 0 })} />
        <MetricCard label="Market Value" value={formatNumber(account.market_value, user.locale, { maximumFractionDigits: 0 })} />
        <MetricCard label="Today P&L" value={formatNumber(account.today_pnl, user.locale, { maximumFractionDigits: 0 })} />
        <MetricCard label="Holdings" value={formatNumber(overview.positions.holding_count, user.locale)} />
        <MetricCard label="Latest Signal" value={formatDate(overview.signals.latest_signal_date, user.locale)} hint={`${formatNumber(overview.signals.pending_actions, user.locale)} pending actions`} />
      </section>

      <section className="two-col-grid">
        <Panel title="Research" aside={<Link className="panel-link" href="/cn/research">Open →</Link>}><p className="panel-copy">Search companies and inspect official disclosure evidence.</p></Panel>
        <Panel title="Quant" aside={<Link className="panel-link" href="/cn/quant">Open →</Link>}><p className="panel-copy">Review signals, methodology, walk-forward results and market data.</p></Panel>
        <Panel title="Portfolio" aside={<Link className="panel-link" href="/cn/portfolio">Open →</Link>}><p className="panel-copy">Inspect P&amp;L, current positions and validated target weights.</p></Panel>
        <Panel title="Execution" aside={<Link className="panel-link" href="/cn/execution">Open →</Link>}><p className="panel-copy">Review planned orders, order history and controlled execution.</p></Panel>
      </section>
    </Shell>
  );
}
