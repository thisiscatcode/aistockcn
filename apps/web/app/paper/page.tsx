import { AutoRefresh } from "@/components/auto-refresh";
import { MetricCard, Panel } from "@/components/cards";
import { Shell } from "@/components/shell";
import { DataTable } from "@/components/table";
import {
  type PaperPerformanceRow,
  getPaperHistory,
  getPaperOrders,
  getPaperOverview,
  getPaperPerformance,
  getPaperPositions,
  getPaperStatus,
  getPaperTargets,
} from "@/lib/api";
import { requireAuth } from "@/lib/auth";
import { formatDate, formatDateTime, formatDisplayValue, formatNumber } from "@/lib/format";
import { getMessages, type PanelLocale } from "@/lib/i18n";

export const dynamic = "force-dynamic";

type DashboardRow = Record<string, unknown>;

type SummaryItem = {
  label: string;
  value: unknown;
  valueKey?: string;
  hint?: string;
};

function asRecord(value: unknown): DashboardRow {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as DashboardRow) : {};
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function asNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string") {
    const normalized = Number(value.trim());
    return Number.isFinite(normalized) ? normalized : null;
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

function compactStrings(value: unknown): string[] {
  return asArray(value)
    .map((item) => String(item ?? "").trim())
    .filter((item) => item.length > 0);
}

function summarizeCounts(rows: DashboardRow[], key: string) {
  const counts = new Map<string, number>();
  for (const row of rows) {
    const label = String(row[key] ?? "").trim();
    if (!label) {
      continue;
    }
    counts.set(label, (counts.get(label) ?? 0) + 1);
  }
  return Array.from(counts.entries())
    .sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]))
    .map(([label, count]) => ({ label, count }));
}

function cleanBrokerMessage(value: unknown): string | null {
  const text = String(value ?? "").trim();
  if (!text) {
    return null;
  }
  if (text.includes("涨跌停") || text.toLowerCase().includes("price outside")) {
    return "Price outside CN daily limit band";
  }
  if (/HTTP\s+\d{3}/i.test(text) || text.toLowerCase().includes("gateway")) {
    return "Broker gateway rejected the order";
  }
  return text;
}

function paperLiveFallback(status: Awaited<ReturnType<typeof getPaperStatus>>, error: unknown) {
  return {
    ...status,
    live_summary: null,
    live_balance: [],
    live_positions_count: 0,
    live_orders_count: 0,
    balance_rows: 0,
    live_error: error instanceof Error ? error.message : "Live broker snapshot unavailable",
  };
}

function SummaryList({ items, locale }: { items: SummaryItem[]; locale: PanelLocale }) {
  return (
    <div className="summary-list">
      {items.map((item) => (
        <div className="summary-item" key={item.label}>
          <span className="summary-label">{item.label}</span>
          <strong className="summary-value">
            {formatDisplayValue(item.value, { locale, key: item.valueKey ?? item.label.toLowerCase().replace(/\s+/g, "_") })}
          </strong>
          {item.hint ? <span className="summary-hint">{item.hint}</span> : null}
        </div>
      ))}
    </div>
  );
}

function Sparkline({
  rows,
  valueKey,
  label,
  locale,
}: {
  rows: PaperPerformanceRow[];
  valueKey: keyof PaperPerformanceRow;
  label: string;
  locale: PanelLocale;
}) {
  const points = rows
    .map((row, index) => ({ index, row, value: asNumber(row[valueKey]) }))
    .filter((entry): entry is { index: number; row: PaperPerformanceRow; value: number } => entry.value !== null);

  if (!points.length) {
    return (
      <div className="sparkline-card">
        <p className="sparkline-label">{label}</p>
        <p className="empty-state">No synced history yet.</p>
      </div>
    );
  }

  const values = points.map((entry) => entry.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const latest = points[points.length - 1];
  const first = points[0];
  const polyline = points
    .map((entry, index) => {
      const x = points.length === 1 ? 50 : (index / (points.length - 1)) * 100;
      const y = max === min ? 50 : 100 - ((entry.value - min) / (max - min)) * 100;
      return `${x},${y}`;
    })
    .join(" ");
  const latestX = points.length === 1 ? 50 : 100;
  const latestY = max === min ? 50 : 100 - ((latest.value - min) / (max - min)) * 100;
  const lineColor = latest.value < 0 ? "var(--danger)" : "var(--accent)";
  const startAt = first.row.recorded_at;
  const endAt = latest.row.recorded_at;

  return (
    <div className="sparkline-card">
      <p className="sparkline-label">{label}</p>
      <p className="sparkline-value">{formatDisplayValue(latest.value, { locale, key: String(valueKey) })}</p>
      <svg className="sparkline-svg" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
        <polyline
          fill="none"
          points={polyline}
          stroke={lineColor}
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth="3"
        />
        <circle cx={latestX} cy={latestY} fill={lineColor} r="3.5" />
      </svg>
      <p className="sparkline-caption">
        {formatDateTime(startAt, locale)} to {formatDateTime(endAt, locale)}
      </p>
    </div>
  );
}

function renderControlButtons({
  target,
  isAdmin,
  canStart,
  canStop,
  startLabel,
  stopLabel,
}: {
  target: string;
  isAdmin: boolean;
  canStart: boolean;
  canStop: boolean;
  startLabel: string;
  stopLabel: string;
}) {
  if (!isAdmin) {
    return null;
  }

  return (
    <div className="action-row">
      {canStart ? (
        <form action="/batch/control" method="post">
          <input type="hidden" name="target" value={target} />
          <input type="hidden" name="action" value="start" />
          <button className="auth-submit action-button" type="submit">
            {startLabel}
          </button>
        </form>
      ) : null}
      {canStop ? (
        <form action="/batch/control" method="post">
          <input type="hidden" name="target" value={target} />
          <input type="hidden" name="action" value="stop" />
          <button className="action-button danger-button" type="submit">
            {stopLabel}
          </button>
        </form>
      ) : null}
    </div>
  );
}

function flashMessage(_isZh: boolean, params: { notice?: string; error?: string; target?: string }) {
  const code = params.notice ?? params.error;
  if (!code) {
    return null;
  }

  const targetLabel = "Auto Paper Trading";
  const success = {
    started: `Start request sent for ${targetLabel}.`,
    stopped: `Stop request sent for ${targetLabel}.`,
  } as const;
  const errors: Record<string, string> = {
    forbidden: "This account does not have permission to control the service.",
    already_running: `${targetLabel} is already running.`,
    not_running: `${targetLabel} is not currently running.`,
    not_found: `No run record was found for ${targetLabel}.`,
    control_unavailable: "Workflow control is not configured correctly yet.",
    invalid_action: "That control action is not valid.",
    control_failed: "Control request failed. Check the API logs.",
    docker_unavailable: "The API container cannot reach Docker right now.",
    image_missing: "A required Docker image is missing.",
    start_failed: `${targetLabel} failed to start.`,
    stop_failed: `${targetLabel} failed to stop.`,
  };

  if (params.notice && code in success) {
    return { tone: "success", text: success[code as keyof typeof success] };
  }
  if (code in errors) {
    return { tone: "error", text: errors[code] };
  }
  return { tone: "error", text: errors.control_failed };
}

export default async function PaperPage({
  searchParams,
}: {
  searchParams?: Promise<{ notice?: string; error?: string; target?: string }>;
}) {
  const user = await requireAuth();
  const copy = getMessages(user.locale);
  const paperLiveTimeoutMs = 3200;
  const [status, overviewResult, targets, positions, orders, history, performance] = await Promise.all([
    getPaperStatus(),
    getPaperOverview(paperLiveTimeoutMs).catch((error) => ({ error })),
    getPaperTargets(60),
    getPaperPositions(120, paperLiveTimeoutMs).catch((error) => ({
      rows: 0,
      positions: [],
      error: error instanceof Error ? error.message : "Live positions unavailable",
    })),
    getPaperOrders(120, paperLiveTimeoutMs).catch((error) => ({
      rows: 0,
      orders: [],
      error: error instanceof Error ? error.message : "Live order feed unavailable",
    })),
    getPaperHistory(120),
    getPaperPerformance(240),
  ]);
  const overview = "error" in overviewResult ? paperLiveFallback(status, overviewResult.error) : overviewResult;
  const isAdmin = user.role === "admin";
  const params = (await searchParams) ?? {};
  const flash = flashMessage(false, params);
  const daemon = overview.daemon;
  const gateway = overview.gateway;
  const liveSummary = asRecord(overview.live_summary);
  const state = asRecord(overview.state);
  const balanceMetrics = asRecord(state.balance_metrics);
  const planSummary = asRecord(state.plan_summary);
  const priceLimitErrorLabel = "price outside CN daily limit band";
  const recentOrders = orders.orders as DashboardRow[];
  const livePositions = positions.positions as DashboardRow[];
  const rawHistory = history.history as DashboardRow[];
  const performanceRows = performance.snapshots;
  const portfolioMarketValue =
    asNumber(liveSummary.market_value) ??
    livePositions.reduce((total, row) => total + (asNumber(row.market_value) ?? 0), 0);

  const ordersBySymbol = new Map<string, DashboardRow>();
  for (const order of recentOrders) {
    const symbol = normalizeSymbol(order.symbol ?? order.code);
    if (symbol && !ordersBySymbol.has(symbol)) {
      ordersBySymbol.set(symbol, order);
    }
  }

  const enrichedTargets: DashboardRow[] = (targets.targets as DashboardRow[]).map((row) => {
    const symbol = normalizeSymbol(row.code);
    const liveOrder = ordersBySymbol.get(symbol);
    return {
      ...row,
      sent_order_id: row.sent_order_id ?? liveOrder?.broker_order_id ?? null,
      sent_status:
        row.sent_status ??
        liveOrder?.order_status ??
        (String(row.action ?? "").startsWith("SKIP_") ? row.action : null),
      sent_price: row.sent_price ?? liveOrder?.price ?? null,
      dealt_qty: liveOrder?.dealt_qty ?? null,
      dealt_avg_price: liveOrder?.dealt_avg_price ?? null,
      order_updated_at: liveOrder?.updated_at ?? null,
      order_remark: liveOrder?.remark ?? null,
      order_type: liveOrder?.order_type ?? null,
      sent_error:
        cleanBrokerMessage(row.sent_error) ?? (String(row.action ?? "") === "SKIP_PRICE_LIMIT" ? priceLimitErrorLabel : null),
    };
  });

  const targetBySymbol = new Map<string, DashboardRow>();
  for (const target of enrichedTargets) {
    const symbol = normalizeSymbol(target.code);
    if (symbol) {
      targetBySymbol.set(symbol, target);
    }
  }

  const positionBySymbol = new Map<string, DashboardRow>();
  for (const position of livePositions) {
    const symbol = normalizeSymbol(position.symbol ?? position.code);
    if (symbol) {
      positionBySymbol.set(symbol, position);
    }
  }

  const allSymbols = new Set<string>([...targetBySymbol.keys(), ...positionBySymbol.keys()]);
  const holdingsRows = Array.from(allSymbols)
    .map((symbol) => {
      const target = targetBySymbol.get(symbol) ?? {};
      const position = positionBySymbol.get(symbol) ?? {};
      const marketValue = asNumber(position.market_value) ?? asNumber(target.current_market_value);
      const targetWeight = asNumber(target.target_weight);
      const actualWeight = portfolioMarketValue > 0 && marketValue !== null ? (marketValue / portfolioMarketValue) * 100 : null;
      return {
        rank: target.rank ?? null,
        code: symbol,
        name: target.name ?? position.name ?? null,
        industry: target.industry ?? null,
        score: target.score ?? null,
        action: target.action ?? (asNumber(position.quantity) ? "HOLD" : null),
        target_qty: target.target_qty ?? 0,
        current_qty: position.quantity ?? target.current_qty ?? 0,
        delta_qty: target.delta_qty ?? null,
        buy_order_qty: target.buy_order_qty ?? null,
        sell_order_qty: target.sell_order_qty ?? null,
        target_weight_pct: targetWeight !== null ? targetWeight * 100 : null,
        actual_weight_pct: actualWeight,
        avg_cost: position.avg_cost ?? target.current_avg_cost ?? null,
        last_price: position.last_price ?? target.current_last_price ?? target.close ?? null,
        market_value: marketValue,
        realized_pnl: position.realized_pnl ?? null,
        unrealized_pnl: position.unrealized_pnl ?? null,
        sent_status: target.sent_status ?? null,
        sent_order_id: target.sent_order_id ?? null,
        sent_error: target.sent_error ?? null,
        order_updated_at: target.order_updated_at ?? null,
      };
    })
    .sort((left, right) => {
      const marketValueDelta = (asNumber(right.market_value) ?? 0) - (asNumber(left.market_value) ?? 0);
      if (marketValueDelta !== 0) {
        return marketValueDelta;
      }
      return (asNumber(left.rank) ?? 999) - (asNumber(right.rank) ?? 999);
    });

  const historyRows = rawHistory.map((row) => {
    const historyBalance = asRecord(row.balance_metrics);
    const historyLiveSummary = asRecord(row.live_summary);
    const historyPlan = asRecord(row.plan_summary);
    return {
      recorded_at: row.recorded_at ?? null,
      status: row.status ?? null,
      score_signal_date: row.score_signal_date ?? null,
      total_assets: historyBalance.total_assets ?? null,
      cash: historyBalance.cash ?? null,
      market_value: historyLiveSummary.market_value ?? historyPlan.current_market_value ?? null,
      total_pnl: historyLiveSummary.total_pnl ?? null,
      active_order_count: row.active_order_count ?? null,
      position_count: row.position_count ?? null,
      buy_order_count: historyPlan.buy_order_count ?? null,
      sell_order_count: historyPlan.sell_order_count ?? null,
      placed_order_ids: row.placed_order_ids ?? [],
      cancelled_order_ids: row.cancelled_order_ids ?? [],
      skipped_symbols: row.skipped_symbols ?? [],
      message: row.message ?? null,
    };
  });

  const orderStatusCounts = summarizeCounts(recentOrders, "order_status");
  const orderSideCounts = summarizeCounts(recentOrders, "side");

  const targetSymbols = compactStrings(planSummary.target_symbols);
  const accountSummaryItems: SummaryItem[] = [
    { label: "Total Assets", value: balanceMetrics.total_assets, valueKey: "total_assets" },
    { label: "Cash", value: balanceMetrics.cash, valueKey: "cash" },
    { label: "Buying Power", value: balanceMetrics.power, valueKey: "power" },
    { label: "Market Value", value: liveSummary.market_value, valueKey: "market_value" },
    { label: "Total PnL", value: liveSummary.total_pnl, valueKey: "total_pnl" },
    { label: "Realized PnL", value: liveSummary.realized_pnl, valueKey: "realized_pnl" },
    { label: "Unrealized PnL", value: liveSummary.unrealized_pnl, valueKey: "unrealized_pnl" },
    {
      label: "Total Fills",
      value: liveSummary.total_fills,
      valueKey: "total_fills",
      hint: `Currency ${String(balanceMetrics.currency ?? gateway.market ?? "—")}`,
    },
  ];
  const planSummaryItems: SummaryItem[] = [
    { label: "Target Count", value: planSummary.target_count, valueKey: "target_count" },
    {
      label: "Target Symbols",
      value: targetSymbols,
      valueKey: "target_symbols",
      hint: targetSymbols.length ? "Latest intended holdings from the rebalance plan." : "No current target list was saved.",
    },
    { label: "Investable Capital", value: planSummary.investable_capital, valueKey: "investable_capital" },
    { label: "Buy Capacity", value: planSummary.buy_capacity, valueKey: "buy_capacity" },
    { label: "Planned Sale Notional", value: planSummary.planned_sale_notional, valueKey: "planned_sale_notional" },
    { label: "Buy Orders", value: planSummary.buy_order_count, valueKey: "buy_order_count" },
    { label: "Sell Orders", value: planSummary.sell_order_count, valueKey: "sell_order_count" },
    { label: "Skipped Symbols", value: planSummary.skip_count, valueKey: "skip_count" },
  ];

  const holdingsColumns = [
    { key: "rank", label: "Rank" },
    { key: "code", label: "Code" },
    { key: "name", label: "Name" },
    { key: "score", label: "Score" },
    { key: "action", label: "Action" },
    { key: "target_qty", label: "Target Qty" },
    { key: "current_qty", label: "Current Qty" },
    { key: "delta_qty", label: "Delta Qty" },
    { key: "buy_order_qty", label: "Planned Buy Qty" },
    { key: "sell_order_qty", label: "Planned Sell Qty" },
    { key: "target_weight_pct", label: "Target Wt %" },
    { key: "actual_weight_pct", label: "Actual Wt %" },
    { key: "avg_cost", label: "Avg Cost" },
    { key: "last_price", label: "Last Price" },
    { key: "market_value", label: "Market Value" },
    { key: "unrealized_pnl", label: "Unrealized PnL" },
    { key: "sent_status", label: "Order Status" },
    { key: "sent_order_id", label: "Order ID" },
    { key: "sent_error", label: "Error" },
  ];
  const orderColumns = [
    { key: "broker_order_id", label: "Order ID" },
    { key: "market", label: "Market" },
    { key: "symbol", label: "Symbol" },
    { key: "side", label: "Side" },
    { key: "order_type", label: "Type" },
    { key: "order_status", label: "Status" },
    { key: "quantity", label: "Qty" },
    { key: "price", label: "Price" },
    { key: "dealt_qty", label: "Dealt Qty" },
    { key: "dealt_avg_price", label: "Dealt Avg Price" },
    { key: "created_at", label: "Created At" },
    { key: "updated_at", label: "Updated At" },
    { key: "remark", label: "Remark" },
  ];
  const historyColumns = [
    { key: "recorded_at", label: "Recorded At" },
    { key: "status", label: "Status" },
    { key: "score_signal_date", label: "Signal Date" },
    { key: "total_assets", label: "Total Assets" },
    { key: "market_value", label: "Market Value" },
    { key: "total_pnl", label: "Total PnL" },
    { key: "active_order_count", label: "Active Orders" },
    { key: "buy_order_count", label: "Buy Orders" },
    { key: "sell_order_count", label: "Sell Orders" },
    { key: "placed_order_ids", label: "Placed Order IDs" },
    { key: "cancelled_order_ids", label: "Cancelled Order IDs" },
    { key: "skipped_symbols", label: "Skipped Symbols" },
    { key: "message", label: "Message" },
  ];

  const latestStateUpdatedAt = formatDateTime(state.updated_at, user.locale);
  const totalPnlHint = `Realized ${formatDisplayValue(liveSummary.realized_pnl, { locale: user.locale, key: "realized_pnl" })} / Unrealized ${formatDisplayValue(liveSummary.unrealized_pnl, { locale: user.locale, key: "unrealized_pnl" })}`;
  const latestMessage = String(state.last_message ?? "—");

  return (
    <Shell
      title={copy.paper.title}
      subtitle={copy.paper.subtitle}
      locale={user.locale}
      username={user.username}
      role={user.role}
    >
      <AutoRefresh intervalSeconds={15} />
      {flash ? <p className={`banner banner-${flash.tone}`}>{flash.text}</p> : null}
      {!gateway.healthy ? <p className="banner banner-error">{copy.paper.gatewayOffline}</p> : null}
      {overview.live_error ? (
        <p className="banner banner-info">Showing the latest saved paper-trading state while the live broker snapshot refreshes.</p>
      ) : null}

      <section className="metrics-grid">
        <MetricCard label={copy.paper.daemon} value={daemon.status_label} hint={daemon.container_name ?? "—"} />
        <MetricCard label={copy.paper.gateway} value={gateway.healthy ? copy.common.live : copy.common.checkNeeded} hint={gateway.base_url} />
        <MetricCard
          label="Account Equity"
          value={formatDisplayValue(balanceMetrics.total_assets, { locale: user.locale, key: "total_assets" })}
          hint={`Balance snapshot ${latestStateUpdatedAt}`}
        />
        <MetricCard
          label="Cash"
          value={formatDisplayValue(balanceMetrics.cash, { locale: user.locale, key: "cash" })}
          hint={String(balanceMetrics.currency ?? gateway.market ?? "—")}
        />
        <MetricCard
          label="Market Value"
          value={formatDisplayValue(liveSummary.market_value, { locale: user.locale, key: "market_value" })}
          hint={formatDisplayValue(planSummary.current_market_value, { locale: user.locale, key: "current_market_value" })}
        />
        <MetricCard label={copy.paper.totalPnl} value={formatDisplayValue(liveSummary.total_pnl, { locale: user.locale, key: "total_pnl" })} hint={totalPnlHint} />
        <MetricCard
          label="Unrealized PnL"
          value={formatDisplayValue(liveSummary.unrealized_pnl, { locale: user.locale, key: "unrealized_pnl" })}
          hint={formatDisplayValue(liveSummary.realized_pnl, { locale: user.locale, key: "realized_pnl" })}
        />
        <MetricCard
          label="Total Fills"
          value={formatDisplayValue(liveSummary.total_fills, { locale: user.locale, key: "total_fills" })}
          hint={formatDisplayValue(liveSummary.total_orders, { locale: user.locale, key: "total_orders" })}
        />
        <MetricCard
          label={copy.paper.openPositions}
          value={formatNumber(overview.live_positions_count, user.locale)}
          hint={formatDisplayValue(liveSummary.open_positions, { locale: user.locale, key: "open_positions" })}
        />
        <MetricCard
          label={copy.paper.openOrders}
          value={formatNumber(overview.live_orders_count, user.locale)}
          hint={formatDisplayValue(state.active_order_count, { locale: user.locale, key: "active_order_count" })}
        />
        <MetricCard
          label={copy.paper.latestSignal}
          value={formatDate(state.score_signal_date, user.locale)}
          hint={formatDate(overview.targets.latest_signal_date, user.locale)}
        />
        <MetricCard
          label={copy.paper.lastSync}
          value={String(state.last_status ?? "—")}
          hint={formatDateTime(state.last_success_at ?? state.last_attempt_at, user.locale)}
        />
      </section>

      <section className="two-col-grid">
        <Panel title={copy.paper.controls} aside={<span className={`pill ${daemon.is_running ? "live" : "warn"}`}>{daemon.status_label}</span>}>
          <div className="stack">
            <p className="panel-copy">{copy.paper.controlHint}</p>
            <div className="status-meta">
              <span>{copy.common.lastStateUpdate}: {latestStateUpdatedAt}</span>
              <span>{copy.paper.latestSignal}: {formatDate(state.score_signal_date, user.locale)}</span>
              <span>{copy.paper.gateway}: {gateway.healthy ? copy.common.live : copy.common.checkNeeded}</span>
              <span>Agent: {gateway.agent_id}</span>
              <span>Message: {latestMessage}</span>
            </div>
            {renderControlButtons({
              target: "paper",
              isAdmin,
              canStart: daemon.can_start,
              canStop: daemon.can_stop,
              startLabel: copy.paper.startAction,
              stopLabel: copy.paper.stopAction,
            })}
          </div>
        </Panel>

        <Panel title="PnL Trend" aside={<span className="pill">{formatNumber(performance.rows, user.locale)} snapshots</span>}>
          <p className="panel-copy">Equity and PnL are plotted from the locally saved paper-trading sync history.</p>
          <div className="sparkline-grid">
            <Sparkline rows={performanceRows} valueKey="total_assets" label="Total Assets" locale={user.locale} />
            <Sparkline rows={performanceRows} valueKey="total_pnl" label="Total PnL" locale={user.locale} />
          </div>
        </Panel>
      </section>

      <section className="two-col-grid">
        <Panel title="Account Snapshot" aside={<span className="pill">{formatDisplayValue(balanceMetrics.currency, { locale: user.locale, key: "currency" })}</span>}>
          <p className="panel-copy">Latest balance and live account summary pulled from the gateway-aware paper state.</p>
          <SummaryList items={accountSummaryItems} locale={user.locale} />
        </Panel>

        <Panel title="Portfolio Intent" aside={<span className="pill">{formatNumber(targetSymbols.length, user.locale)} symbols</span>}>
          <p className="panel-copy">What the rebalance planner wants to hold and how much capital it expects to deploy.</p>
          <SummaryList items={planSummaryItems} locale={user.locale} />
        </Panel>
      </section>

      <Panel title="Holdings vs Targets" aside={<span className="pill">{formatNumber(holdingsRows.length, user.locale)} rows</span>}>
        <p className="table-note">
          Merge live positions, target quantities, current market value, and the latest order state into one table so you can compare what the strategy wants against what the paper account currently holds.
        </p>
        <DataTable
          rows={holdingsRows}
          columns={holdingsColumns}
          emptyLabel={positions.error ? "Live positions are refreshing." : copy.common.noRows}
          locale={user.locale}
          pageSize={25}
        />
      </Panel>

      <section className="stack">
        <Panel title="Order Activity" aside={<span className="pill">{formatNumber(orders.rows, user.locale)} orders</span>}>
          <div className="stack">
            <div className="inline-pill-row">
              {orderStatusCounts.slice(0, 6).map((item) => (
                <span className="pill" key={`status-${item.label}`}>
                  {item.label}: {formatNumber(item.count, user.locale)}
                </span>
              ))}
              {orderSideCounts.map((item) => (
                <span className="pill" key={`side-${item.label}`}>
                  {item.label}: {formatNumber(item.count, user.locale)}
                </span>
              ))}
            </div>
            <DataTable
              rows={recentOrders}
              columns={orderColumns}
              emptyLabel={orders.error ? "Live order feed is refreshing." : copy.common.noRows}
              locale={user.locale}
              pageSize={25}
            />
          </div>
        </Panel>

        <Panel title="Recent Rebalances" aside={<span className="pill">{formatNumber(history.rows, user.locale)} snapshots</span>}>
          <p className="table-note">
            Every daemon sync now records a ledger entry with status, account values, placed or cancelled order IDs, and skipped symbols.
          </p>
          <DataTable rows={historyRows} columns={historyColumns} emptyLabel={copy.common.noRows} locale={user.locale} pageSize={25} />
        </Panel>
      </section>

      <Panel title={copy.paper.daemonLog} aside={<span className="pill">{daemon.log_source ?? "—"}</span>}>
        <pre className="log-console">{daemon.log_lines.join("\n") || copy.common.noLogs}</pre>
      </Panel>
    </Shell>
  );
}
