import { Shell } from "@/components/shell";
import { DataTable } from "@/components/table";
import { Panel } from "@/components/cards";
import { getPaperDbDailyHistory, getPaperHoldings, getPaperTargets, getPortfolioOverview, type OverviewTopPick } from "@/lib/api";
import { requireAuth } from "@/lib/auth";
import { formatDate, formatDateTime, formatDisplayValue, formatNumber } from "@/lib/format";
import type { PanelLocale } from "@/lib/i18n";
import { positionColumns, positionDisplayRow } from "@/app/holdings/position-table";

export const dynamic = "force-dynamic";

function displayName(username: string) {
  return username
    .split(/[._\s-]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ") || "Portfolio Manager";
}

function toneFromNumber(value: unknown) {
  if (typeof value !== "number" || Number.isNaN(value) || value === 0) {
    return "neutral";
  }
  return value > 0 ? "positive" : "negative";
}

function formatPercent(value: unknown, locale: PanelLocale) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "—";
  }
  return `${formatNumber(value * 100, locale, { maximumFractionDigits: 0 })}%`;
}

function scoreWidth(value: unknown) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return 0;
  }
  const percent = Math.abs(value) <= 1 ? value * 100 : value;
  return Math.max(0, Math.min(100, percent));
}

function formatScore(value: unknown, locale: PanelLocale) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "—";
  }
  const percent = Math.abs(value) <= 1 ? value * 100 : value;
  return `${formatNumber(percent, locale, { maximumFractionDigits: 1 })}%`;
}

function formatWeight(value: unknown, locale: PanelLocale) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "—";
  }
  return `${formatNumber(value * 100, locale, { maximumFractionDigits: 2 })}%`;
}

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
    maximumFractionDigits: 0,
    minimumFractionDigits: 0
  }).format(Math.abs(Math.round(value)));
  return `${value > 0 ? "+" : value < 0 ? "-" : ""}${formatted}`;
}

function formatIntegerDisplay(value: unknown, locale: PanelLocale) {
  const numericValue = asNumber(value);
  if (numericValue === null) {
    return formatDisplayValue(value, { locale });
  }
  return formatNumber(Math.round(numericValue), locale, { maximumFractionDigits: 0 });
}

function dateKey(value: unknown) {
  const text = String(value ?? "");
  return /^\d{4}-\d{2}-\d{2}/.test(text) ? text.slice(0, 10) : "";
}

function monthTitle(monthDate: Date, locale: string) {
  return new Intl.DateTimeFormat(locale === "zh" ? "zh-CN" : "en-US", {
    year: "numeric",
    month: "long",
    timeZone: "UTC"
  }).format(monthDate);
}

function parseMonthParam(value: string | undefined) {
  const match = /^(\d{4})-(\d{2})$/.exec(String(value ?? "").trim());
  if (!match) {
    return null;
  }
  const year = Number(match[1]);
  const monthIndex = Number(match[2]) - 1;
  if (!Number.isInteger(year) || monthIndex < 0 || monthIndex > 11) {
    return null;
  }
  return new Date(Date.UTC(year, monthIndex, 1));
}

function addMonths(monthDate: Date, offset: number) {
  return new Date(Date.UTC(monthDate.getUTCFullYear(), monthDate.getUTCMonth() + offset, 1));
}

function monthKey(monthDate: Date) {
  return monthDate.toISOString().slice(0, 7);
}

function monthDateRange(monthDate: Date) {
  const startDate = new Date(Date.UTC(monthDate.getUTCFullYear(), monthDate.getUTCMonth(), 1));
  const endDate = new Date(Date.UTC(monthDate.getUTCFullYear(), monthDate.getUTCMonth() + 1, 0));
  return {
    startDate: startDate.toISOString().slice(0, 10),
    endDate: endDate.toISOString().slice(0, 10)
  };
}

function calendarCells(dailyRows: DashboardRow[], selectedMonthDate?: Date | null) {
  const pnlByDate = new Map<string, DashboardRow>();
  for (const row of dailyRows) {
    const key = dateKey(row.trade_date);
    if (key) {
      pnlByDate.set(key, row);
    }
  }
  const latestDateKey = Array.from(pnlByDate.keys()).sort().at(-1);
  const base = selectedMonthDate ?? (latestDateKey ? new Date(`${latestDateKey}T00:00:00Z`) : new Date());
  const monthStart = new Date(Date.UTC(base.getUTCFullYear(), base.getUTCMonth(), 1));
  const monthEnd = new Date(Date.UTC(base.getUTCFullYear(), base.getUTCMonth() + 1, 0));
  const cells: Array<{
    key: string;
    day: number;
    inMonth: boolean;
    pnl: number | null;
    trades: number;
  }> = [];
  let firstBusinessDay: Date | null = null;
  for (let day = 1; day <= monthEnd.getUTCDate(); day += 1) {
    const date = new Date(Date.UTC(base.getUTCFullYear(), base.getUTCMonth(), day));
    const weekday = date.getUTCDay();
    if (weekday !== 0 && weekday !== 6) {
      firstBusinessDay = date;
      break;
    }
  }
  const leadingDays = firstBusinessDay ? firstBusinessDay.getUTCDay() - 1 : 0;
  for (let index = 0; index < leadingDays; index += 1) {
    cells.push({ key: `leading-${index}`, day: 0, inMonth: false, pnl: null, trades: 0 });
  }
  for (let day = 1; day <= monthEnd.getUTCDate(); day += 1) {
    const date = new Date(Date.UTC(base.getUTCFullYear(), base.getUTCMonth(), day));
    const weekday = date.getUTCDay();
    if (weekday === 0 || weekday === 6) {
      continue;
    }
    const key = date.toISOString().slice(0, 10);
    const row = pnlByDate.get(key);
    cells.push({
      key,
      day,
      inMonth: true,
      pnl: asNumber(row?.realized_pnl),
      trades: asNumber(row?.fills_rows) ?? 0
    });
  }
  while (cells.length % 5 !== 0) {
    cells.push({ key: `trailing-${cells.length}`, day: 0, inMonth: false, pnl: null, trades: 0 });
  }
  return {
    monthDate: monthStart,
    cells
  };
}

function PnlCalendar({
  dailyRows,
  monthDate,
  locale
}: {
  dailyRows: DashboardRow[];
  monthDate?: Date | null;
  locale: PanelLocale;
}) {
  const pnlCalendar = calendarCells(dailyRows, monthDate);
  const previousMonth = addMonths(pnlCalendar.monthDate, -1);
  const nextMonth = addMonths(pnlCalendar.monthDate, 1);
  const weekdayLabels = ["Mon", "Tue", "Wed", "Thu", "Fri"];

  return (
    <section className="panel overview-calendar-panel" aria-label="P/L Calendar">
      <div className="overview-calendar-toolbar">
        <a className="calendar-nav-button" href={`/overview?month=${monthKey(previousMonth)}`} aria-label={`Previous month, ${monthTitle(previousMonth, locale)}`}>
          &lt;
        </a>
        <span className="pill">{monthTitle(pnlCalendar.monthDate, locale)}</span>
        <a className="calendar-nav-button" href={`/overview?month=${monthKey(nextMonth)}`} aria-label={`Next month, ${monthTitle(nextMonth, locale)}`}>
          &gt;
        </a>
      </div>
      <div className="pnl-calendar">
        <div className="pnl-calendar-weekdays">
          {weekdayLabels.map((label) => (
            <span key={label}>{label}</span>
          ))}
        </div>
        <div className="pnl-calendar-grid">
          {pnlCalendar.cells.map((cell) => {
            const tone = cell.pnl === null || cell.pnl === 0 ? "neutral" : cell.pnl > 0 ? "positive" : "negative";
            const className = `pnl-calendar-day ${cell.inMonth ? "" : "pnl-calendar-day-muted"} pnl-calendar-day-${tone}`;
            const body = (
              <>
                <span className="pnl-calendar-date">{cell.inMonth ? cell.day : ""}</span>
                {cell.inMonth ? (
                  cell.trades ? (
                    <>
                      <strong>{cell.pnl === null ? "—" : formatSignedNumber(cell.pnl)}</strong>
                      <span>{`${formatNumber(cell.trades, locale)} trades`}</span>
                    </>
                  ) : (
                    <strong className="pnl-calendar-empty">——</strong>
                  )
                ) : null}
              </>
            );
            return cell.inMonth && cell.trades ? (
              <a className={`${className} pnl-calendar-day-link`} href={`/holdings/daily/${encodeURIComponent(cell.key)}`} key={cell.key} rel="noopener noreferrer" target="_blank">
                {body}
              </a>
            ) : (
              <div className={className} key={cell.key}>
                {body}
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}

function KpiCard({
  label,
  value,
  detail,
  tone = "neutral"
}: {
  label: string;
  value: string;
  detail?: string;
  tone?: "positive" | "negative" | "neutral";
}) {
  return (
    <article className={`overview-kpi-card overview-kpi-${tone}`}>
      <p className="overview-kpi-label">{label}</p>
      <strong>{value}</strong>
      {detail ? <span>{detail}</span> : null}
    </article>
  );
}

function signalTone(signalType?: string | null) {
  const normalized = String(signalType ?? "").toUpperCase();
  if (normalized === "BUY") {
    return "signal-buy";
  }
  if (normalized === "SELL") {
    return "signal-short";
  }
  return "";
}

function plannedOrderSide(row: DashboardRow) {
  const action = String(row.action ?? "").trim().toUpperCase();
  const buyQty = asNumber(row.buy_order_qty);
  const sellQty = asNumber(row.sell_order_qty);
  const deltaQty = asNumber(row.delta_qty);
  if (buyQty !== null && buyQty > 0) {
    return "BUY";
  }
  if (sellQty !== null && sellQty > 0) {
    return "SELL";
  }
  if (deltaQty !== null && deltaQty > 0) {
    return "BUY";
  }
  if (deltaQty !== null && deltaQty < 0) {
    return "SELL";
  }
  if (action.includes("BUY")) {
    return "BUY";
  }
  if (action.includes("SELL")) {
    return "SELL";
  }
  return action || "HOLD";
}

function hasPlannedOrder(row: DashboardRow) {
  const side = plannedOrderSide(row);
  if (side === "BUY" || side === "SELL") {
    return true;
  }
  return ["buy_order_qty", "sell_order_qty", "estimated_order_notional", "estimated_order_fee"].some(
    (key) => Math.abs(asNumber(row[key]) ?? 0) > 0
  );
}

function plannedOrderRows(rows: DashboardRow[]) {
  return rows.filter(hasPlannedOrder).map((row) => {
    const side = plannedOrderSide(row);
    return {
      rank: row.rank ?? null,
      code: row.code ?? row.symbol ?? null,
      name: row.name ?? null,
      side,
      order_qty: side === "SELL" ? row.sell_order_qty ?? row.delta_qty : row.buy_order_qty ?? row.delta_qty,
      target_qty: row.target_qty ?? null,
      current_qty: row.current_qty ?? null,
      delta_qty: row.delta_qty ?? null,
      limit_price: side === "SELL" ? row.sell_limit_price ?? row.close : row.buy_limit_price ?? row.close,
      estimated_order_notional: row.estimated_order_notional ?? null,
      estimated_order_fee: row.estimated_order_fee ?? null,
      signal_date: row.signal_date ?? null,
      status: row.sent_status ?? row.action ?? null,
      error: row.sent_error ?? row.reason ?? null
    };
  });
}

const plannedOrderColumns = [
  { key: "rank", label: "Rank" },
  { key: "code", label: "Code" },
  { key: "name", label: "Name" },
  { key: "side", label: "Side" },
  { key: "order_qty", label: "Order Qty" },
  { key: "target_qty", label: "Target Qty" },
  { key: "current_qty", label: "Current Qty" },
  { key: "delta_qty", label: "Delta" },
  { key: "limit_price", label: "Limit Price" },
  { key: "estimated_order_notional", label: "Est. Notional" },
  { key: "estimated_order_fee", label: "Est. Fee" },
  { key: "signal_date", label: "Signal Date" },
  { key: "status", label: "Status" },
  { key: "error", label: "Note" }
];

export default async function OverviewPage({
  searchParams
}: {
  searchParams?: Promise<{ month?: string }>;
}) {
  const user = await requireAuth();
  const params = (await searchParams) ?? {};
  const requestedMonthDate = parseMonthParam(params.month);
  const requestedMonthRange = requestedMonthDate ? monthDateRange(requestedMonthDate) : null;
  const name = displayName(user.username);
  const [overview, dailyHistory, holdingsSnapshot, targets] = await Promise.all([
    getPortfolioOverview(),
    getPaperDbDailyHistory(120, 5000, requestedMonthRange?.startDate, requestedMonthRange?.endDate).catch(() => ({ rows: 0, daily: [] })),
    getPaperHoldings(1000, 300, 5000).catch(() => ({ positions: [], positions_rows: 0, raw_positions_rows: 0 })),
    getPaperTargets(200).catch(() => ({ rows: 0, targets: [] }))
  ]);
  const dailyRows = dailyHistory.daily as DashboardRow[];
  const positionRows = (holdingsSnapshot.positions as DashboardRow[]).map(positionDisplayRow);
  const intendedOrderRows = plannedOrderRows(targets.targets as DashboardRow[]);

  return (
    <Shell
      title={`Good Morning, ${name} - Here is your portfolio summary.`}
      subtitle=""
      locale={user.locale}
      username={user.username}
      role={user.role}
      tone="dark"
    >
      {overview.warnings.length ? (
        <section className="portfolio-warning-list" aria-label="Overview data warnings">
          {overview.warnings.map((warning) => (
            <p key={warning}>{warning}</p>
          ))}
        </section>
      ) : null}

      <section className="overview-summary-layout" aria-label="Portfolio summary">
        <PnlCalendar dailyRows={dailyRows} monthDate={requestedMonthDate} locale={user.locale} />

        <div className="overview-kpi-grid overview-kpi-stack" aria-label="Portfolio key performance indicators">
          <KpiCard
            label="Account Equity"
            value={formatIntegerDisplay(overview.account.total_assets, user.locale)}
            detail={`Updated ${formatDateTime(overview.account.updated_at ?? overview.generated_at, user.locale)}`}
          />
          <KpiCard
            label="Today P&L"
            value={formatIntegerDisplay(overview.account.today_pnl, user.locale)}
            detail={formatPercent(overview.account.today_pnl_pct, user.locale)}
            tone={toneFromNumber(overview.account.today_pnl)}
          />
          <KpiCard
            label="Holdings / Pending Buy / Pending Sell"
            value={`${formatNumber(overview.positions.holding_count, user.locale)} / ${formatNumber(overview.positions.pending_buy_count, user.locale)} / ${formatNumber(overview.positions.pending_sell_count, user.locale)}`}
            detail={`${formatNumber(overview.positions.open_order_count, user.locale)} open orders`}
          />
          <KpiCard
            label="Pending Actions"
            value={formatNumber(overview.signals.pending_actions, user.locale)}
            detail={`Signal date ${formatDate(overview.signals.latest_signal_date, user.locale)}`}
          />
        </div>
      </section>

      {"error" in holdingsSnapshot && holdingsSnapshot.error ? <p className="banner banner-error">Futu data unavailable: {String(holdingsSnapshot.error)}</p> : null}

      <Panel title="Current Positions" aside={<span className="pill">{formatNumber(positionRows.length, user.locale)} rows</span>}>
        <DataTable rows={positionRows} columns={positionColumns} emptyLabel="No Futu positions." locale={user.locale} pageSize={50} />
      </Panel>

      <section className="portfolio-table-card">
        <div className="portfolio-card-header">
          <div>
            <p className="portfolio-section-kicker">Actionable Insights</p>
            <h2>Top AI Picks</h2>
          </div>
          <span className="portfolio-table-aside">Source: {overview.top_picks[0]?.source ?? "—"}</span>
        </div>

        <div className="portfolio-table-wrap">
          <table className="portfolio-picks-table">
            <thead>
              <tr>
                <th>Ticker/Symbol</th>
                <th>Company Name</th>
                <th>Signal Type</th>
                <th>AI Confidence Score</th>
                <th>Recommended Weight</th>
              </tr>
            </thead>
            <tbody>
              {overview.top_picks.map((pick: OverviewTopPick, index) => (
                <tr key={`${pick.code ?? "row"}-${index}`}>
                  <td><strong>{pick.code ?? "—"}</strong></td>
                  <td>{pick.name ?? "—"}</td>
                  <td>
                    <span className={`signal-badge ${signalTone(pick.signal_type)}`}>
                      {pick.signal_type ?? "—"}
                    </span>
                  </td>
                  <td>
                    <div className="confidence-cell">
                      <div className="confidence-track" aria-hidden="true">
                        <span style={{ width: `${scoreWidth(pick.confidence)}%` }} />
                      </div>
                      <strong>{formatScore(pick.confidence, user.locale)}</strong>
                    </div>
                  </td>
                  <td>{formatWeight(pick.recommended_weight, user.locale)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {overview.top_picks.length ? null : <p className="empty-state portfolio-empty-state">No real AI picks or target rows are available yet.</p>}
        </div>
      </section>

      <Panel title="Planned Orders" aside={<span className="pill">{formatNumber(intendedOrderRows.length, user.locale)} intended</span>}>
        <p className="table-note">
          Intended buy/sell orders from the latest rebalance target file. These are visible before broker submission and still appear outside active trading hours.
        </p>
        <DataTable rows={intendedOrderRows} columns={plannedOrderColumns} emptyLabel="No intended buy/sell orders." locale={user.locale} pageSize={50} />
      </Panel>
    </Shell>
  );
}
