import { MetricCard, Panel } from "@/components/cards";
import { Shell } from "@/components/shell";
import { DataTable } from "@/components/table";
import { getPaperDbDailyDetail } from "@/lib/api";
import { requireAuth } from "@/lib/auth";
import { formatDisplayValue, formatNumber } from "@/lib/format";
import { normalizeSymbol, paperStockUrl, positionColumns, positionDisplayRow } from "../../position-table";

export const dynamic = "force-dynamic";

type DashboardRow = Record<string, unknown>;

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

function formatSignedNumber(value: number | null) {
  if (value === null) {
    return "—";
  }
  const formatted = new Intl.NumberFormat("en-US", {
    maximumFractionDigits: 2,
    minimumFractionDigits: Number.isInteger(value) ? 0 : 2
  }).format(Math.abs(value));
  return `${value > 0 ? "+" : value < 0 ? "-" : ""}${formatted}`;
}

function fillDisplayRow(row: DashboardRow) {
  const symbol = normalizeSymbol(row.symbol);
  const name = String(row.name ?? row.stock_name ?? row.security_name ?? "").trim();
  return {
    created_at: row.created_at ?? null,
    broker_order_id: row.broker_order_id ?? null,
    symbol,
    symbol_detail: name || undefined,
    symbol_href: paperStockUrl(row.symbol),
    side: String(row.side ?? "").toUpperCase(),
    quantity: row.quantity ?? null,
    price: row.price ?? null,
    notional: row.notional ?? null,
  };
}

export default async function HoldingsDailyPage({ params }: { params: Promise<{ tradeDate: string }> }) {
  const user = await requireAuth();
  const { tradeDate } = await params;
  const result = await getPaperDbDailyDetail(tradeDate, 5000);
  const day = (result.day ?? {}) as DashboardRow;
  const fills = ((day.fills as DashboardRow[] | undefined) ?? []).map(fillDisplayRow);
  const positions = ((day.positions as DashboardRow[] | undefined) ?? []).map(positionDisplayRow);
  const realizedPnl = asNumber(day.realized_pnl);

  const fillColumns = [
    { key: "created_at", label: "Filled At" },
    { key: "broker_order_id", label: "Order ID" },
    { key: "symbol", label: "Symbol" },
    { key: "side", label: "Side" },
    { key: "quantity", label: "Qty" },
    { key: "price", label: "Price" },
    { key: "notional", label: "Notional" },
  ];
  return (
    <Shell
      title={`Daily Trades ${result.trade_date}`}
      subtitle="Actual trades and reconstructed position status"
      locale={user.locale}
      username={user.username}
      role={user.role}
    >
      {result.error ? <p className="banner banner-error">Daily data unavailable: {result.error}</p> : null}
      {!result.error && !result.day ? <p className="banner banner-error">No actual trades recorded for this date.</p> : null}

      <section className="metrics-grid">
        <MetricCard label="Realized P/L" value={formatSignedNumber(realizedPnl)} hint="Actual fills only" />
        <MetricCard label="Trades" value={formatNumber(asNumber(day.fills_rows) ?? fills.length, user.locale)} hint="Filled trades" />
        <MetricCard label="Positions" value={formatNumber(asNumber(day.positions_rows) ?? positions.length, user.locale)} hint="After this date" />
        <MetricCard label="Buy Notional" value={formatDisplayValue(day.buy_notional, { locale: user.locale, key: "buy_notional" })} hint={`Buy Qty ${formatDisplayValue(day.buy_qty, { locale: user.locale, key: "buy_qty" })}`} />
        <MetricCard label="Sell Notional" value={formatDisplayValue(day.sell_notional, { locale: user.locale, key: "sell_notional" })} hint={`Sell Qty ${formatDisplayValue(day.sell_qty, { locale: user.locale, key: "sell_qty" })}`} />
      </section>

      <Panel title="Actual Trades" aside={<span className="pill">{formatNumber(fills.length, user.locale)} rows</span>}>
        <DataTable rows={fills} columns={fillColumns} emptyLabel="No filled trades recorded for this date." locale={user.locale} pageSize={50} />
      </Panel>

      <Panel title="Actual Position Status" aside={<span className="pill">{formatNumber(positions.length, user.locale)} rows</span>}>
        <DataTable rows={positions} columns={positionColumns} emptyLabel="No open positions after this date." locale={user.locale} pageSize={50} />
      </Panel>
    </Shell>
  );
}
