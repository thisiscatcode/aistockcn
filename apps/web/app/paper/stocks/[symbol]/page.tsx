import { MetricCard, Panel } from "@/components/cards";
import { Shell } from "@/components/shell";
import { DataTable } from "@/components/table";
import { getPaperDbStock, getPaperDbStockLedger, getPaperDbStockSelectionHistory } from "@/lib/api";
import { requireAuth } from "@/lib/auth";
import { formatDate, formatDisplayValue, formatNumber } from "@/lib/format";

export const dynamic = "force-dynamic";

type DashboardRow = Record<string, unknown>;

function normalizeSymbol(value: unknown): string {
  const text = String(value ?? "").trim().toUpperCase();
  if (!text) {
    return "";
  }
  if (text.includes(".")) {
    return text.split(".", 2)[1] ?? text;
  }
  return /^\d+$/.test(text) ? text.padStart(6, "0") : text;
}

function signedTone(value: unknown) {
  const numeric = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(numeric) || numeric === 0) {
    return "neutral";
  }
  return numeric > 0 ? "positive" : "negative";
}

function stockNameFrom(row: DashboardRow, fallback?: unknown): string | null {
  const name = String(row.name ?? row.stock_name ?? row.security_name ?? fallback ?? "").trim();
  return name || null;
}

function stockCell(symbol: string, name?: unknown) {
  const normalized = normalizeSymbol(symbol);
  const stockName = stockNameFrom({}, name);
  return {
    symbol: normalized,
    symbol_detail: stockName,
    symbol_href: normalized ? `/paper/stocks/${normalized}` : undefined,
    code: normalized,
    code_detail: stockName,
    code_href: normalized ? `/paper/stocks/${normalized}` : undefined,
  };
}

function orderDisplayRow(row: DashboardRow, symbol: string, name?: unknown) {
  return {
    ...stockCell(symbol || String(row.symbol ?? ""), name ?? row.name),
    broker_order_id: row.broker_order_id ?? null,
    side: String(row.side ?? "").toUpperCase(),
    order_status: row.order_status ?? null,
    quantity: row.quantity ?? null,
    price: row.price ?? null,
    dealt_qty: row.dealt_qty ?? null,
    dealt_avg_price: row.dealt_avg_price ?? null,
    created_at: row.created_at ?? null,
    updated_at: row.updated_at ?? null,
  };
}

function fillDisplayRow(row: DashboardRow, symbol: string, name?: unknown) {
  return {
    ...stockCell(symbol || String(row.symbol ?? ""), name ?? row.name),
    created_at: row.created_at ?? null,
    broker_order_id: row.broker_order_id ?? null,
    side: String(row.side ?? "").toUpperCase(),
    quantity: row.quantity ?? null,
    price: row.price ?? null,
    notional: row.notional ?? null,
  };
}

function ledgerDisplayRow(row: DashboardRow, symbol: string, name?: unknown) {
  const realizedPnl = row.realized_pnl ?? null;
  const cumulativeRealizedPnl = row.cumulative_realized_pnl ?? null;
  return {
    ...stockCell(symbol || String(row.symbol ?? ""), name ?? row.name),
    created_at: row.created_at ?? null,
    broker_order_id: row.broker_order_id ?? null,
    side: String(row.side ?? "").toUpperCase(),
    quantity: row.quantity ?? null,
    price: row.price ?? null,
    notional: row.notional ?? null,
    avg_cost_before: row.avg_cost_before ?? null,
    realized_pnl: realizedPnl,
    realized_pnl_tone: signedTone(realizedPnl),
    cumulative_realized_pnl: cumulativeRealizedPnl,
    cumulative_realized_pnl_tone: signedTone(cumulativeRealizedPnl),
    position_quantity_after: row.position_quantity_after ?? null,
    avg_cost_after: row.avg_cost_after ?? null,
  };
}

function dailyDisplayRow(row: DashboardRow) {
  const realizedPnl = row.realized_pnl ?? null;
  return {
    trade_date: row.trade_date ?? null,
    fills: row.fills ?? null,
    buy_qty: row.buy_qty ?? null,
    sell_qty: row.sell_qty ?? null,
    buy_notional: row.buy_notional ?? null,
    sell_notional: row.sell_notional ?? null,
    realized_pnl: realizedPnl,
    realized_pnl_tone: signedTone(realizedPnl),
  };
}

function selectionDisplayRow(row: DashboardRow, symbol: string, name?: unknown) {
  const event = String(row.event ?? "");
  const rank = row.rank ?? null;
  const previousRank = row.previous_rank ?? null;
  return {
    signal_date: row.signal_date ?? null,
    event_label: row.event_label ?? row.event ?? null,
    event_label_tone: event === "DROPPED" ? "negative" : event === "STILL_LISTED" ? "positive" : "neutral",
    ...stockCell(symbol, name),
    rank,
    previous_rank: previousRank,
    streak: row.streak ?? null,
    score: row.score ?? null,
    close: row.close ?? null,
    bias_20: row.bias_20 ?? null,
    pct_chg_5d: row.pct_chg_5d ?? null,
    pct_chg_20d: row.pct_chg_20d ?? null,
    profile_label: row.profile_label ?? row.profile_name ?? null,
    order_sides: row.order_sides ?? [],
    buy_order_count: row.buy_order_count ?? null,
    sell_order_count: row.sell_order_count ?? null,
    reason: row.reason ?? null,
  };
}

export default async function PaperStockPage({ params }: { params: Promise<{ symbol: string }> }) {
  const user = await requireAuth();
  const { symbol: rawSymbol } = await params;
  const symbol = normalizeSymbol(rawSymbol);
  const [detail, ledgerResult, selectionHistory] = await Promise.all([
    getPaperDbStock(symbol, 5000),
    getPaperDbStockLedger(symbol, 1000, 5000),
    getPaperDbStockSelectionHistory(symbol, 5000),
  ]);
  const summary = detail.summary ?? {};
  const stockName = stockNameFrom(summary, selectionHistory.name ?? ledgerResult.name);
  const displaySymbol = String(summary.display_symbol ?? selectionHistory.display_symbol ?? ledgerResult.display_symbol ?? symbol);
  const ledgerRows = (ledgerResult.ledger as DashboardRow[]).map((row) => ledgerDisplayRow(row, symbol, stockName));
  const dailyRows = (ledgerResult.daily as DashboardRow[]).map(dailyDisplayRow);
  const orderRows = (detail.recent_orders as DashboardRow[]).map((row) => orderDisplayRow(row, symbol, stockName));
  const fillRows = (detail.recent_fills as DashboardRow[]).map((row) => fillDisplayRow(row, symbol, stockName));
  const selectionRows = (selectionHistory.events as DashboardRow[]).map((row) => selectionDisplayRow(row, symbol, stockName));
  const latestSelectionEvent = selectionHistory.latest_event ?? null;
  const latestEventLabel = latestSelectionEvent ? String(latestSelectionEvent.event_label ?? latestSelectionEvent.event ?? "—") : "No list history";
  const latestEventDate = latestSelectionEvent ? formatDate(latestSelectionEvent.signal_date, user.locale) : "—";
  const latestScore = selectionHistory.latest_score ?? {};

  const ledgerColumns = [
    { key: "created_at", label: "Filled At" },
    { key: "symbol", label: "Symbol" },
    { key: "broker_order_id", label: "Order ID" },
    { key: "side", label: "Side" },
    { key: "quantity", label: "Qty" },
    { key: "price", label: "Price" },
    { key: "notional", label: "Notional" },
    { key: "avg_cost_before", label: "Avg Cost Before" },
    { key: "realized_pnl", label: "Realized P/L" },
    { key: "cumulative_realized_pnl", label: "Cumulative Realized P/L" },
    { key: "position_quantity_after", label: "Qty After" },
    { key: "avg_cost_after", label: "Avg Cost After" },
  ];
  const dailyColumns = [
    { key: "trade_date", label: "Date" },
    { key: "fills", label: "Fills" },
    { key: "buy_qty", label: "Buy Qty" },
    { key: "sell_qty", label: "Sell Qty" },
    { key: "buy_notional", label: "Buy Notional" },
    { key: "sell_notional", label: "Sell Notional" },
    { key: "realized_pnl", label: "Realized P/L" },
  ];
  const orderColumns = [
    { key: "broker_order_id", label: "Order ID" },
    { key: "symbol", label: "Symbol" },
    { key: "side", label: "Side" },
    { key: "order_status", label: "Status" },
    { key: "quantity", label: "Qty" },
    { key: "price", label: "Price" },
    { key: "dealt_qty", label: "Dealt Qty" },
    { key: "dealt_avg_price", label: "Dealt Avg Price" },
    { key: "created_at", label: "Created At" },
    { key: "updated_at", label: "Updated At" },
  ];
  const fillColumns = [
    { key: "created_at", label: "Filled At" },
    { key: "symbol", label: "Symbol" },
    { key: "broker_order_id", label: "Order ID" },
    { key: "side", label: "Side" },
    { key: "quantity", label: "Qty" },
    { key: "price", label: "Price" },
    { key: "notional", label: "Notional" },
  ];
  const selectionColumns = [
    { key: "signal_date", label: "Signal Date" },
    { key: "event_label", label: "Event" },
    { key: "code", label: "Code" },
    { key: "rank", label: "Rank" },
    { key: "previous_rank", label: "Prev Rank" },
    { key: "streak", label: "Streak" },
    { key: "score", label: "Score" },
    { key: "close", label: "Signal Close" },
    { key: "bias_20", label: "20D Bias" },
    { key: "pct_chg_5d", label: "5D Chg" },
    { key: "pct_chg_20d", label: "20D Chg" },
    { key: "profile_label", label: "Profile" },
    { key: "order_sides", label: "Paper Orders" },
    { key: "buy_order_count", label: "Plan Buys" },
    { key: "sell_order_count", label: "Plan Sells" },
    { key: "reason", label: "Reason" },
  ];

  return (
    <Shell
      title={`${stockName ? `${stockName} ` : ""}${formatDisplayValue(displaySymbol, { locale: user.locale, key: "symbol" })}`}
      subtitle="Paper trading ledger and ranking history"
      locale={user.locale}
      username={user.username}
      role={user.role}
    >
      {detail.error ? <p className="banner banner-error">Postgres data unavailable: {detail.error}</p> : null}
      {ledgerResult.error ? <p className="banner banner-error">Ledger unavailable: {ledgerResult.error}</p> : null}
      {selectionHistory.error ? <p className="banner banner-error">Selection history unavailable: {selectionHistory.error}</p> : null}

      <section className="metrics-grid">
        <MetricCard label="Stock Name" value={stockName ?? "—"} hint={displaySymbol} />
        <MetricCard label="Quantity" value={formatDisplayValue(summary.quantity, { locale: user.locale, key: "quantity" })} hint={`${formatNumber(Number(summary.fills_count ?? 0), user.locale)} fills`} />
        <MetricCard label="Avg Cost" value={formatDisplayValue(summary.avg_cost, { locale: user.locale, key: "avg_cost" })} hint="Remaining position cost basis" />
        <MetricCard label="Diluted Cost" value={formatDisplayValue(summary.diluted_cost, { locale: user.locale, key: "diluted_cost" })} hint="After realized P/L allocation" />
        <MetricCard label="Last Price" value={formatDisplayValue(summary.last_price, { locale: user.locale, key: "last_price" })} hint={formatDisplayValue(summary.market_value, { locale: user.locale, key: "market_value" })} />
        <MetricCard label="Realized P/L" value={formatDisplayValue(summary.realized_pnl, { locale: user.locale, key: "realized_pnl" })} hint={`${formatNumber(Number(summary.orders_count ?? 0), user.locale)} orders`} />
        <MetricCard label="Current Unrealized P/L" value={formatDisplayValue(summary.unrealized_pnl, { locale: user.locale, key: "unrealized_pnl" })} hint={`Total ${formatDisplayValue(summary.total_pnl, { locale: user.locale, key: "total_pnl" })}`} />
        <MetricCard label="Latest List Event" value={latestEventLabel} hint={latestEventDate} />
        <MetricCard label="Latest Stored Score" value={formatDisplayValue(latestScore.score, { locale: user.locale, key: "score" })} hint={formatDisplayValue(latestScore.close, { locale: user.locale, key: "close" })} />
      </section>

      <Panel title="Ranking History" aside={<span className="pill">{formatNumber(selectionRows.length, user.locale)} events</span>}>
        <p className="table-note">
          One row per signal date: first listing, consecutive listing, and the first date the stock dropped from the paper target list.
        </p>
        <DataTable rows={selectionRows} columns={selectionColumns} emptyLabel="No ranking history was found for this symbol." locale={user.locale} pageSize={50} />
      </Panel>

      <Panel title="Trade Ledger" aside={<span className="pill">{formatNumber(ledgerResult.rows, user.locale)} rows</span>}>
        <DataTable rows={ledgerRows} columns={ledgerColumns} emptyLabel="No fills for this symbol." locale={user.locale} pageSize={50} />
      </Panel>

      <Panel title="Daily Summary" aside={<span className="pill">{formatNumber(dailyRows.length, user.locale)} days</span>}>
        <DataTable rows={dailyRows} columns={dailyColumns} emptyLabel="No daily activity for this symbol." locale={user.locale} pageSize={25} />
      </Panel>

      <Panel title="Recent Orders" aside={<span className="pill">{formatNumber(orderRows.length, user.locale)} rows</span>}>
        <DataTable rows={orderRows} columns={orderColumns} emptyLabel="No orders for this symbol." locale={user.locale} pageSize={25} />
      </Panel>

      <Panel title="Recent Fills" aside={<span className="pill">{formatNumber(fillRows.length, user.locale)} rows</span>}>
        <DataTable rows={fillRows} columns={fillColumns} emptyLabel="No fills for this symbol." locale={user.locale} pageSize={25} />
      </Panel>
    </Shell>
  );
}
