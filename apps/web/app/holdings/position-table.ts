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

export function normalizeSymbol(value: unknown): string {
  const text = String(value ?? "").trim().toUpperCase();
  if (!text) {
    return "";
  }
  if (text.includes(".")) {
    return text.split(".", 2)[1] ?? text;
  }
  return /^\d+$/.test(text) ? text.padStart(6, "0") : text;
}

export function displaySymbol(symbol: unknown, exchange: unknown) {
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

export function paperStockUrl(symbol: unknown) {
  const code = normalizeSymbol(symbol);
  return code ? `/paper/stocks/${encodeURIComponent(code)}` : "";
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

export function positionDisplayRow(row: DashboardRow) {
  const symbol = row.symbol ?? row.code;
  const englishName = row.english_name ?? row.stock_name ?? row.security_name ?? null;
  const chineseName = row.name ?? null;
  const code = row.display_symbol ?? displaySymbol(symbol, row.exchange ?? row.market);
  const detail = [truncateText(englishName), truncateText(chineseName, 18)].filter(Boolean).join(" / ");
  const currentPnl = asNumber(row.unrealized_pnl ?? row.pl_val);
  const currentPnlPercent = pnlPercent(row, currentPnl);
  const todayPnl = asNumber(row.today_pnl);
  const todayPnlPct = asNumber(row.today_pnl_pct);
  return {
    code_name: code,
    code_name_detail: detail,
    code_name_href: paperStockUrl(symbol),
    market_value: row.market_value ?? null,
    quantity: row.quantity ?? row.qty ?? null,
    last_price: row.last_price ?? row.price ?? row.current_price ?? row.last_trade_price ?? null,
    avg_cost: row.avg_cost ?? row.average_cost ?? null,
    diluted_cost: row.diluted_cost ?? row.cost_price ?? null,
    current_pnl: formatSignedNumber(currentPnl),
    current_pnl_detail: formatSignedPercent(currentPnlPercent),
    current_pnl_tone: pnlTone(currentPnl),
    today_pnl: formatSignedNumber(todayPnl),
    today_pnl_detail: formatSignedPercent(todayPnlPct),
    today_pnl_tone: pnlTone(todayPnl),
  };
}

export const positionColumns = [
  { key: "code_name", label: "Code / Name" },
  { key: "market_value", label: "Market Value" },
  { key: "quantity", label: "Quantity" },
  { key: "last_price", label: "Last Price" },
  { key: "avg_cost", label: "Avg Cost" },
  { key: "diluted_cost", label: "Diluted Cost" },
  { key: "current_pnl", label: "Current Unrealized P/L" },
  { key: "today_pnl", label: "Today P/L" },
];
