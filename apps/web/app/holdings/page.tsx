import { AutoRefresh } from "@/components/auto-refresh";
import { MetricCard, Panel } from "@/components/cards";
import { Shell } from "@/components/shell";
import { DataTable } from "@/components/table";
import { getPaperHoldings } from "@/lib/api";
import { requireAuth } from "@/lib/auth";
import { formatDateTime, formatDisplayValue, formatNumber } from "@/lib/format";

export const dynamic = "force-dynamic";

type DashboardRow = Record<string, unknown>;

const TERMINAL_ORDER_STATUSES = new Set([
  "CANCELLED",
  "CANCELLED_ALL",
  "CANCELLED_PART",
  "CANCELLED_PART_ALL",
  "DELETED",
  "DISABLED",
  "EXPIRED",
  "FAILED",
  "FILLED_ALL",
  "REJECTED",
  "SUBMIT_FAILED",
]);

function asNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string") {
    const parsed = Number(value.trim());
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

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

function normalizeOrderStatus(value: unknown): string {
  return String(value ?? "")
    .trim()
    .toUpperCase()
    .replace(/[-\s/]+/g, "_");
}

function isActiveOrder(row: DashboardRow): boolean {
  const status = normalizeOrderStatus(row.order_status ?? row.status);
  return Boolean(status) && !TERMINAL_ORDER_STATUSES.has(status);
}

export default async function HoldingsPage() {
  const user = await requireAuth();
  const snapshot = await getPaperHoldings(1000, 300, 5000);
  const summary = snapshot.summary ?? {};
  const positions = snapshot.positions as DashboardRow[];
  const activeOrders = (snapshot.orders as DashboardRow[]).filter(isActiveOrder);
  const computedMarketValue = positions.reduce((total, row) => total + (asNumber(row.market_value) ?? 0), 0);
  const computedUnrealizedPnl = positions.reduce((total, row) => total + (asNumber(row.unrealized_pnl) ?? 0), 0);
  const marketValue = asNumber(summary.market_value) ?? computedMarketValue;
  const unrealizedPnl = asNumber(summary.unrealized_pnl) ?? computedUnrealizedPnl;

  const positionRows = positions.map((row) => ({
    symbol: normalizeSymbol(row.symbol ?? row.code),
    name: row.name ?? row.stock_name ?? row.security_name ?? null,
    quantity: row.quantity ?? row.qty ?? null,
    available_qty: row.available_qty ?? row.can_sell_qty ?? row.pl_qty ?? null,
    market_value: row.market_value ?? null,
    last_price: row.last_price ?? row.price ?? row.current_price ?? null,
    avg_cost: row.avg_cost ?? row.cost_price ?? row.average_cost ?? null,
    unrealized_pnl: row.unrealized_pnl ?? null,
    realized_pnl: row.realized_pnl ?? null,
    pnl_ratio: row.pnl_ratio ?? row.unrealized_pnl_pct ?? null,
    currency: row.currency ?? summary.currency ?? null,
    updated_at: row.updated_at ?? row.create_time ?? snapshot.generated_at ?? null,
  }));

  const activeOrderRows = activeOrders.map((row) => {
    const quantity = asNumber(row.quantity ?? row.qty) ?? 0;
    const dealtQty = asNumber(row.dealt_qty) ?? 0;
    return {
      broker_order_id: row.broker_order_id ?? row.order_id ?? null,
      symbol: normalizeSymbol(row.symbol ?? row.code),
      side: String(row.side ?? row.trd_side ?? "").toUpperCase(),
      order_status: normalizeOrderStatus(row.order_status ?? row.status),
      quantity,
      dealt_qty: dealtQty,
      remaining_qty: Math.max(quantity - dealtQty, 0),
      price: row.price ?? null,
      created_at: row.created_at ?? row.create_time ?? null,
      updated_at: row.updated_at ?? row.create_time ?? null,
      remark: row.remark ?? null,
    };
  });

  const positionColumns = [
    { key: "symbol", label: "Code" },
    { key: "name", label: "Name" },
    { key: "quantity", label: "Qty" },
    { key: "available_qty", label: "Available" },
    { key: "market_value", label: "Market Value" },
    { key: "last_price", label: "Last Price" },
    { key: "avg_cost", label: "Avg Cost" },
    { key: "unrealized_pnl", label: "Unrealized PnL" },
    { key: "realized_pnl", label: "Realized PnL" },
    { key: "pnl_ratio", label: "PnL Ratio" },
    { key: "currency", label: "Currency" },
    { key: "updated_at", label: "Updated At" },
  ];

  const orderColumns = [
    { key: "broker_order_id", label: "Order ID" },
    { key: "symbol", label: "Code" },
    { key: "side", label: "Side" },
    { key: "order_status", label: "Status" },
    { key: "quantity", label: "Qty" },
    { key: "dealt_qty", label: "Dealt" },
    { key: "remaining_qty", label: "Remaining" },
    { key: "price", label: "Price" },
    { key: "created_at", label: "Created At" },
    { key: "updated_at", label: "Updated At" },
    { key: "remark", label: "Remark" },
  ];

  return (
    <Shell
      title="持倉"
      subtitle="Futu live positions"
      locale={user.locale}
      username={user.username}
      role={user.role}
    >
      <AutoRefresh intervalSeconds={10} />
      {snapshot.error ? <p className="banner banner-error">Futu data unavailable: {snapshot.error}</p> : null}

      <section className="metrics-grid">
        <MetricCard label="Gateway" value={snapshot.gateway.healthy ? "Live" : "Check Needed"} hint={snapshot.gateway.base_url} />
        <MetricCard
          label="Updated"
          value={formatDateTime(snapshot.generated_at, user.locale)}
          hint={`Account ${formatDisplayValue(snapshot.gateway.account_id, { locale: user.locale, key: "account_id" })}`}
        />
        <MetricCard label="Positions" value={formatNumber(snapshot.positions_rows, user.locale)} hint="Futu position list" />
        <MetricCard label="Active Orders" value={formatNumber(activeOrderRows.length, user.locale)} hint={`${formatNumber(snapshot.orders_rows, user.locale)} total orders`} />
        <MetricCard label="Total Assets" value={formatDisplayValue(summary.total_assets, { locale: user.locale, key: "total_assets" })} hint={formatDisplayValue(summary.currency, { locale: user.locale, key: "currency" })} />
        <MetricCard label="Cash" value={formatDisplayValue(summary.cash, { locale: user.locale, key: "cash" })} hint={formatDisplayValue(summary.buying_power ?? summary.power, { locale: user.locale, key: "buying_power" })} />
        <MetricCard label="Market Value" value={formatDisplayValue(marketValue, { locale: user.locale, key: "market_value" })} hint="Live holdings value" />
        <MetricCard label="Unrealized PnL" value={formatDisplayValue(unrealizedPnl, { locale: user.locale, key: "unrealized_pnl" })} hint={formatDisplayValue(summary.total_pnl, { locale: user.locale, key: "total_pnl" })} />
      </section>

      <Panel title="持倉明細" aside={<span className="pill">{formatNumber(positionRows.length, user.locale)} rows</span>}>
        <DataTable rows={positionRows} columns={positionColumns} emptyLabel="No Futu positions." locale={user.locale} pageSize={50} />
      </Panel>

      <Panel title="未完成訂單" aside={<span className="pill">{formatNumber(activeOrderRows.length, user.locale)} active</span>}>
        <DataTable rows={activeOrderRows} columns={orderColumns} emptyLabel="No active Futu orders." locale={user.locale} pageSize={25} />
      </Panel>
    </Shell>
  );
}
