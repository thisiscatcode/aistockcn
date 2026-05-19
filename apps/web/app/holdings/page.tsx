import { AutoRefresh } from "@/components/auto-refresh";
import { MetricCard, Panel } from "@/components/cards";
import { Shell } from "@/components/shell";
import { DataTable } from "@/components/table";
import { getPaperHoldings } from "@/lib/api";
import { requireAuth } from "@/lib/auth";
import { formatDateTime, formatDisplayValue, formatNumber } from "@/lib/format";

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

export default async function HoldingsPage() {
  const user = await requireAuth();
  const snapshot = await getPaperHoldings(1000, 300, 5000);
  const summary = snapshot.summary ?? {};
  const positions = snapshot.positions as DashboardRow[];
  const computedMarketValue = positions.reduce((total, row) => total + (asNumber(row.market_value) ?? 0), 0);
  const computedUnrealizedPnl = positions.reduce((total, row) => total + (asNumber(row.unrealized_pnl) ?? 0), 0);
  const marketValue = asNumber(summary.market_value) ?? computedMarketValue;
  const unrealizedPnl = asNumber(summary.unrealized_pnl) ?? computedUnrealizedPnl;

  const positionRows = positions.map((row) => ({
    code_name: [normalizeSymbol(row.symbol ?? row.code), row.name ?? row.stock_name ?? row.security_name ?? null]
      .filter(Boolean)
      .join(" / "),
    market_value: row.market_value ?? null,
    quantity: row.quantity ?? row.qty ?? null,
    last_price: row.last_price ?? row.price ?? row.current_price ?? null,
    cost: row.avg_cost ?? row.cost_price ?? row.average_cost ?? null,
  }));

  const positionColumns = [
    { key: "code_name", label: "Code / Name" },
    { key: "market_value", label: "Market Value" },
    { key: "quantity", label: "Quantity" },
    { key: "last_price", label: "Last Price" },
    { key: "cost", label: "Cost" },
  ];

  return (
    <Shell
      title="Holdings"
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
        <MetricCard
          label="Positions"
          value={formatNumber(snapshot.positions_rows, user.locale)}
          hint={`${formatNumber(snapshot.raw_positions_rows ?? snapshot.positions_rows, user.locale)} raw Futu rows`}
        />
        <MetricCard label="Total Assets" value={formatDisplayValue(summary.total_assets, { locale: user.locale, key: "total_assets" })} hint={formatDisplayValue(summary.currency, { locale: user.locale, key: "currency" })} />
        <MetricCard label="Cash" value={formatDisplayValue(summary.cash, { locale: user.locale, key: "cash" })} hint={formatDisplayValue(summary.buying_power ?? summary.power, { locale: user.locale, key: "buying_power" })} />
        <MetricCard label="Market Value" value={formatDisplayValue(marketValue, { locale: user.locale, key: "market_value" })} hint="Live holdings value" />
        <MetricCard label="Unrealized PnL" value={formatDisplayValue(unrealizedPnl, { locale: user.locale, key: "unrealized_pnl" })} hint={formatDisplayValue(summary.total_pnl, { locale: user.locale, key: "total_pnl" })} />
      </section>

      <Panel title="Current Positions" aside={<span className="pill">{formatNumber(positionRows.length, user.locale)} rows</span>}>
        <DataTable rows={positionRows} columns={positionColumns} emptyLabel="No Futu positions." locale={user.locale} pageSize={50} />
      </Panel>
    </Shell>
  );
}
