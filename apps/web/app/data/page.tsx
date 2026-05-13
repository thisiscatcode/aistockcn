import { MetricCard, Panel } from "@/components/cards";
import { Shell } from "@/components/shell";
import { DataTable } from "@/components/table";
import {
  getExplorerCatalog,
  getExplorerQuery,
  type ExplorerFilter
} from "@/lib/api";
import { requireAuth } from "@/lib/auth";
import { formatBytes, formatDateTime, formatNumber } from "@/lib/format";
import { getMessages } from "@/lib/i18n";

export const dynamic = "force-dynamic";

type SearchValue = string | string[] | undefined;

function firstValue(value: SearchValue) {
  if (Array.isArray(value)) {
    return value[0];
  }
  return value;
}

function allValues(value: SearchValue) {
  if (!value) {
    return [];
  }
  return Array.isArray(value) ? value : [value];
}

function buildFilterSlots(params: Record<string, SearchValue>) {
  const filters: ExplorerFilter[] = [];
  for (let index = 1; index <= 3; index += 1) {
    const column = String(firstValue(params[`f${index}_column`]) ?? "").trim();
    const operator = String(firstValue(params[`f${index}_operator`]) ?? "").trim();
    const value = String(firstValue(params[`f${index}_value`]) ?? "").trim();
    const valueTo = String(firstValue(params[`f${index}_value_to`]) ?? "").trim();
    if (!column || !operator) {
      continue;
    }
    filters.push({
      column,
      operator,
      value: value || undefined,
      value_to: valueTo || undefined
    });
  }
  return filters;
}

function pageHref({
  dataset,
  search,
  page,
  pageSize,
  sortBy,
  sortDir,
  columns,
  filters,
  exportFormat
}: {
  dataset: string;
  search: string;
  page: number;
  pageSize: number;
  sortBy: string;
  sortDir: string;
  columns: string[];
  filters: ExplorerFilter[];
  exportFormat?: string;
}) {
  const query = new URLSearchParams();
  query.set("dataset", dataset);
  if (search.trim()) {
    query.set("search", search.trim());
  }
  query.set("page", String(page));
  query.set("page_size", String(pageSize));
  query.set("sort_by", sortBy);
  query.set("sort_dir", sortDir);
  for (const column of columns) {
    query.append("columns", column);
  }
  filters.forEach((filter, index) => {
    query.set(`f${index + 1}_column`, filter.column);
    query.set(`f${index + 1}_operator`, filter.operator);
    if (filter.value) {
      query.set(`f${index + 1}_value`, filter.value);
    }
    if (filter.value_to) {
      query.set(`f${index + 1}_value_to`, filter.value_to);
    }
  });
  if (exportFormat) {
    query.set("export_format", exportFormat);
    return `/data/export?${query.toString()}`;
  }
  return `/data?${query.toString()}`;
}

export default async function DataPage({
  searchParams
}: {
  searchParams?: Promise<Record<string, SearchValue>>;
}) {
  const user = await requireAuth();
  const copy = getMessages(user.locale);
  const params = (await searchParams) ?? {};
  const catalog = await getExplorerCatalog();
  const availableDatasets = catalog.datasets.filter((dataset) => dataset.column_count > 0);
  const fallbackDataset = availableDatasets[0] ?? catalog.datasets[0];
  const datasetKey = String(firstValue(params.dataset) ?? fallbackDataset?.key ?? "training_features");
  const dataset = catalog.datasets.find((item) => item.key === datasetKey) ?? fallbackDataset;

  if (!dataset) {
    return (
      <Shell
        title="Data Explorer"
        subtitle=""
        locale={user.locale}
        username={user.username}
        role={user.role}
      >
        <Panel title="No Data">
          <p className="empty-state">{copy.common.noRows}</p>
        </Panel>
      </Shell>
    );
  }

  const search = String(firstValue(params.search) ?? "").trim();
  const page = Math.max(Number.parseInt(String(firstValue(params.page) ?? "1"), 10) || 1, 1);
  const pageSize = Math.min(Math.max(Number.parseInt(String(firstValue(params.page_size) ?? "50"), 10) || 50, 1), 200);
  const sortBy = String(firstValue(params.sort_by) ?? dataset.default_columns[0] ?? dataset.columns[0]?.name ?? "date");
  const sortDir = String(firstValue(params.sort_dir) ?? "desc");
  const selectedColumns = allValues(params.columns).filter((value) => dataset.columns.some((column) => column.name === value));
  const filters = buildFilterSlots(params);

  const queryStartedAt = Date.now();
  const result = await getExplorerQuery({
    dataset: dataset.key,
    search,
    filters,
    columns: selectedColumns,
    sort_by: sortBy,
    sort_dir: sortDir,
    page,
    page_size: pageSize
  });
  const queryElapsedSeconds = ((Date.now() - queryStartedAt) / 1000).toFixed(2);

  const paginationBase = {
    dataset: dataset.key,
    search,
    pageSize: result.page_size,
    sortBy: result.sort_by,
    sortDir: result.sort_dir,
    columns: result.selected_columns,
    filters
  };

  return (
    <Shell
      title="Data Explorer"
      subtitle=""
      locale={user.locale}
      username={user.username}
      role={user.role}
    >
      <section className="metrics-grid">
        <MetricCard label="Current Dataset" value={dataset.label} hint={dataset.key} />
        <MetricCard label="Total Rows" value={formatNumber(result.total_rows, user.locale)} hint="Rows in saved parquet" />
        <MetricCard label="Filtered Rows" value={formatNumber(result.filtered_rows, user.locale)} hint="Rows matching current query" />
        <MetricCard label="Columns" value={formatNumber(dataset.column_count, user.locale)} hint={formatBytes(dataset.size_bytes, user.locale)} />
        <MetricCard label="Page" value={`${result.page}/${result.total_pages}`} hint={`${formatNumber(result.page_size, user.locale)} rows / page`} />
        <MetricCard label="Updated" value={formatDateTime(dataset.updated_at, user.locale)} hint={dataset.path} />
      </section>

      <section className="explorer-layout">
        <Panel title="Datasets">
          <div className="dataset-catalog">
            {catalog.datasets.map((item) => (
              <a
                key={item.key}
                href={`/data?dataset=${item.key}`}
                className={`dataset-card ${item.key === dataset.key ? "dataset-card-active" : ""}`}
              >
                <strong>{item.label}</strong>
                <span className="dataset-card-metric">{formatNumber(item.row_count, user.locale)} rows</span>
                <span className="dataset-card-metric">{formatNumber(item.column_count, user.locale)} cols</span>
                <span className="dataset-card-metric">{formatDateTime(item.updated_at, user.locale)}</span>
              </a>
            ))}
          </div>
        </Panel>

        <div className="explorer-main">
          <Panel title="Query Builder">
            <form method="get" action="/data" className="explorer-form">
              <input type="hidden" name="dataset" value={dataset.key} />
              <div className="explorer-form-grid">
                <label className="field-block">
                  <span>Search</span>
                  <input type="text" name="search" defaultValue={search} placeholder="code / name / industry" />
                </label>
                <label className="field-block">
                  <span>Sort By</span>
                  <select name="sort_by" defaultValue={result.sort_by}>
                    {dataset.columns.map((column) => (
                      <option key={column.name} value={column.name}>
                        {column.name}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="field-block">
                  <span>Sort Direction</span>
                  <select name="sort_dir" defaultValue={result.sort_dir}>
                    <option value="desc">Descending</option>
                    <option value="asc">Ascending</option>
                  </select>
                </label>
                <label className="field-block">
                  <span>Rows Per Page</span>
                  <select name="page_size" defaultValue={String(result.page_size)}>
                    {[25, 50, 100, 200].map((size) => (
                      <option key={size} value={size}>
                        {size}
                      </option>
                    ))}
                  </select>
                </label>
              </div>

              <div className="filter-builder">
                {[1, 2, 3].map((index) => {
                  const current = filters[index - 1];
                  return (
                    <div key={index} className="filter-row">
                      <select name={`f${index}_column`} defaultValue={current?.column ?? ""}>
                        <option value="">{`Filter ${index} Column`}</option>
                        {dataset.columns.map((column) => (
                          <option key={column.name} value={column.name}>
                            {column.name}
                          </option>
                        ))}
                      </select>
                      <select name={`f${index}_operator`} defaultValue={current?.operator ?? ""}>
                        <option value="">Operator</option>
                        <option value="eq">=</option>
                        <option value="neq">!=</option>
                        <option value="gt">&gt;</option>
                        <option value="gte">&gt;=</option>
                        <option value="lt">&lt;</option>
                        <option value="lte">&lt;=</option>
                        <option value="between">Between</option>
                        <option value="contains">Contains</option>
                        <option value="starts_with">Starts With</option>
                        <option value="ends_with">Ends With</option>
                        <option value="is_null">Is Null</option>
                        <option value="not_null">Not Null</option>
                      </select>
                      <input type="text" name={`f${index}_value`} defaultValue={current?.value ?? ""} placeholder="Value" />
                      <input type="text" name={`f${index}_value_to`} defaultValue={current?.value_to ?? ""} placeholder="Second Value / Upper Bound" />
                    </div>
                  );
                })}
              </div>

              <div className="column-picker">
                {dataset.columns.map((column) => {
                  const checked = result.selected_columns.includes(column.name);
                  return (
                    <label key={column.name} className="checkbox-chip">
                      <input type="checkbox" name="columns" value={column.name} defaultChecked={checked} />
                      <span>{column.name}</span>
                      <small>{column.type}</small>
                    </label>
                  );
                })}
              </div>

              <div className="action-row explorer-actions">
                <button className="action-button" type="submit">
                  Apply Query
                </button>
                <a href={`/data?dataset=${dataset.key}`} className="action-button secondary-button">
                  Reset
                </a>
                <a href={pageHref({ ...paginationBase, page: 1, exportFormat: "csv" })} className="action-button secondary-button">
                  Export CSV
                </a>
                <a href={pageHref({ ...paginationBase, page: 1, exportFormat: "parquet" })} className="action-button secondary-button">
                  Export Parquet
                </a>
              </div>

              <p className="panel-copy">
                {`Exports are capped at ${formatNumber(result.max_export_rows, user.locale)} rows. Narrow the query first if you need more.`}
              </p>
            </form>
          </Panel>

          <Panel
            title="Result Table"
            aside={<span className="pill">{formatNumber(result.filtered_rows, user.locale)} rows</span>}
          >
            <div className="status-meta">
              <span className="status-meta-item query-execution-note">
                <span className="status-meta-value">Query executed in {queryElapsedSeconds}s</span>
              </span>
              <span className="status-meta-separator">•</span>
              <span className="status-meta-item">
                <span className="status-meta-label">Search</span>
                <span className="status-meta-value">{result.search || "—"}</span>
              </span>
              <span className="status-meta-separator">•</span>
              <span className="status-meta-item">
                <span className="status-meta-label">Sort</span>
                <span className="status-meta-value">{result.sort_by} / {result.sort_dir}</span>
              </span>
              <span className="status-meta-separator">•</span>
              <span className="status-meta-item status-meta-columns">
                <span className="status-meta-label">Columns</span>
                <span className="status-meta-value">{result.selected_columns.join(", ") || "—"}</span>
              </span>
            </div>
            <DataTable
              rows={result.rows}
              columns={result.selected_columns.map((column) => ({ key: column, label: column }))}
              emptyLabel={copy.common.noRows}
              locale={user.locale}
            />
            <div className="pagination-row">
              <a
                href={pageHref({ ...paginationBase, page: Math.max(1, result.page - 1) })}
                className={`action-button secondary-button ${result.page <= 1 ? "button-disabled" : ""}`}
                aria-disabled={result.page <= 1}
              >
                Previous
              </a>
              <span className="pill">
                Page {result.page} / {result.total_pages}
              </span>
              <a
                href={pageHref({ ...paginationBase, page: Math.min(result.total_pages, result.page + 1) })}
                className={`action-button secondary-button ${result.page >= result.total_pages ? "button-disabled" : ""}`}
                aria-disabled={result.page >= result.total_pages}
              >
                Next
              </a>
            </div>
          </Panel>
        </div>
      </section>
    </Shell>
  );
}
