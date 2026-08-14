from __future__ import annotations

import hashlib
import json
import math
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from app.config import Settings, get_settings
from app.services.research import ResearchError, normalize_us_symbol
from app.services.research_documents import _run_schema_migration, _write_connection
from app.services.research_sec import _sec_request, resolve_sec_cik


SEC_COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

FINANCIAL_METRICS: dict[str, dict[str, Any]] = {
    "revenue": {
        "label": "Revenue",
        "unit": "USD",
        "concepts": (
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "Revenues",
            "SalesRevenueNet",
        ),
    },
    "gross_profit": {
        "label": "Gross profit",
        "unit": "USD",
        "concepts": ("GrossProfit",),
    },
    "operating_income": {
        "label": "Operating income",
        "unit": "USD",
        "concepts": ("OperatingIncomeLoss",),
    },
    "net_income": {
        "label": "Net income",
        "unit": "USD",
        "concepts": ("NetIncomeLoss", "ProfitLoss"),
    },
    "eps_diluted": {
        "label": "Diluted EPS",
        "unit": "USD/shares",
        "concepts": ("EarningsPerShareDiluted",),
    },
    "operating_cash_flow": {
        "label": "Operating cash flow",
        "unit": "USD",
        "concepts": ("NetCashProvidedByUsedInOperatingActivities",),
    },
    "capital_expenditure": {
        "label": "Capital expenditure",
        "unit": "USD",
        "concepts": (
            "PaymentsToAcquirePropertyPlantAndEquipment",
            "PaymentsForAdditionsToPropertyPlantAndEquipment",
        ),
    },
    "cash_and_equivalents": {
        "label": "Cash and equivalents",
        "unit": "USD",
        "concepts": (
            "CashAndCashEquivalentsAtCarryingValue",
            "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        ),
    },
    "assets": {
        "label": "Total assets",
        "unit": "USD",
        "concepts": ("Assets",),
    },
    "liabilities": {
        "label": "Total liabilities",
        "unit": "USD",
        "concepts": ("Liabilities",),
    },
    "stockholders_equity": {
        "label": "Stockholders' equity",
        "unit": "USD",
        "concepts": ("StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"),
    },
}

IFRS_METRIC_CONCEPTS: dict[str, tuple[str, ...]] = {
    "revenue": ("Revenue", "RevenueFromContractsWithCustomers"),
    "gross_profit": ("GrossProfit",),
    "operating_income": ("ProfitLossFromOperatingActivities",),
    "net_income": ("ProfitLoss",),
    "eps_diluted": ("DilutedEarningsLossPerShare",),
    "operating_cash_flow": ("CashFlowsFromUsedInOperatingActivities",),
    "capital_expenditure": ("PurchaseOfPropertyPlantAndEquipment",),
    "cash_and_equivalents": ("CashAndCashEquivalents",),
    "assets": ("Assets",),
    "liabilities": ("Liabilities",),
    "stockholders_equity": ("Equity",),
}


RESEARCH_FINANCIAL_SCHEMA_SQL = """
create table if not exists research_financial_facts (
  id text primary key,
  symbol text not null references us_stock_master(symbol),
  cik text not null,
  metric text not null,
  metric_label text not null,
  taxonomy text not null,
  concept text not null,
  concept_priority integer not null,
  concept_label text,
  concept_description text,
  unit text not null,
  value numeric not null,
  start_date date,
  end_date date not null,
  period_kind text not null,
  fiscal_year integer,
  fiscal_period text,
  form text not null,
  filed_date date not null,
  accession_number text not null,
  frame text,
  source_url text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists research_financial_facts_symbol_period_idx
  on research_financial_facts(symbol, period_kind, end_date desc, metric);
create index if not exists research_financial_facts_accession_idx
  on research_financial_facts(accession_number);

create table if not exists research_financial_sync_status (
  symbol text primary key references us_stock_master(symbol),
  cik text not null,
  entity_name text,
  source_url text not null,
  fact_count integer not null default 0,
  status text not null,
  error_message text,
  synced_at timestamptz not null default now()
);

alter table research_financial_facts add column if not exists market text not null default 'US';
alter table research_financial_facts add column if not exists issuer_id text;
alter table research_financial_facts add column if not exists source_provider text not null default 'SEC';
alter table research_financial_facts add column if not exists validation_status text not null default 'validated';
alter table research_financial_facts add column if not exists validation_checks jsonb not null default '{}'::jsonb;
alter table research_financial_facts add column if not exists source_document_id text;
update research_financial_facts set issuer_id = 'US:' || symbol where issuer_id is null;
alter table research_financial_sync_status add column if not exists market text not null default 'US';
alter table research_financial_sync_status add column if not exists issuer_id text;
update research_financial_sync_status set issuer_id = 'US:' || symbol where issuer_id is null;

do $$
declare constraint_row record;
begin
  for constraint_row in
    select conrelid::regclass::text as table_name, conname
    from pg_constraint
    where contype = 'f'
      and confrelid = 'us_stock_master'::regclass
      and conrelid in ('research_financial_facts'::regclass, 'research_financial_sync_status'::regclass)
  loop
    execute format('alter table %I drop constraint %I', constraint_row.table_name, constraint_row.conname);
  end loop;
end $$;
"""


def init_research_financial_schema() -> None:
    _run_schema_migration(
        migration_id="research_financials_v2_market_validation",
        lock_id=87_072_402,
        statements=(RESEARCH_FINANCIAL_SCHEMA_SQL,),
        required_columns=(
            ("research_financial_facts", "market"),
            ("research_financial_facts", "validation_status"),
            ("research_financial_facts", "validation_checks"),
            ("research_financial_facts", "issuer_id"),
        ),
    )


def _safe_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


def _period_kind(*, start_date: date | None, end_date: date, form: str, fiscal_period: str) -> str:
    if start_date is None:
        return "instant"
    days = (end_date - start_date).days + 1
    if form in {"10-K", "20-F", "40-F"} and fiscal_period == "FY" and 300 <= days <= 430:
        return "annual"
    if 70 <= days <= 110:
        return "quarter"
    return "year_to_date"


def _filing_index_url(cik: str, accession_number: str) -> str:
    accession_path = "".join(character for character in accession_number if character.isdigit())
    return (
        f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
        f"{accession_path}/{accession_number}-index.html"
    )


def normalize_companyfacts_payload(
    *, symbol: str, cik: str, payload: dict[str, Any]
) -> list[dict[str, Any]]:
    normalized_symbol = normalize_us_symbol(symbol)
    rows: list[dict[str, Any]] = []
    taxonomies = (
        ("us-gaap", {metric: tuple(definition["concepts"]) for metric, definition in FINANCIAL_METRICS.items()}),
        ("ifrs-full", IFRS_METRIC_CONCEPTS),
    )
    facts = payload.get("facts", {})
    for taxonomy_priority, (taxonomy, metric_concepts) in enumerate(taxonomies):
        taxonomy_facts = facts.get(taxonomy, {}) if isinstance(facts, dict) else {}
        if not isinstance(taxonomy_facts, dict):
            continue
        for metric, concepts in metric_concepts.items():
            definition = FINANCIAL_METRICS[metric]
            expected_unit = str(definition["unit"])
            for priority, concept in enumerate(concepts):
                concept_payload = taxonomy_facts.get(concept)
                if not isinstance(concept_payload, dict):
                    continue
                units = concept_payload.get("units", {})
                if not isinstance(units, dict):
                    continue
                unit = _preferred_fact_unit(units=units, expected_unit=expected_unit)
                if unit is None:
                    continue
                entries = units.get(unit, [])
                for item in entries if isinstance(entries, list) else []:
                    if not isinstance(item, dict) or str(item.get("form") or "") not in {"10-K", "10-Q", "20-F", "40-F"}:
                        continue
                    end_date = _safe_date(item.get("end"))
                    filed_date = _safe_date(item.get("filed"))
                    accession_number = str(item.get("accn") or "").strip()
                    if end_date is None or filed_date is None or not accession_number:
                        continue
                    try:
                        value = Decimal(str(item.get("val")))
                    except (InvalidOperation, TypeError, ValueError):
                        continue
                    if not value.is_finite():
                        continue
                    start_date = _safe_date(item.get("start"))
                    fiscal_period = str(item.get("fp") or "").strip().upper()
                    form = str(item.get("form") or "").strip().upper()
                    identity = "|".join(
                        [
                            normalized_symbol, taxonomy, concept, unit,
                            str(start_date or ""), str(end_date), accession_number,
                            fiscal_period, form,
                        ]
                    )
                    rows.append({
                        "id": hashlib.sha256(identity.encode("utf-8")).hexdigest(),
                        "symbol": normalized_symbol,
                        "cik": cik,
                        "metric": metric,
                        "metric_label": definition["label"],
                        "taxonomy": taxonomy,
                        "concept": concept,
                        "concept_priority": taxonomy_priority * 100 + priority,
                        "concept_label": concept_payload.get("label"),
                        "concept_description": concept_payload.get("description"),
                        "unit": unit,
                        "value": value,
                        "start_date": start_date,
                        "end_date": end_date,
                        "period_kind": _period_kind(
                            start_date=start_date,
                            end_date=end_date,
                            form=form,
                            fiscal_period=fiscal_period,
                        ),
                        "fiscal_year": int(item["fy"]) if str(item.get("fy") or "").isdigit() else None,
                        "fiscal_period": fiscal_period or None,
                        "form": form,
                        "filed_date": filed_date,
                        "accession_number": accession_number,
                        "frame": str(item.get("frame") or "").strip() or None,
                        "source_url": _filing_index_url(cik, accession_number),
                    })
    return rows


def _preferred_fact_unit(*, units: dict[str, Any], expected_unit: str) -> str | None:
    if expected_unit in units:
        return expected_unit
    share_based = expected_unit.endswith("/shares")
    candidates = [
        str(unit)
        for unit in units
        if (str(unit).endswith("/shares") if share_based else "/" not in str(unit))
        and len(str(unit).split("/", 1)[0]) == 3
        and str(unit).split("/", 1)[0].isalpha()
    ]
    return sorted(candidates)[0] if candidates else None


def sync_sec_companyfacts(*, symbol: str, settings: Settings | None = None) -> dict[str, Any]:
    resolved = settings or get_settings()
    normalized_symbol = normalize_us_symbol(symbol)
    cik = resolve_sec_cik(normalized_symbol)
    source_url = SEC_COMPANYFACTS_URL.format(cik=cik)
    try:
        payload = json.loads(_sec_request(source_url, settings=resolved).decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ResearchError("sec_companyfacts_invalid_response") from exc
    rows = normalize_companyfacts_payload(symbol=normalized_symbol, cik=cik, payload=payload)
    if not rows:
        raise ResearchError("sec_companyfacts_no_supported_facts")
    with _write_connection(resolved) as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                insert into research_financial_facts (
                  id, symbol, cik, metric, metric_label, taxonomy, concept, concept_priority,
                  concept_label, concept_description, unit, value, start_date, end_date,
                  period_kind, fiscal_year, fiscal_period, form, filed_date, accession_number,
                  frame, source_url
                ) values (
                  %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                  %s, %s, %s, %s, %s, %s, %s, %s
                )
                on conflict (id) do update set
                  value = excluded.value,
                  concept_label = excluded.concept_label,
                  concept_description = excluded.concept_description,
                  frame = excluded.frame,
                  source_url = excluded.source_url,
                  updated_at = now()
                """,
                [
                    [
                        row["id"], row["symbol"], row["cik"], row["metric"], row["metric_label"],
                        row["taxonomy"], row["concept"], row["concept_priority"], row["concept_label"],
                        row["concept_description"], row["unit"], row["value"], row["start_date"],
                        row["end_date"], row["period_kind"], row["fiscal_year"], row["fiscal_period"],
                        row["form"], row["filed_date"], row["accession_number"], row["frame"],
                        row["source_url"],
                    ]
                    for row in rows
                ],
            )
            cur.execute(
                """
                insert into research_financial_sync_status (
                  symbol, cik, entity_name, source_url, fact_count, status, error_message, synced_at
                ) values (%s, %s, %s, %s, %s, 'ready', null, now())
                on conflict (symbol) do update set
                  cik = excluded.cik,
                  entity_name = excluded.entity_name,
                  source_url = excluded.source_url,
                  fact_count = excluded.fact_count,
                  status = 'ready',
                  error_message = null,
                  synced_at = now()
                """,
                [normalized_symbol, cik, payload.get("entityName"), source_url, len(rows)],
            )
        conn.commit()
    return {
        "symbol": normalized_symbol,
        "cik": cik,
        "entity_name": payload.get("entityName"),
        "source_url": source_url,
        "normalized_facts": len(rows),
        "metrics": sorted({row["metric"] for row in rows}),
        "status": "ready",
    }


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _change_pct(latest: float | None, previous: float | None) -> float | None:
    if latest is None or previous in {None, 0}:
        return None
    return round((latest / previous - 1.0) * 100.0, 2)


def _period_record(rows: list[dict[str, Any]]) -> dict[str, Any]:
    metrics: dict[str, dict[str, Any]] = {}
    for row in sorted(rows, key=lambda item: (int(item["concept_priority"]), str(item["filed_date"])), reverse=False):
        metric = str(row["metric"])
        if metric in metrics:
            continue
        metrics[metric] = {
            "label": row["metric_label"],
            "value": _number(row["value"]),
            "unit": row["unit"],
            "taxonomy": row["taxonomy"],
            "concept": row["concept"],
            "form": row["form"],
            "filed_date": row["filed_date"],
            "accession_number": row["accession_number"],
            "source_url": row["source_url"],
            "locator": (
                f"{row['taxonomy']}:{row['concept']} · {row['form']} "
                f"{row.get('fiscal_period') or ''}{row.get('fiscal_year') or ''} · "
                f"period ended {row['end_date']} · accession {row['accession_number']}"
            ),
        }
    revenue = metrics.get("revenue", {}).get("value")
    gross_profit = metrics.get("gross_profit", {}).get("value")
    operating_income = metrics.get("operating_income", {}).get("value")
    net_income = metrics.get("net_income", {}).get("value")
    operating_cash_flow = metrics.get("operating_cash_flow", {}).get("value")
    capital_expenditure = metrics.get("capital_expenditure", {}).get("value")
    derived = {
        "gross_margin_pct": round(gross_profit / revenue * 100, 2) if revenue and gross_profit is not None else None,
        "operating_margin_pct": round(operating_income / revenue * 100, 2) if revenue and operating_income is not None else None,
        "net_margin_pct": round(net_income / revenue * 100, 2) if revenue and net_income is not None else None,
        "free_cash_flow": (
            operating_cash_flow - capital_expenditure
            if operating_cash_flow is not None and capital_expenditure is not None
            else None
        ),
    }
    first = rows[0]
    return {
        "end_date": first["end_date"],
        "start_date": first.get("start_date"),
        "fiscal_year": first.get("fiscal_year"),
        "fiscal_period": first.get("fiscal_period"),
        "period_kind": first["period_kind"],
        "metrics": metrics,
        "derived": derived,
    }


def get_sec_financial_summary(*, symbol: str, annual_limit: int = 5, quarterly_limit: int = 8) -> dict[str, Any]:
    normalized_symbol = normalize_us_symbol(symbol)
    with _write_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select * from (
                  select distinct on (metric, period_kind, coalesce(start_date, end_date), end_date)
                    metric, metric_label, taxonomy, concept, concept_priority, unit, value,
                    start_date, end_date, period_kind, fiscal_year, fiscal_period, form,
                    filed_date, accession_number, frame, source_url
                  from research_financial_facts
                  where symbol = %s
                    and period_kind in ('annual', 'quarter', 'instant')
                  order by metric, period_kind, coalesce(start_date, end_date), end_date,
                           concept_priority asc, filed_date desc
                ) canonical
                order by end_date desc, metric
                """,
                [normalized_symbol],
            )
            rows = [dict(row) for row in cur.fetchall()]
            cur.execute(
                "select * from research_financial_sync_status where symbol = %s",
                [normalized_symbol],
            )
            status_row = cur.fetchone()

    grouped: dict[tuple[str, date, date | None], list[dict[str, Any]]] = {}
    for row in rows:
        key = (str(row["period_kind"]), row["end_date"], row.get("start_date"))
        grouped.setdefault(key, []).append(row)
    annual = sorted(
        (_period_record(items) for (kind, _, _), items in grouped.items() if kind == "annual"),
        key=lambda item: item["end_date"],
        reverse=True,
    )[: max(1, min(int(annual_limit), 10))]
    quarterly = sorted(
        (_period_record(items) for (kind, _, _), items in grouped.items() if kind == "quarter"),
        key=lambda item: item["end_date"],
        reverse=True,
    )[: max(1, min(int(quarterly_limit), 16))]
    instants = sorted(
        (_period_record(items) for (kind, _, _), items in grouped.items() if kind == "instant"),
        key=lambda item: item["end_date"],
        reverse=True,
    )

    latest_annual = annual[0] if annual else None
    previous_annual = annual[1] if len(annual) > 1 else None
    annual_changes: dict[str, float | None] = {}
    if latest_annual:
        for metric, fact in latest_annual["metrics"].items():
            annual_changes[metric] = _change_pct(
                fact.get("value"),
                previous_annual["metrics"].get(metric, {}).get("value") if previous_annual else None,
            )
        for metric, value in latest_annual["derived"].items():
            prior = previous_annual["derived"].get(metric) if previous_annual else None
            annual_changes[metric] = (
                round(value - prior, 2) if metric.endswith("_margin_pct") and value is not None and prior is not None
                else _change_pct(value, prior)
            )

    latest_quarter = quarterly[0] if quarterly else None
    comparable_quarter = None
    if latest_quarter:
        comparable_quarter = next(
            (
                item for item in quarterly[1:]
                if 330 <= (latest_quarter["end_date"] - item["end_date"]).days <= 400
            ),
            None,
        )
    quarterly_yoy_changes: dict[str, float | None] = {}
    if latest_quarter:
        for metric, fact in latest_quarter["metrics"].items():
            quarterly_yoy_changes[metric] = _change_pct(
                fact.get("value"),
                comparable_quarter["metrics"].get(metric, {}).get("value") if comparable_quarter else None,
            )

    evidence: list[dict[str, Any]] = []
    if latest_annual:
        for metric in ("revenue", "net_income", "eps_diluted", "operating_cash_flow", "assets", "liabilities"):
            fact = latest_annual["metrics"].get(metric)
            if not fact:
                continue
            evidence.append({
                "id": f"sec-xbrl-{metric}-{latest_annual['end_date']}",
                "claim": (
                    f"{fact['label']}: {fact['value']} {fact['unit']} for the annual period ended "
                    f"{latest_annual['end_date']}; change versus the previous annual period: "
                    f"{annual_changes.get(metric)}%."
                ),
                "source": "SEC XBRL Company Facts",
                "locator": fact["locator"],
                "as_of": fact["filed_date"],
                "source_url": fact["source_url"],
            })
    if latest_quarter:
        for metric in ("revenue", "operating_income", "net_income", "eps_diluted"):
            fact = latest_quarter["metrics"].get(metric)
            if not fact:
                continue
            evidence.append({
                "id": f"sec-xbrl-{metric}-{latest_quarter['end_date']}",
                "claim": (
                    f"{fact['label']}: {fact['value']} {fact['unit']} for the quarter ended "
                    f"{latest_quarter['end_date']}; year-over-year change: "
                    f"{quarterly_yoy_changes.get(metric)}%."
                ),
                "source": "SEC XBRL Company Facts",
                "locator": fact["locator"],
                "as_of": fact["filed_date"],
                "source_url": fact["source_url"],
            })
    status = dict(status_row) if status_row else None
    return {
        "symbol": normalized_symbol,
        "status": status,
        "coverage": {
            "fact_rows": len(rows),
            "annual_periods": len(annual),
            "quarterly_periods": len(quarterly),
            "latest_end_date": rows[0]["end_date"] if rows else None,
        },
        "latest_annual": latest_annual,
        "previous_annual": previous_annual,
        "annual_changes": annual_changes,
        "latest_quarter": latest_quarter,
        "comparable_quarter": comparable_quarter,
        "quarterly_yoy_changes": quarterly_yoy_changes,
        "annual_series": annual,
        "quarterly_series": quarterly,
        "latest_balance_sheet": instants[0] if instants else None,
        "evidence": evidence,
    }
