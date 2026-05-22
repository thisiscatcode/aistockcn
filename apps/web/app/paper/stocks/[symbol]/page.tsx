import { MetricCard, Panel } from "@/components/cards";
import { Shell } from "@/components/shell";
import { DataTable } from "@/components/table";
import { getPaperDbStock, getPaperDbStockLedger } from "@/lib/api";
import { requireAuth } from "@/lib/auth";
import { formatDisplayValue, formatNumber } from "@/lib/format";

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

function orderDisplayRow(row: DashboardRow) {
  return {
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

function fillDisplayRow(row: DashboardRow) {
  return {
    created_at: row.created_at ?? null,
    broker_order_id: row.broker_order_id ?? null,
    side: String(row.side ?? "").toUpperCase(),
    quantity: row.quantity ?? null,
    price: row.price ?? null,
    notional: row.notional ?? null,
  };
}

function ledgerDisplayRow(row: DashboardRow) {
  const realizedPnl = row.realized_pnl ?? null;
  const cumulativeRealizedPnl = row.cumulative_realized_pnl ?? null;
  return {
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

export default async function PaperStockPage({ params }: { params: Promise<{ symbol: string }> }) {
  const user = await requireAuth();
  const { symbol: rawSymbol } = await params;
  const symbol = normalizeSymbol(rawSymbol);
  const [detail, ledgerResult] = await Promise.all([
    getPaperDbStock(symbol, 5000),
    getPaperDbStockLedger(symbol, 1000, 5000),
  ]);
  const summary = detail.summary ?? {};
  const ledgerRows = (ledgerResult.ledger as DashboardRow[]).map(ledgerDisplayRow);
  const dailyRows = (ledgerResult.daily as DashboardRow[]).map(dailyDisplayRow);
  const orderRows = (detail.recent_orders as DashboardRow[]).map(orderDisplayRow);
  const fillRows = (detail.recent_fills as DashboardRow[]).map(fillDisplayRow);

  const ledgerColumns = [
    { key: "created_at", label: "Filled At" },
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
    { key: "broker_order_id", label: "Order ID" },
    { key: "side", label: "Side" },
    { key: "quantity", label: "Qty" },
    { key: "price", label: "Price" },
    { key: "notional", label: "Notional" },
  ];

  return (
    <Shell
      title={`Stock ${formatDisplayValue(summary.display_symbol ?? symbol, { locale: user.locale, key: "symbol" })}`}
      subtitle="Postgres trade ledger"
      locale={user.locale}
      username={user.username}
      role={user.role}
    >
      {detail.error ? <p className="banner banner-error">Postgres data unavailable: {detail.error}</p> : null}
      {ledgerResult.error ? <p className="banner banner-error">Ledger unavailable: {ledgerResult.error}</p> : null}

      <section className="metrics-grid">
        <MetricCard label="Quantity" value={formatDisplayValue(summary.quantity, { locale: user.locale, key: "quantity" })} hint={`${formatNumber(Number(summary.fills_count ?? 0), user.locale)} fills`} />
        <MetricCard label="Avg Cost" value={formatDisplayValue(summary.avg_cost, { locale: user.locale, key: "avg_cost" })} hint="Remaining position cost basis" />
        <MetricCard label="Diluted Cost" value={formatDisplayValue(summary.diluted_cost, { locale: user.locale, key: "diluted_cost" })} hint="After realized P/L allocation" />
        <MetricCard label="Last Price" value={formatDisplayValue(summary.last_price, { locale: user.locale, key: "last_price" })} hint={formatDisplayValue(summary.market_value, { locale: user.locale, key: "market_value" })} />
        <MetricCard label="Realized P/L" value={formatDisplayValue(summary.realized_pnl, { locale: user.locale, key: "realized_pnl" })} hint={`${formatNumber(Number(summary.orders_count ?? 0), user.locale)} orders`} />
        <MetricCard label="Current Unrealized P/L" value={formatDisplayValue(summary.unrealized_pnl, { locale: user.locale, key: "unrealized_pnl" })} hint={`Total ${formatDisplayValue(summary.total_pnl, { locale: user.locale, key: "total_pnl" })}`} />
      </section>

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
