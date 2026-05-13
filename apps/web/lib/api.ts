export const API_BASE_URL =
  process.env.API_BASE_URL ??
  process.env.NEXT_PUBLIC_API_BASE_URL ??
  "http://127.0.0.1:8000";

type FetchJsonOptions = {
  timeoutMs?: number;
};

async function fetchJson<T>(path: string, options: FetchJsonOptions = {}): Promise<T> {
  const controller = options.timeoutMs ? new AbortController() : null;
  const timeout = controller
    ? setTimeout(() => controller.abort(), options.timeoutMs)
    : null;

  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
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
  training_metadata?: Record<string, unknown>;
  backtest_summary?: Record<string, unknown>;
  backtest_runs?: Array<Record<string, unknown>>;
  model_profiles?: Array<Record<string, unknown>>;
  default_profile?: string;
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
  placed_order_ids?: string[];
  cancelled_order_ids?: string[];
  skipped_symbols?: string[];
};

export type PaperPerformance = {
  rows: number;
  snapshots: PaperPerformanceRow[];
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

export function getModelOverview() {
  return fetchJson<ModelOverview>("/api/model/latest");
}

export function getPicks(limit = 25) {
  return fetchJson<PicksOverview>(`/api/model/picks?limit=${limit}`);
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

export function getPaperHistory(limit = 50) {
  return fetchJson<PaperHistory>(`/api/paper/history?limit=${limit}`);
}

export function getPaperPerformance(limit = 240) {
  return fetchJson<PaperPerformance>(`/api/paper/performance?limit=${limit}`);
}
