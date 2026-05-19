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

function displaySymbol(symbol: unknown, exchange: unknown) {
  const normalized = normalizeSymbol(symbol);
  const exchangeText = String(exchange ?? "").trim().toUpperCase();
  return normalized && exchangeText ? `${normalized}.${exchangeText}` : normalized;
}

function truncateText(value: unknown, maxLength = 28) {
  const text = String(value ?? "").trim();
  if (!text) {
    return "";
  }
  return text.length > maxLength ? `${text.slice(0, maxLength - 1)}...` : text;
}

function googleStockSearchUrl(symbol: unknown) {
  const code = normalizeSymbol(symbol);
  const query = [code, "stock"].filter(Boolean).join(" ");
  return `https://www.google.com/search?q=${encodeURIComponent(query)}`;
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

function formatSignedPercent(value: number | null) {
  if (value === null) {
    return "—";
  }
  const formatted = new Intl.NumberFormat("en-US", {
    maximumFractionDigits: 2,
    minimumFractionDigits: 2
  }).format(Math.abs(value));
  return `${value > 0 ? "+" : value < 0 ? "-" : ""}${formatted}%`;
}

function pnlPercent(row: DashboardRow, pnl: number | null) {
  const futuRatio = asNumber(row.pl_ratio);
  if (futuRatio !== null) {
    return futuRatio;
  }
  const cost = asNumber(row.avg_cost ?? row.cost_price ?? row.average_cost);
  const quantity = asNumber(row.quantity ?? row.qty);
  if (pnl === null || cost === null || quantity === null || cost * quantity === 0) {
    return null;
  }
  return (pnl / Math.abs(cost * quantity)) * 100;
}

function pnlTone(value: number | null) {
  if (value === null || value === 0) {
    return "neutral";
  }
  return value > 0 ? "positive" : "negative";
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

  const positionRows = positions.map((row) => {
    const symbol = row.symbol ?? row.code;
    const englishName = row.english_name ?? row.stock_name ?? row.security_name ?? null;
    const chineseName = row.name ?? null;
    const code = row.display_symbol ?? displaySymbol(symbol, row.exchange);
    const detail = [truncateText(englishName), truncateText(chineseName, 18)].filter(Boolean).join(" / ");
    const currentPnl = asNumber(row.unrealized_pnl ?? row.pl_val);
    const currentPnlPercent = pnlPercent(row, currentPnl);
    return {
      code_name: code,
      code_name_detail: detail,
      code_name_href: googleStockSearchUrl(symbol),
      market_value: row.market_value ?? null,
      quantity: row.quantity ?? row.qty ?? null,
      last_price: row.last_price ?? row.price ?? row.current_price ?? null,
      cost: row.avg_cost ?? row.cost_price ?? row.average_cost ?? null,
      current_pnl: formatSignedNumber(currentPnl),
      current_pnl_detail: formatSignedPercent(currentPnlPercent),
      current_pnl_tone: pnlTone(currentPnl),
    };
  });

  const positionColumns = [
    { key: "code_name", label: "Code / Name" },
    { key: "market_value", label: "Market Value" },
    { key: "quantity", label: "Quantity" },
    { key: "last_price", label: "Last Price" },
    { key: "cost", label: "Cost" },
    { key: "current_pnl", label: "Current P/L" },
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
        <MetricCard label="Unrealized P/L" value={formatDisplayValue(unrealizedPnl, { locale: user.locale, key: "unrealized_pnl" })} hint="Sum of Futu position pl_val" />
      </section>

      <Panel title="Current Positions" aside={<span className="pill">{formatNumber(positionRows.length, user.locale)} rows</span>}>
        <DataTable rows={positionRows} columns={positionColumns} emptyLabel="No Futu positions." locale={user.locale} pageSize={50} />
      </Panel>
    </Shell>
  );
}
