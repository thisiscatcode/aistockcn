export const API_BASE_URL =
  process.env.API_BASE_URL ??
  process.env.NEXT_PUBLIC_API_BASE_URL ??
  "http://127.0.0.1:8000";

export const RESEARCH_API_BASE_URL =
  process.env.RESEARCH_API_BASE_URL ??
  API_BASE_URL;

export const US_MARKET_API_BASE_URL =
  process.env.US_MARKET_API_BASE_URL ??
  "http://127.0.0.1:8004";

type FetchJsonOptions = {
  timeoutMs?: number;
  baseUrl?: string;
};

async function fetchJson<T>(path: string, options: FetchJsonOptions = {}): Promise<T> {
  const controller = options.timeoutMs ? new AbortController() : null;
  const timeout = controller
    ? setTimeout(() => controller.abort(), options.timeoutMs)
    : null;

  try {
    const response = await fetch(`${options.baseUrl ?? API_BASE_URL}${path}`, {
      cache: "no-store",
      signal: controller?.signal
    });

    if (!response.ok) {
      throw new Error(`API request failed: ${response.status} ${response.statusText}`);
    }

    return (await response.json()) as T;
  } finally {
    if (timeout) {
      clearTimeout(timeout);
    }
  }
}

export type BatchStatus = {
  is_running: boolean;
  is_stale: boolean;
  is_stalled?: boolean;
  container_name?: string | null;
  container_status?: string | null;
  container_running_for?: string | null;
  container_started_at?: string | null;
  container_finished_at?: string | null;
  container_exit_code?: number | null;
  oom_killed?: boolean;
  created_at?: string | null;
  updated_at?: string | null;
  last_activity_at?: string | null;
  activity_age_seconds?: number | null;
  start_date?: string | null;
  end_date?: string | null;
  current_pass_index?: number | null;
  state_file?: string | null;
  last_code?: string | null;
  done_count: number;
  failed_count: number;
  attempted_count: number;
  total_codes?: number | null;
  remaining_count?: number | null;
  progress_pct?: number | null;
  latest_log_file?: string | null;
  latest_log_updated_at?: string | null;
  latest_log_line_count?: number | null;
  can_start?: boolean;
  can_stop?: boolean;
  failure_reasons_top: Array<{ reason: string; count: number }>;
};

export type BatchLogs = {
  source: string;
  lines: string[];
  container_name?: string;
  path?: string;
};

export type ReferenceBatchStatus = {
  status: string;
  status_label: string;
  is_running: boolean;
  can_start: boolean;
  can_stop: boolean;
  container_id?: string | null;
  container_name?: string | null;
  container_status?: string | null;
  container_started_at?: string | null;
  container_finished_at?: string | null;
  container_exit_code?: number | null;
  oom_killed?: boolean;
  state_file?: string | null;
  updated_at?: string | null;
  completed_at?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  last_code?: string | null;
  last_error?: string | null;
  done_count: number;
  failed_count: number;
  total_codes: number;
  progress_pct?: number | null;
  failure_reasons_top: Array<{ reason: string; count: number }>;
  reference_status_file?: string | null;
  reference_status_updated_at?: string | null;
  target_trade_date?: string | null;
  valuation_reference_ready_count: number;
  valuation_reference_missing_count: number;
  valuation_reference_stale_count: number;
  industry_missing_count: number;
  log_file?: string | null;
  log_source?: string | null;
  log_lines: string[];
};

export type AdminSettings = {
  path?: string | null;
  settings: {
    exclude_st_from_model_candidates?: boolean;
    updated_at?: string | null;
  };
};

export type WorkflowRuntimeDetail = {
  label: string;
  value: string;
};

export type WorkflowRuntimeStep = {
  step: number;
  key: string;
  status: string;
  status_label: string;
  is_running: boolean;
  runner_script?: string | null;
  command_hint?: string | null;
  container_name?: string | null;
  container_status?: string | null;
  container_started_at?: string | null;
  container_finished_at?: string | null;
  container_exit_code?: number | null;
  oom_killed?: boolean;
  latest_log_source?: string | null;
  latest_log_file?: string | null;
  latest_log_updated_at?: string | null;
  artifact_path?: string | null;
  artifact_updated_at?: string | null;
  artifact_size_bytes?: number | null;
  details: WorkflowRuntimeDetail[];
  warnings?: string[];
  log_lines: string[];
};

export type WorkflowStatus = {
  generated_at?: string | null;
  steps: WorkflowRuntimeStep[];
};

export type PipelineRunStatus = {
  status: string;
  status_label: string;
  is_running: boolean;
  can_start: boolean;
  can_stop: boolean;
  container_id?: string | null;
  container_name?: string | null;
  container_status?: string | null;
  container_started_at?: string | null;
  container_finished_at?: string | null;
  container_exit_code?: number | null;
  oom_killed?: boolean;
  current_step_key?: string | null;
  current_step_label?: string | null;
  completed_steps: string[];
  failed_step_key?: string | null;
  error_message?: string | null;
  updated_at?: string | null;
  log_file?: string | null;
  log_source?: string | null;
  log_lines: string[];
};

export type DataSummary = {
  stock_count: number;
  active_stock_count: number;
  registry_stock_count: number;
  subset_stock_count: number;
  kline_file_count: number;
  valuation_file_count: number;
  paired_file_count: number;
  total_size_mb: number;
  sample_codes: string[];
  latest_inference_snapshot?: {
    rows: number;
    code_count?: number | null;
    latest_date: string | null;
  } | null;
  reference_snapshot?: {
    path: string;
    updated_at?: string | null;
    target_trade_date?: string | null;
    has_warnings: boolean;
    industry_known_count: number;
    industry_missing_count: number;
    valuation_reference_ready_count: number;
    valuation_reference_missing_count: number;
    valuation_reference_stale_count: number;
    missing_industry_codes: string[];
    missing_reference_codes: string[];
    stale_reference_codes: string[];
    batch_state_path?: string | null;
    batch_updated_at?: string | null;
    batch_last_code?: string | null;
    batch_failed_count?: number | null;
  } | null;
};

export type DatasetSnapshot = {
  path: string;
  rows: number;
  columns: string[];
  column_count: number;
  code_count?: number | null;
  date_min?: string | null;
  date_max?: string | null;
};

export type PipelineSummary = {
  training_features?: DatasetSnapshot | null;
  inference_features?: DatasetSnapshot | null;
  inference_scores?: DatasetSnapshot | null;
};

export type ExplorerDatasetColumn = {
  name: string;
  type: string;
};

export type ExplorerDataset = {
  key: string;
  label: string;
  description: string;
  path: string;
  row_count: number;
  column_count: number;
  size_bytes: number;
  updated_at?: string | null;
  default_columns: string[];
  searchable_columns: string[];
  columns: ExplorerDatasetColumn[];
};

export type ExplorerCatalog = {
  datasets: ExplorerDataset[];
};

export type ExplorerFilter = {
  column: string;
  operator: string;
  value?: string | null;
  value_to?: string | null;
};

export type ExplorerQuery = {
  dataset: ExplorerDataset;
  rows: Array<Record<string, unknown>>;
  page: number;
  page_size: number;
  total_rows: number;
  filtered_rows: number;
  total_pages: number;
  search: string;
  sort_by: string;
  sort_dir: string;
  selected_columns: string[];
  applied_filters: ExplorerFilter[];
  max_export_rows: number;
};

export type StockRow = {
  code: string;
  exchange?: string;
  name?: string;
  industry?: string;
  trade_date?: string;
  universe?: string;
};

export type StockDetail = {
  stock?: Record<string, unknown> | null;
  kline: {
    code: string;
    rows: number;
    columns: string[];
    date_min?: string | null;
    date_max?: string | null;
    head: Array<Record<string, unknown>>;
    tail: Array<Record<string, unknown>>;
  };
  valuation: {
    code: string;
    rows: number;
    columns: string[];
    date_min?: string | null;
    date_max?: string | null;
    head: Array<Record<string, unknown>>;
    tail: Array<Record<string, unknown>>;
  };
};

export type ModelOverview = {
  current_profile?: string | null;
  current_profile_label?: string | null;
  active_profile?: string | null;
  active_profile_label?: string | null;
  training_profile?: string | null;
  training_metadata?: Record<string, unknown>;
  backtest_summary?: Record<string, unknown>;
  backtest_equity_curve?: Array<Record<string, unknown>>;
  artifact_status?: Record<string, Record<string, unknown>>;
  backtest_runs?: Array<Record<string, unknown>>;
  model_profiles?: Array<Record<string, unknown>>;
  default_profile?: string;
  active_profile_artifact_status?: Record<string, unknown>;
  top_features: Array<Record<string, unknown>>;
};

export type PicksOverview = {
  rows: number;
  latest_date?: string | null;
  source_close_date?: string | null;
  raw_sync_date?: string | null;
  feature_time?: string | null;
  data_src_time?: string | null;
  model_time?: string | null;
  profile_name?: string | null;
  picks: Array<Record<string, unknown>>;
};

export type PaperDaemonStatus = {
  status: string;
  status_label: string;
  is_running: boolean;
  can_start: boolean;
  can_stop: boolean;
  container_id?: string | null;
  container_name?: string | null;
  container_status?: string | null;
  container_started_at?: string | null;
  container_finished_at?: string | null;
  container_exit_code?: number | null;
  oom_killed?: boolean;
  log_file?: string | null;
  log_source?: string | null;
  log_lines: string[];
};

export type PaperGatewayStatus = {
  configured: boolean;
  healthy: boolean;
  base_url: string;
  market: string;
  agent_id: string;
  account_id?: number | null;
  details?: Record<string, unknown> | null;
  error?: string | null;
};

export type PaperTargetsOverview = {
  path: string;
  rows: number;
  latest_signal_date?: string | null;
  updated_at?: string | null;
};

export type PaperStatus = {
  daemon: PaperDaemonStatus;
  gateway: PaperGatewayStatus;
  state: Record<string, unknown>;
  targets: PaperTargetsOverview;
  history_tail: Array<Record<string, unknown>>;
  state_file: string;
  history_file: string;
  config: Record<string, unknown>;
};

export type PaperOverview = PaperStatus & {
  live_summary?: Record<string, unknown> | null;
  live_balance: Array<Record<string, unknown>>;
  live_positions_count: number;
  live_orders_count: number;
  balance_rows: number;
  live_error?: string | null;
};

export type PaperTargets = {
  rows: number;
  targets: Array<Record<string, unknown>>;
};

export type PaperPositions = {
  rows: number;
  positions: Array<Record<string, unknown>>;
  error?: string | null;
};

export type PaperOrders = {
  rows: number;
  orders: Array<Record<string, unknown>>;
  error?: string | null;
};

export type PaperHoldings = {
  generated_at?: string | null;
  gateway?: PaperGatewayStatus;
  source?: string | null;
  summary: Record<string, unknown>;
  balance: Array<Record<string, unknown>>;
  positions_rows: number;
  raw_positions_rows?: number;
  positions: Array<Record<string, unknown>>;
  orders_rows: number;
  orders: Array<Record<string, unknown>>;
  error?: string | null;
};

export type PaperDbHealth = {
  healthy: boolean;
  error?: string | null;
  fills: number;
  orders: number;
  positions: number;
};

export type PaperStockDetail = {
  symbol: string;
  summary: Record<string, unknown>;
  position?: Record<string, unknown> | null;
  daily: Array<Record<string, unknown>>;
  recent_orders: Array<Record<string, unknown>>;
  recent_fills: Array<Record<string, unknown>>;
  error?: string | null;
};

export type PaperStockLedger = {
  symbol: string;
  display_symbol?: string | null;
  name?: string | null;
  rows: number;
  ledger: Array<Record<string, unknown>>;
  daily: Array<Record<string, unknown>>;
  error?: string | null;
};

export type PaperStockSelectionHistory = {
  symbol: string;
  display_symbol?: string | null;
  name?: string | null;
  rows: number;
  latest_event?: Record<string, unknown> | null;
  events: Array<Record<string, unknown>>;
  latest_score?: Record<string, unknown> | null;
  error?: string | null;
};

export type PaperDailyHistory = {
  rows: number;
  daily: Array<Record<string, unknown>>;
  error?: string | null;
};

export type PaperDailyDetail = {
  trade_date: string;
  day?: Record<string, unknown> | null;
  error?: string | null;
};

export type PaperHistory = {
  rows: number;
  history: Array<Record<string, unknown>>;
};

export type PaperPerformanceRow = {
  recorded_at?: string | null;
  status?: string | null;
  score_signal_date?: string | null;
  message?: string | null;
  cash?: number | null;
  power?: number | null;
  total_assets?: number | null;
  market_value?: number | null;
  realized_pnl?: number | null;
  unrealized_pnl?: number | null;
  total_pnl?: number | null;
  position_count?: number | null;
  active_order_count?: number | null;
  target_count?: number | null;
  buy_order_count?: number | null;
  sell_order_count?: number | null;
  skip_count?: number | null;
  execution_skip_count?: number | null;
  estimated_order_fee?: number | null;
  placed_order_ids?: string[];
  cancelled_order_ids?: string[];
  skipped_symbols?: string[];
};

export type PaperPerformance = {
  rows: number;
  snapshots: PaperPerformanceRow[];
};

export type OverviewPerformancePoint = {
  date?: string | null;
  portfolio_value?: number | null;
  benchmark_value?: number | null;
  account_equity?: number | null;
};

export type OverviewTopPick = {
  rank?: number | null;
  code?: string | null;
  name?: string | null;
  industry?: string | null;
  signal_type?: string | null;
  confidence?: number | null;
  recommended_weight?: number | null;
  target_qty?: number | null;
  estimated_order_notional?: number | null;
  reason?: string | null;
  source?: string | null;
};

export type OverviewPortfolio = {
  generated_at?: string | null;
  account: {
    currency?: string | null;
    total_assets?: number | null;
    cash?: number | null;
    market_value?: number | null;
    total_pnl?: number | null;
    today_pnl?: number | null;
    today_pnl_pct?: number | null;
    updated_at?: string | null;
  };
  positions: {
    holding_count?: number | null;
    pending_buy_count?: number | null;
    pending_sell_count?: number | null;
    open_order_count?: number | null;
  };
  signals: {
    latest_signal_date?: string | null;
    new_signals_today?: number | null;
    pending_actions?: number | null;
  };
  performance: {
    benchmark: {
      code: string;
      name: string;
    };
    points: OverviewPerformancePoint[];
  };
  top_picks: OverviewTopPick[];
  warnings: string[];
};

export function getBatchStatus() {
  return fetchJson<BatchStatus>("/api/status/batch");
}

export function getWorkflowStatus() {
  return fetchJson<WorkflowStatus>("/api/status/workflow");
}

export function getPipelineRunStatus() {
  return fetchJson<PipelineRunStatus>("/api/status/pipeline");
}

export function getReferenceBatchStatus() {
  return fetchJson<ReferenceBatchStatus>("/api/status/reference");
}

export function getBatchLogs(tail = 120) {
  return fetchJson<BatchLogs>(`/api/logs/batch?tail=${tail}`);
}

export function getDataSummary() {
  return fetchJson<DataSummary>("/api/data/summary");
}

export function getPipelineSummary() {
  return fetchJson<PipelineSummary>("/api/data/pipeline");
}

export function getExplorerCatalog() {
  return fetchJson<ExplorerCatalog>("/api/data/explorer/catalog");
}

export function getExplorerQuery(params: {
  dataset: string;
  search?: string;
  filters?: ExplorerFilter[];
  columns?: string[];
  sort_by?: string;
  sort_dir?: string;
  page?: number;
  page_size?: number;
}) {
  const query = new URLSearchParams();
  query.set("dataset", params.dataset);
  if (params.search?.trim()) {
    query.set("search", params.search.trim());
  }
  if (params.sort_by?.trim()) {
    query.set("sort_by", params.sort_by.trim());
  }
  if (params.sort_dir?.trim()) {
    query.set("sort_dir", params.sort_dir.trim());
  }
  if (params.page) {
    query.set("page", String(params.page));
  }
  if (params.page_size) {
    query.set("page_size", String(params.page_size));
  }
  for (const column of params.columns ?? []) {
    if (column.trim()) {
      query.append("columns", column.trim());
    }
  }
  for (const filter of params.filters ?? []) {
    if (!filter.column || !filter.operator) {
      continue;
    }
    query.append("filter", JSON.stringify(filter));
  }
  return fetchJson<ExplorerQuery>(`/api/data/explorer/query?${query.toString()}`);
}

export function getStocks(limit = 30, search = "") {
  const query = search ? `&search=${encodeURIComponent(search)}` : "";
  return fetchJson<StockRow[]>(`/api/data/stocks?limit=${limit}${query}`);
}

export function getStockDetail(code: string) {
  return fetchJson<StockDetail>(`/api/data/stock/${code}`);
}

export function getModelOverview(profile?: string) {
  const query = profile ? `?profile=${encodeURIComponent(profile)}` : "";
  return fetchJson<ModelOverview>(`/api/model/latest${query}`);
}

export function getPicks(limit = 25, profile?: string) {
  const query = new URLSearchParams();
  query.set("limit", String(limit));
  if (profile) {
    query.set("profile", profile);
  }
  return fetchJson<PicksOverview>(`/api/model/picks?${query.toString()}`);
}

export function getAdminSettings() {
  return fetchJson<AdminSettings>("/api/admin/settings");
}

export function getPortfolioOverview() {
  return fetchJson<OverviewPortfolio>("/api/overview/portfolio");
}

export function getPaperStatus() {
  return fetchJson<PaperStatus>("/api/paper/status");
}

export function getPaperOverview(timeoutMs?: number) {
  return fetchJson<PaperOverview>("/api/paper/overview", { timeoutMs });
}

export function getPaperTargets(limit = 25) {
  return fetchJson<PaperTargets>(`/api/paper/targets?limit=${limit}`);
}

export function getPaperPositions(limit = 50, timeoutMs?: number) {
  return fetchJson<PaperPositions>(`/api/paper/positions?limit=${limit}`, { timeoutMs });
}

export function getPaperOrders(limit = 50, timeoutMs?: number) {
  return fetchJson<PaperOrders>(`/api/paper/orders?limit=${limit}`, { timeoutMs });
}

export function getPaperHoldings(positionLimit = 500, orderLimit = 200, timeoutMs?: number) {
  return fetchJson<PaperHoldings>(`/api/paper/holdings?position_limit=${positionLimit}&order_limit=${orderLimit}`, { timeoutMs });
}

export function getPaperDbHealth(timeoutMs?: number) {
  return fetchJson<PaperDbHealth>("/api/paper/db/health", { timeoutMs });
}

export function getPaperDbHoldings(positionLimit = 500, orderLimit = 200, timeoutMs?: number) {
  return fetchJson<PaperHoldings>(`/api/paper/db/holdings?position_limit=${positionLimit}&order_limit=${orderLimit}`, { timeoutMs });
}

export function getPaperDbDailyHistory(limit = 20, timeoutMs?: number, startDate?: string, endDate?: string) {
  const query = new URLSearchParams({ limit: String(limit) });
  if (startDate) query.set("start_date", startDate);
  if (endDate) query.set("end_date", endDate);
  return fetchJson<PaperDailyHistory>(`/api/paper/db/daily-history?${query.toString()}`, { timeoutMs });
}

export function getPaperDbDailyDetail(tradeDate: string, timeoutMs?: number) {
  return fetchJson<PaperDailyDetail>(`/api/paper/db/daily-history/${encodeURIComponent(tradeDate)}`, { timeoutMs });
}

export function getPaperDbOrders({
  symbol,
  status,
  startDate,
  endDate,
  limit = 200,
  timeoutMs
}: {
  symbol?: string;
  status?: string;
  startDate?: string;
  endDate?: string;
  limit?: number;
  timeoutMs?: number;
} = {}) {
  const query = new URLSearchParams({ limit: String(limit) });
  if (symbol) query.set("symbol", symbol);
  if (status) query.set("status", status);
  if (startDate) query.set("start_date", startDate);
  if (endDate) query.set("end_date", endDate);
  return fetchJson<PaperOrders>(`/api/paper/db/orders?${query.toString()}`, { timeoutMs });
}

export function getPaperDbFills({
  symbol,
  side,
  startDate,
  endDate,
  limit = 500,
  timeoutMs
}: {
  symbol?: string;
  side?: string;
  startDate?: string;
  endDate?: string;
  limit?: number;
  timeoutMs?: number;
} = {}) {
  const query = new URLSearchParams({ limit: String(limit) });
  if (symbol) query.set("symbol", symbol);
  if (side) query.set("side", side);
  if (startDate) query.set("start_date", startDate);
  if (endDate) query.set("end_date", endDate);
  return fetchJson<{ rows: number; fills: Array<Record<string, unknown>>; error?: string | null }>(`/api/paper/db/fills?${query.toString()}`, { timeoutMs });
}

export function getPaperDbStock(symbol: string, timeoutMs?: number) {
  return fetchJson<PaperStockDetail>(`/api/paper/db/stocks/${encodeURIComponent(symbol)}`, { timeoutMs });
}

export function getPaperDbStockLedger(symbol: string, limit = 1000, timeoutMs?: number) {
  return fetchJson<PaperStockLedger>(`/api/paper/db/stocks/${encodeURIComponent(symbol)}/ledger?limit=${limit}`, { timeoutMs });
}

export function getPaperDbStockSelectionHistory(symbol: string, timeoutMs?: number) {
  return fetchJson<PaperStockSelectionHistory>(`/api/paper/db/stocks/${encodeURIComponent(symbol)}/selection-history`, { timeoutMs });
}

export function getPaperDailyHistory(limit = 20, timeoutMs?: number) {
  return fetchJson<PaperDailyHistory>(`/api/paper/daily-history?limit=${limit}`, { timeoutMs });
}

export function getPaperHistory(limit = 50) {
  return fetchJson<PaperHistory>(`/api/paper/history?limit=${limit}`);
}

export function getPaperPerformance(limit = 240) {
  return fetchJson<PaperPerformance>(`/api/paper/performance?limit=${limit}`);
}

export type ResearchCompany = {
  symbol: string;
  market?: string | null;
  stock_name?: string | null;
  stock_name_zh?: string | null;
  stock_type?: string | null;
  stock_industry?: string | null;
  stock_industry_en?: string | null;
  stock_industry_short?: string | null;
  market_cap?: number | string | null;
  earnings_per_share?: number | string | null;
  pe_ratio?: number | string | null;
  currency?: string | null;
  trade_date?: string | null;
  close?: number | string | null;
  price_diff?: number | string | null;
  volume?: number | string | null;
  turnover?: number | string | null;
  average_trade?: number | string | null;
};

export type ResearchCompanySearch = {
  query: string;
  rows: number;
  total_active: number;
  companies: ResearchCompany[];
};

export type ResearchCompanySnapshot = {
  company: ResearchCompany;
  history: Array<Record<string, unknown>>;
  coverage: {
    observations?: number | null;
    date_min?: string | null;
    date_max?: string | null;
  };
  research_readiness: {
    market_data: string;
    sec_filings: string;
    financial_facts: string;
  };
};

export type ResearchFinancialMetric = {
  label: string;
  value: number | null;
  unit: string;
  taxonomy: string;
  concept: string;
  form: string;
  filed_date: string;
  accession_number: string;
  source_url: string;
  locator: string;
};

export type ResearchFinancialPeriod = {
  start_date?: string | null;
  end_date: string;
  fiscal_year?: number | null;
  fiscal_period?: string | null;
  period_kind: string;
  metrics: Record<string, ResearchFinancialMetric>;
  derived: Record<string, number | null>;
};

export type ResearchFinancialSummary = {
  symbol: string;
  status?: {
    status: string;
    fact_count: number;
    synced_at: string;
    source_url: string;
  } | null;
  coverage: {
    fact_rows: number;
    annual_periods: number;
    quarterly_periods: number;
    latest_end_date?: string | null;
  };
  latest_annual?: ResearchFinancialPeriod | null;
  previous_annual?: ResearchFinancialPeriod | null;
  annual_changes: Record<string, number | null>;
  latest_quarter?: ResearchFinancialPeriod | null;
  comparable_quarter?: ResearchFinancialPeriod | null;
  quarterly_yoy_changes: Record<string, number | null>;
  annual_series: ResearchFinancialPeriod[];
  quarterly_series: ResearchFinancialPeriod[];
  latest_balance_sheet?: ResearchFinancialPeriod | null;
  evidence: ResearchEvidence[];
};

export type ResearchEvidence = {
  id: string;
  claim: string;
  source: string;
  locator: string;
  as_of?: string | null;
  document_id?: string;
  page_number?: number | null;
  source_url?: string | null;
  source_format?: "pdf" | "sec_html" | string;
  native_page_numbers?: boolean;
  sec_cik?: string | null;
  sec_accession_number?: string | null;
  sec_primary_document?: string | null;
  source_metadata?: Record<string, unknown>;
  reranker_score?: number;
};

export type ResearchAnswer = {
  symbol: string;
  question: string;
  answer: string;
  document_evidence: ResearchEvidence[];
  data_evidence: ResearchEvidence[];
  model_inference: string[];
  limitations: string[];
  agent_steps: Array<{ tool: string; status: string; detail: string }>;
  tool_plan?: { tools: string[]; reason: string; planner: string };
  duration_ms?: number;
  model: { provider: string; name: string };
  retrieval?: {
    strategy?: string;
    embedding_model?: string;
    reranker_model?: string;
    indexed_documents?: number;
    lexical_candidates?: number;
    vector_candidates?: number;
    merged_candidates?: number;
    diversified_by_document?: boolean;
  };
};

export type ResearchComparison = {
  symbols: string[];
  question: string;
  answer: string;
  companies: Array<{
    symbol: string;
    company: ResearchCompany;
    calculations: {
      return_1d_pct?: number | null;
      return_5d_pct?: number | null;
      return_20d_pct?: number | null;
      annualized_volatility_pct?: number | null;
    };
    financials?: {
      end_date?: string | null;
      fiscal_year?: number | null;
      metrics?: Record<string, { value?: number | null; unit?: string; locator?: string }>;
      derived?: Record<string, number | null>;
      annual_changes?: Record<string, number | null>;
    } | null;
  }>;
  document_evidence: Array<ResearchEvidence & { symbol: string }>;
  financial_evidence?: Array<ResearchEvidence & { symbol: string }>;
  model_inference: string[];
  agent_steps: Array<{ tool: string; status: string; detail: string }>;
  model: { provider: string; name: string };
};

export type ResearchEvaluationRun = {
  id: string;
  benchmark_name: string;
  model_name: string;
  framework?: string;
  torch_version?: string;
  case_count: number;
  top1_accuracy: number;
  mean_reciprocal_rank: number;
  baseline_top1_accuracy: number;
  duration_ms: number;
  created_at?: string;
  details?: Array<{
    case: number;
    query: string;
    relevant_rank: number;
    reranker_top_passage: string;
    reranker_top_score: number;
    baseline_relevant_rank: number;
    passed: boolean;
  }>;
};

export type ResearchDocument = {
  id: string;
  symbol: string;
  filename: string;
  document_type: string;
  filing_date?: string | null;
  fiscal_year?: number | null;
  source_url?: string | null;
  source_format?: "pdf" | "sec_html" | string;
  native_page_numbers?: boolean;
  sec_cik?: string | null;
  sec_accession_number?: string | null;
  sec_primary_document?: string | null;
  source_metadata?: Record<string, unknown>;
  sha256: string;
  size_bytes: number;
  page_count?: number | null;
  chunk_count: number;
  status: "uploaded" | "processing" | "text_ready" | "indexed" | "failed" | string;
  error_message?: string | null;
  created_at: string;
  updated_at: string;
  duplicate?: boolean;
};

export type ResearchDocumentList = {
  rows: number;
  documents: ResearchDocument[];
};

export type FilingChangeEvidence = {
  chunk_id: string;
  document_id: string;
  filename: string;
  document_type: string;
  filing_date?: string | null;
  fiscal_year?: number | null;
  page_number?: number | null;
  locator_type: string;
  locator: string;
  source_url?: string | null;
  quote: string;
};

export type FilingChangeReview = {
  decision: "confirmed" | "rejected" | "needs_edit";
  reviewer: string;
  note?: string | null;
  created_at: string;
};

export type FilingChange = {
  id: string;
  sequence: number;
  change_type: "added" | "deleted" | "strengthened" | "weakened" | "rewritten";
  topic: string;
  materiality_score: number;
  similarity_score: number;
  summary: string;
  rationale: string;
  older_evidence: FilingChangeEvidence;
  newer_evidence: FilingChangeEvidence;
  review_status: "pending" | "confirmed" | "rejected" | "needs_edit";
  reviewed_by?: string | null;
  reviewer_note?: string | null;
  reviewed_at?: string | null;
  review_history?: FilingChangeReview[];
};

export type FilingChangeRun = {
  id: string;
  symbol: string;
  older_document_id: string;
  newer_document_id: string;
  status: "queued" | "running" | "completed" | "failed";
  algorithm_version: string;
  parameters: Record<string, unknown>;
  retry_of_run_id?: string | null;
  result_count: number;
  reviewed_count?: number;
  error_code?: string | null;
  error_message?: string | null;
  older_filename: string;
  older_filing_date?: string | null;
  older_fiscal_year?: number | null;
  newer_filename: string;
  newer_filing_date?: string | null;
  newer_fiscal_year?: number | null;
  created_at: string;
  completed_at?: string | null;
  changes?: FilingChange[];
};

export type FilingChangeRunList = {
  symbol: string;
  rows: number;
  runs: FilingChangeRun[];
};

export function getResearchCompanies(query = "", limit = 12) {
  const params = new URLSearchParams({ query, limit: String(limit) });
  return fetchJson<ResearchCompanySearch>(`/api/research/companies?${params.toString()}`, {
    timeoutMs: 10000,
    baseUrl: RESEARCH_API_BASE_URL
  });
}

export function getResearchCompany(symbol: string, historyLimit = 30) {
  const params = new URLSearchParams({ history_limit: String(historyLimit) });
  return fetchJson<ResearchCompanySnapshot>(
    `/api/research/companies/${encodeURIComponent(symbol)}?${params.toString()}`,
    { timeoutMs: 10000, baseUrl: RESEARCH_API_BASE_URL }
  );
}

export function getResearchDocuments(symbol?: string) {
  const params = new URLSearchParams();
  if (symbol) params.set("symbol", symbol);
  const query = params.size ? `?${params.toString()}` : "";
  return fetchJson<ResearchDocumentList>(`/api/research/documents${query}`, {
    timeoutMs: 10000,
    baseUrl: RESEARCH_API_BASE_URL
  });
}

export function getResearchFilingChangeRuns(symbol: string, limit = 20) {
  const params = new URLSearchParams({ symbol, limit: String(limit) });
  return fetchJson<FilingChangeRunList>(`/api/research/filing-changes?${params.toString()}`, {
    timeoutMs: 10000,
    baseUrl: RESEARCH_API_BASE_URL
  });
}

export function getResearchFinancials(symbol: string) {
  return fetchJson<ResearchFinancialSummary>(
    `/api/research/financials/${encodeURIComponent(symbol)}`,
    { timeoutMs: 10000, baseUrl: RESEARCH_API_BASE_URL }
  );
}

export type UsMarketContext = {
  market: "US";
  currency: "USD";
  timezone: "America/New_York";
  benchmark: { symbol: string; name: string };
  as_of: string;
  data_freshness?: Record<string, string | null>;
};

export type UsCoverage = {
  active_symbols: number;
  latest_trade_date?: string | null;
  first_trade_date?: string | null;
  trading_dates: number;
  total_bars: number;
  latest_symbols: number;
  latest_coverage_pct: number;
};

export type UsMarketSummary = UsMarketContext & {
  coverage: UsCoverage;
  exchanges: Array<{ exchange: string; symbols: number }>;
  fundamentals: {
    details_ready: number;
    industry_ready: number;
    market_cap_ready: number;
  };
};

export type UsStockRow = {
  symbol: string;
  exchange?: string | null;
  name?: string | null;
  name_zh?: string | null;
  industry?: string | null;
  market_cap?: number | null;
  currency?: string | null;
  trade_date?: string | null;
  close?: number | null;
  price_diff?: number | null;
  volume?: number | null;
  turnover?: number | null;
};

export type UsStocksResponse = UsMarketContext & {
  stocks: UsStockRow[];
  rows: number;
  total: number;
  limit: number;
  offset: number;
  search: string;
};

export type UsPick = {
  rank: number;
  symbol: string;
  exchange?: string | null;
  score?: number | null;
  signal_date?: string | null;
  name?: string | null;
  industry?: string | null;
  currency?: string | null;
  row_data?: Record<string, unknown>;
};

export type UsPicksResponse = UsMarketContext & {
  selection_type: "cat" | "lobster";
  selection_method: "rules_based";
  model_profile: null;
  picks: UsPick[];
  rows: number;
};

export type UsModelStatus = UsMarketContext & {
  profile: {
    name: string;
    label: string;
    horizon_trading_days: number;
    benchmark: { symbol: string; name: string };
    status: "insufficient_history" | "not_trained" | string;
  };
  gate: {
    ready: boolean;
    required_trading_dates: number;
    available_trading_dates: number;
    history_ready: boolean;
    training_ready: boolean;
    walk_forward_ready: boolean;
    blockers: string[];
  };
  metrics: Record<string, number> | null;
};

export type UsPipelineRun = {
  lane: string;
  target_date?: string | null;
  status: string;
  started_at?: string | null;
  completed_at?: string | null;
  total_count: number;
  done_count: number;
  failed_count: number;
  skipped_count: number;
  last_symbol?: string | null;
  last_error?: string | null;
};

export type UsPipelineStatus = UsMarketContext & {
  status: string;
  is_running: boolean;
  current_run?: UsPipelineRun | null;
  recent_runs: UsPipelineRun[];
  coverage: UsCoverage;
  scheduler: { timezone: string; lanes: string[] };
};

export type UsOverview = UsMarketContext & {
  summary: UsMarketSummary;
  top_picks: UsPick[];
  selection: { method: string; date?: string | null };
  model: UsModelStatus;
  pipeline: { status: string; is_running: boolean; current_run?: UsPipelineRun | null };
  paper: { status: string; enabled: boolean; message: string };
};

export type UsPaperStatus = UsMarketContext & {
  status: "gated" | string;
  enabled: boolean;
  account: null;
  positions: Array<Record<string, unknown>>;
  orders: Array<Record<string, unknown>>;
  gate: UsModelStatus["gate"];
  message: string;
};

const usFetch = <T>(path: string, timeoutMs = 15000) =>
  fetchJson<T>(path, { baseUrl: US_MARKET_API_BASE_URL, timeoutMs });

export function getUsOverview() {
  return usFetch<UsOverview>("/api/us/overview", 25000);
}

export function getUsMarketSummary() {
  return usFetch<UsMarketSummary>("/api/us/data/summary");
}

export function getUsStocks(search = "", limit = 50, offset = 0) {
  const params = new URLSearchParams({ search, limit: String(limit), offset: String(offset) });
  return usFetch<UsStocksResponse>(`/api/us/data/stocks?${params.toString()}`);
}

export function getUsModelStatus() {
  return usFetch<UsModelStatus>("/api/us/models");
}

export function getUsPicks(limit = 25, listType: "cat" | "lobster" = "cat") {
  const params = new URLSearchParams({ limit: String(limit), list_type: listType });
  return usFetch<UsPicksResponse>(`/api/us/picks?${params.toString()}`, 25000);
}

export function getUsPaperStatus() {
  return usFetch<UsPaperStatus>("/api/us/paper/status");
}

export function getUsPipelineStatus() {
  return usFetch<UsPipelineStatus>("/api/us/pipeline/status");
}
