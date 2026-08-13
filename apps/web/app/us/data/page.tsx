import { MetricCard, Panel } from "@/components/cards";
import { DataTable } from "@/components/table";
import { getUsMarketSummary, getUsStocks } from "@/lib/api";
import { requireAuth } from "@/lib/auth";
import { formatDate, formatNumber } from "@/lib/format";
import { UsShell } from "../us-components";

export const dynamic = "force-dynamic";

export default async function UsDataPage({
  searchParams
}: {
  searchParams?: Promise<{ search?: string }>;
}) {
  const user = await requireAuth();
  const params = (await searchParams) ?? {};
  const search = String(params.search ?? "").trim();
  const [summary, response] = await Promise.all([
    getUsMarketSummary(),
    getUsStocks(search, 100)
  ]);
  const rows = response.stocks.map((stock) => ({
    symbol: stock.symbol,
    symbol_href: `/research?symbol=${encodeURIComponent(stock.symbol)}`,
    company: stock.name,
    exchange: stock.exchange,
    industry: stock.industry,
    trade_date: stock.trade_date,
    close_usd: stock.close,
    price_diff: stock.price_diff,
    volume: stock.volume,
    market_cap_usd: stock.market_cap
  }));

  return (
    <UsShell user={user} title="US Market Data" subtitle="NASDAQ and NYSE universe">
      <section className="metrics-grid">
        <MetricCard label="Active Companies" value={formatNumber(summary.coverage.active_symbols, user.locale)} />
        <MetricCard label="Stored Bars" value={formatNumber(summary.coverage.total_bars, user.locale)} hint="Daily observations" />
        <MetricCard label="Date Range" value={`${formatDate(summary.coverage.first_trade_date, user.locale)} → ${formatDate(summary.coverage.latest_trade_date, user.locale)}`} hint={`${summary.coverage.trading_dates} trading days`} />
        <MetricCard label="Latest Coverage" value={`${formatNumber(summary.coverage.latest_coverage_pct, user.locale, { maximumFractionDigits: 1 })}%`} />
      </section>

      <Panel title="Company Search" aside={<span className="pill">{formatNumber(response.total, user.locale)} matches</span>}>
        <form className="us-stock-search" action="/us/data" method="get">
          <input name="search" defaultValue={search} placeholder="Search AAPL, company name or industry" aria-label="Search US companies" />
          <button type="submit">Search</button>
          {search ? <a href="/us/data">Clear</a> : null}
        </form>
        <DataTable
          rows={rows}
          columns={[
            { key: "symbol", label: "Symbol" },
            { key: "company", label: "Company" },
            { key: "exchange", label: "Exchange" },
            { key: "industry", label: "Industry" },
            { key: "trade_date", label: "Market Date" },
            { key: "close_usd", label: "Close (USD)" },
            { key: "price_diff", label: "Change" },
            { key: "volume", label: "Volume" },
            { key: "market_cap_usd", label: "Market Cap (USD)" }
          ]}
          locale={user.locale}
          pageSize={25}
          emptyLabel="No US companies match this search."
        />
      </Panel>
    </UsShell>
  );
}
