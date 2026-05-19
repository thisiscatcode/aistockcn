"use client";

import { useMemo, useState } from "react";
import type { PanelLocale } from "@/lib/i18n";
import { formatDisplayValue } from "@/lib/format";

type TableRow = Record<string, unknown>;
type TableColumn = string | { key: string; label: string };

const NUMERIC_KEYWORDS = [
  "amount",
  "avg",
  "cap",
  "change",
  "close",
  "cost",
  "count",
  "drawdown",
  "future_return",
  "high",
  "low",
  "metric",
  "notional",
  "open",
  "pb",
  "pcf",
  "pe",
  "price",
  "ps",
  "qty",
  "quantity",
  "rank",
  "rate",
  "return",
  "score",
  "turnover",
  "value",
  "volume"
];

const TEXT_KEYWORDS = ["code", "date", "industry", "name", "symbol"];

function isNumericCell(value: unknown, key: string) {
  const normalizedKey = key.toLowerCase();
  if (TEXT_KEYWORDS.some((keyword) => normalizedKey === keyword || normalizedKey.endsWith(`_${keyword}`))) {
    return false;
  }
  if (typeof value === "number" && !Number.isNaN(value)) {
    return true;
  }
  if (typeof value !== "string" || !/^-?\d+(\.\d+)?$/.test(value.trim())) {
    return false;
  }
  return value.includes(".") || NUMERIC_KEYWORDS.some((keyword) => normalizedKey.includes(keyword));
}

function linkHref(row: TableRow, key: string): string | null {
  const value = row[`${key}_href`];
  if (typeof value !== "string") {
    return null;
  }
  const href = value.trim();
  return href ? href : null;
}

function cellDetail(row: TableRow, key: string): string | null {
  const value = row[`${key}_detail`];
  if (typeof value !== "string") {
    return null;
  }
  const detail = value.trim();
  return detail ? detail : null;
}

function cellTitle(row: TableRow, key: string, fallback: string) {
  const detail = cellDetail(row, key);
  return detail ? `${fallback} / ${detail}` : fallback;
}

function cellTone(row: TableRow, key: string): string | null {
  const value = row[`${key}_tone`];
  if (value === "positive" || value === "negative" || value === "neutral") {
    return value;
  }
  return null;
}

export function DataTable({
  rows,
  columns,
  emptyLabel,
  locale = "en",
  pageSize,
  pageSizeOptions = [10, 25, 50, 100]
}: {
  rows: TableRow[];
  columns?: TableColumn[];
  emptyLabel?: string;
  locale?: PanelLocale;
  pageSize?: number;
  pageSizeOptions?: number[];
}) {
  const normalizedPageSizeOptions = useMemo(
    () => Array.from(new Set(pageSizeOptions.filter((option) => Number.isInteger(option) && option > 0))).sort((left, right) => left - right),
    [pageSizeOptions]
  );
  const initialPageSize = pageSize ?? normalizedPageSizeOptions[0] ?? 25;
  const [currentPage, setCurrentPage] = useState(1);
  const [currentPageSize, setCurrentPageSize] = useState(initialPageSize);

  if (!rows.length) {
    return <p className="empty-state">{emptyLabel ?? "No rows to display."}</p>;
  }

  const hasPagination = typeof pageSize === "number" && pageSize > 0 && rows.length > pageSize;
  const totalPages = hasPagination ? Math.max(1, Math.ceil(rows.length / currentPageSize)) : 1;
  const safeCurrentPage = Math.min(currentPage, totalPages);
  const visibleRows = hasPagination
    ? rows.slice((safeCurrentPage - 1) * currentPageSize, safeCurrentPage * currentPageSize)
    : rows;
  const headers = columns ?? Object.keys(rows[0]);
  const normalizedHeaders = headers.map((header) =>
    typeof header === "string" ? { key: header, label: header } : header
  );
  const numericColumns = new Set(
    normalizedHeaders
      .filter((header) => rows.some((row) => isNumericCell(row[header.key], header.key)))
      .map((header) => header.key)
  );

  return (
    <>
      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              {normalizedHeaders.map((header) => (
                <th key={header.key} className={numericColumns.has(header.key) ? "data-table-cell-numeric" : undefined}>
                  {header.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visibleRows.map((row, index) => (
              <tr key={`${(safeCurrentPage - 1) * currentPageSize + index}-${normalizedHeaders[0]?.key ?? "row"}`}>
                {normalizedHeaders.map((header) => {
                  const value = formatDisplayValue(row[header.key], { locale, key: header.key });
                  const href = linkHref(row, header.key);
                  const detail = cellDetail(row, header.key);
                  const tone = cellTone(row, header.key);
                  const contentClassName = [
                    detail ? "data-table-cell-stack" : "data-table-cell-content",
                    tone ? `data-table-cell-tone-${tone}` : null
                  ].filter(Boolean).join(" ");
                  return (
                    <td key={header.key} className={numericColumns.has(header.key) ? "data-table-cell-numeric" : undefined}>
                      <span className={contentClassName} title={cellTitle(row, header.key, value)}>
                        {href ? (
                          <a className="data-table-link" href={href} target="_blank" rel="noopener noreferrer">
                            {value}
                          </a>
                        ) : (
                          value
                        )}
                        {detail ? <span className="data-table-cell-detail">{detail}</span> : null}
                      </span>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {hasPagination ? (
        <div className="table-pagination">
          <label className="table-page-size">
            Rows
            <select
              value={currentPageSize}
              onChange={(event) => {
                setCurrentPageSize(Number(event.target.value));
                setCurrentPage(1);
              }}
            >
              {normalizedPageSizeOptions.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </label>
          <span className="pill">
            Page {safeCurrentPage} / {totalPages}
          </span>
          <div className="table-pagination-controls">
            <button
              className="action-button secondary-button table-page-button"
              disabled={safeCurrentPage <= 1}
              type="button"
              onClick={() => setCurrentPage((page) => Math.max(1, page - 1))}
            >
              Previous
            </button>
            <button
              className="action-button secondary-button table-page-button"
              disabled={safeCurrentPage >= totalPages}
              type="button"
              onClick={() => setCurrentPage((page) => Math.min(totalPages, page + 1))}
            >
              Next
            </button>
          </div>
        </div>
      ) : null}
    </>
  );
}
