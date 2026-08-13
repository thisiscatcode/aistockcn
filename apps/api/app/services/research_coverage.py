from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Iterable
from uuid import uuid4

from app.services.research_documents import _write_connection
from app.services.research_financials import sync_sec_companyfacts
from app.services.research_filing_changes import create_filing_change_run
from app.services.research_sec import _ticker_cik_map, sync_sec_filings


FAMOUS_US_SYMBOLS = (
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "GOOG", "META", "TSLA", "AVGO", "JPM",
    "WMT", "LLY", "V", "MA", "XOM", "COST", "UNH", "NFLX", "ORCL", "AMD", "CRM",
    "ADBE", "QCOM", "CSCO", "IBM", "INTC", "MU", "AMAT", "TXN", "PLTR", "COIN", "HOOD",
    "UBER", "ABNB", "DIS", "NKE", "MCD", "KO", "PEP", "HD", "LOW", "CAT", "BA", "GE",
    "GM", "F", "GS", "MS", "BAC", "WFC", "C", "PFE", "MRK", "JNJ", "ABBV", "TMO",
    "DHR", "GILD", "AMGN", "ISRG", "PANW", "CRWD", "SNOW", "NOW", "SHOP", "TSM", "BABA",
    "NVO", "SAP", "TM",
)


def merge_priority_candidates(
    *,
    favorites: Iterable[str],
    famous: Iterable[str],
    selections: Iterable[str],
    active: Iterable[str],
    eligible: set[str],
    issuer_keys: dict[str, str] | None = None,
    limit: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Merge stable priority lanes while preserving every reason for each selected symbol."""
    lanes = (
        ("fei_favorite", favorites),
        ("famous", famous),
        ("current_selection", selections),
        ("active_liquidity", active),
    )
    reasons: dict[str, list[str]] = {}
    ordered: list[str] = []
    ineligible_favorites: list[str] = []
    for reason, symbols in lanes:
        for raw_symbol in symbols:
            symbol = str(raw_symbol or "").strip().upper()
            if not symbol:
                continue
            if symbol not in eligible:
                if reason == "fei_favorite" and symbol not in ineligible_favorites:
                    ineligible_favorites.append(symbol)
                continue
            if symbol not in reasons:
                reasons[symbol] = []
                ordered.append(symbol)
            if reason not in reasons[symbol]:
                reasons[symbol].append(reason)
    safe_limit = max(1, min(int(limit), 1000))
    rows: list[dict[str, Any]] = []
    seen_issuers: set[str] = set()
    for symbol in ordered:
        issuer_key = (issuer_keys or {}).get(symbol, symbol)
        if issuer_key in seen_issuers:
            continue
        seen_issuers.add(issuer_key)
        rows.append({
            "symbol": symbol,
            "priority_rank": len(rows) + 1,
            "priority_reasons": reasons[symbol],
            "is_fei_favorite": "fei_favorite" in reasons[symbol],
            "issuer_key": issuer_key,
        })
        if len(rows) >= safe_limit:
            break
    return rows, ineligible_favorites


def _priority_sources() -> dict[str, list[str]]:
    with _write_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select f.symbol
                from us_stock_favorite_stocks f
                join us_stock_master m on m.symbol = f.symbol
                where m.is_active = true and m.del_flg = false
                order by f.display_num nulls last, f.symbol
                """
            )
            favorites = [str(row["symbol"]) for row in cur.fetchall()]

            cur.execute(
                """
                with latest as (select max(trade_date) as trade_date from us_selection_daily_snapshots)
                select code, min(rank) as best_rank
                from us_selection_daily_snapshots s join latest l using (trade_date)
                group by code order by best_rank, code
                """
            )
            selections = [str(row["code"]) for row in cur.fetchall()]

            cur.execute(
                """
                with dates as (
                  select distinct trade_date from us_stock_daily_metrics
                  order by trade_date desc limit 20
                )
                select d.symbol, avg(d.close * d.volume) as average_dollar_volume
                from us_stock_daily_metrics d
                join dates using (trade_date)
                join us_stock_master m on m.symbol = d.symbol
                where m.is_active = true and m.del_flg = false
                  and m.stock_type in ('Common Stock', 'ADR', 'REIT')
                  and d.close > 0 and d.volume > 0
                group by d.symbol
                order by average_dollar_volume desc nulls last
                limit 1000
                """
            )
            active = [str(row["symbol"]) for row in cur.fetchall()]

            cur.execute(
                """
                select symbol from us_stock_master
                where is_active = true and del_flg = false and symbol = any(%s)
                """,
                [list(FAMOUS_US_SYMBOLS)],
            )
            active_famous = {str(row["symbol"]) for row in cur.fetchall()}
    return {
        "favorites": favorites,
        "famous": [symbol for symbol in FAMOUS_US_SYMBOLS if symbol in active_famous],
        "selections": selections,
        "active": active,
    }


def seed_core_company_coverage(*, limit: int = 100, requested_by: str = "coverage-bootstrap") -> dict[str, Any]:
    sources = _priority_sources()
    cik_map = _ticker_cik_map()
    eligible = set(cik_map)
    companies, ineligible_favorites = merge_priority_candidates(
        favorites=sources["favorites"],
        famous=sources["famous"],
        selections=sources["selections"],
        active=sources["active"],
        eligible=eligible,
        issuer_keys=cik_map,
        limit=limit,
    )
    if len(companies) < limit:
        raise RuntimeError("coverage_candidate_shortfall")
    queued = 0
    with _write_connection() as conn:
        with conn.cursor() as cur:
            for company in companies:
                cur.execute(
                    """
                    insert into research_company_coverage (
                      symbol, sec_cik, priority_rank, priority_reasons, is_fei_favorite, status
                    ) values (%s, %s, %s, %s::jsonb, %s, 'queued')
                    on conflict (symbol) do update set
                      sec_cik = excluded.sec_cik,
                      priority_rank = excluded.priority_rank,
                      priority_reasons = excluded.priority_reasons,
                      is_fei_favorite = excluded.is_fei_favorite,
                      status = research_company_coverage.status,
                      updated_at = now()
                    """,
                    [
                        company["symbol"], company["issuer_key"], company["priority_rank"],
                        json.dumps(company["priority_reasons"]), company["is_fei_favorite"],
                    ],
                )
                cur.execute(
                    """
                    insert into research_coverage_jobs (
                      id, symbol, status, priority_rank, requested_by
                    )
                    select %s, %s, 'queued', %s, %s
                    where not exists (
                      select 1 from research_coverage_jobs
                      where symbol = %s
                    )
                    on conflict do nothing
                    returning id
                    """,
                    [
                        str(uuid4()), company["symbol"], company["priority_rank"],
                        requested_by[:120], company["symbol"],
                    ],
                )
                queued += int(cur.fetchone() is not None)
        conn.commit()
    return {
        "target": limit,
        "selected": len(companies),
        "queued": queued,
        "fei_favorites_selected": sum(1 for row in companies if row["is_fei_favorite"]),
        "fei_favorites_without_sec_cik": ineligible_favorites,
        "companies": companies,
    }


def claim_next_coverage_job() -> str | None:
    with _write_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select id from research_coverage_jobs
                where (
                    status = 'queued'
                    or (
                      status = 'failed' and attempt_count < max_attempts
                      and coalesce(next_retry_at, now()) <= now()
                    )
                    or (status = 'running' and updated_at < now() - interval '1 hour')
                )
                order by priority_rank, created_at
                for update skip locked limit 1
                """
            )
            row = cur.fetchone()
            if not row:
                conn.rollback()
                return None
            job_id = str(row["id"])
            cur.execute(
                """
                update research_coverage_jobs
                set status = 'running', attempt_count = attempt_count + 1,
                    started_at = coalesce(started_at, now()), next_retry_at = null,
                    last_error_code = null, last_error_message = null, updated_at = now()
                where id = %s
                """,
                [job_id],
            )
            cur.execute(
                """
                update research_company_coverage c
                set status = 'syncing', last_sync_started_at = now(),
                    last_error_code = null, last_error_message = null, updated_at = now()
                from research_coverage_jobs j where j.id = %s and c.symbol = j.symbol
                """,
                [job_id],
            )
        conn.commit()
    return job_id


def _job(job_id: str) -> dict[str, Any]:
    with _write_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("select * from research_coverage_jobs where id = %s", [job_id])
            row = cur.fetchone()
    if not row:
        raise RuntimeError("coverage_job_not_found")
    return dict(row)


def _coverage_counts(cur: Any, symbol: str) -> dict[str, int]:
    cur.execute(
        """
        select
          count(*) filter (where document_type = 'annual_report' and status = 'indexed')::integer annual_indexed,
          count(*) filter (where document_type in ('quarterly_report', 'current_report') and status = 'indexed')::integer recent_indexed,
          count(*) filter (where status in ('uploaded', 'processing'))::integer pending_documents,
          count(*) filter (where status = 'failed')::integer failed_documents
        from research_documents where symbol = %s
        """,
        [symbol],
    )
    result = dict(cur.fetchone())
    cur.execute("select count(*)::integer as count from research_financial_facts where symbol = %s", [symbol])
    result["xbrl_fact_count"] = int(cur.fetchone()["count"])
    return {key: int(value or 0) for key, value in result.items()}


def process_coverage_job(job_id: str) -> dict[str, Any]:
    job = _job(job_id)
    symbol = str(job["symbol"])
    errors: list[str] = []
    try:
        annual = sync_sec_filings(
            symbol=symbol,
            forms=["10-K", "20-F", "40-F"],
            limit_per_form=2,
        )
        errors.extend(str(item.get("code")) for item in annual.get("errors", []) if item.get("code"))
        recent = sync_sec_filings(
            symbol=symbol,
            forms=["10-Q", "6-K"],
            limit_per_form=1,
        )
        errors.extend(str(item.get("code")) for item in recent.get("errors", []) if item.get("code"))
        try:
            sync_sec_companyfacts(symbol=symbol)
        except Exception as exc:
            errors.append(str(exc))

        with _write_connection() as conn:
            with conn.cursor() as cur:
                counts = _coverage_counts(cur, symbol)
                cur.execute(
                    """
                    update research_coverage_jobs
                    set status = 'waiting_index', last_error_code = %s,
                        last_error_message = %s, updated_at = now()
                    where id = %s
                    """,
                    [errors[0][:120] if errors else None, "; ".join(errors)[:1000] or None, job_id],
                )
                cur.execute(
                    """
                    update research_company_coverage
                    set status = 'indexing', annual_indexed = %s, recent_indexed = %s,
                        xbrl_fact_count = %s, last_error_code = %s,
                        last_error_message = %s, updated_at = now()
                    where symbol = %s
                    """,
                    [
                        counts["annual_indexed"], counts["recent_indexed"], counts["xbrl_fact_count"],
                        errors[0][:120] if errors else None, "; ".join(errors)[:1000] or None, symbol,
                    ],
                )
            conn.commit()
        return {"job_id": job_id, "symbol": symbol, "status": "waiting_index", **counts, "errors": errors}
    except Exception as exc:
        code = str(exc)[:120] or "coverage_sync_failed"
        unsupported = code == "sec_cik_not_found"
        attempt_count = int(job.get("attempt_count") or 1)
        with _write_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    update research_coverage_jobs
                    set status = %s, last_error_code = %s, last_error_message = %s,
                        next_retry_at = case when %s then null else now() + (%s * interval '5 minutes') end,
                        completed_at = case when %s then now() else completed_at end,
                        updated_at = now()
                    where id = %s
                    """,
                    [
                        "unsupported" if unsupported else "failed", code, str(exc)[:1000],
                        unsupported, max(1, 2 ** (attempt_count - 1)), unsupported, job_id,
                    ],
                )
                cur.execute(
                    """
                    update research_company_coverage
                    set status = %s, last_error_code = %s, last_error_message = %s, updated_at = now()
                    where symbol = %s
                    """,
                    ["unsupported" if unsupported else "failed", code, str(exc)[:1000], symbol],
                )
            conn.commit()
        return {"job_id": job_id, "symbol": symbol, "status": "unsupported" if unsupported else "failed", "error": code}


def _ensure_change_detection(symbol: str) -> str | None:
    with _write_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select id from research_documents
                where symbol = %s and document_type = 'annual_report' and status = 'indexed'
                order by filing_date desc nulls last, fiscal_year desc nulls last limit 2
                """,
                [symbol],
            )
            documents = [str(row["id"]) for row in cur.fetchall()]
            if len(documents) < 2:
                return None
            newer_id, older_id = documents
            cur.execute(
                """
                select id from research_filing_change_runs
                where older_document_id = %s and newer_document_id = %s
                  and status in ('queued', 'running', 'completed')
                order by created_at desc limit 1
                """,
                [older_id, newer_id],
            )
            existing = cur.fetchone()
    if existing:
        return str(existing["id"])
    run = create_filing_change_run(
        symbol=symbol,
        older_document_id=older_id,
        newer_document_id=newer_id,
        requested_by="coverage-worker",
        parameters={"max_changes": 24},
    )
    return str(run["id"])


def reconcile_coverage_jobs(*, limit: int = 300) -> dict[str, int]:
    with _write_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select j.id, j.symbol, c.target_annual_reports, c.target_recent_reports
                from research_coverage_jobs j
                join research_company_coverage c using (symbol)
                where j.status = 'waiting_index'
                order by j.priority_rank limit %s
                """,
                [max(1, min(int(limit), 1000))],
            )
            jobs = [dict(row) for row in cur.fetchall()]
    summary = {"ready": 0, "indexing": 0, "partial": 0}
    ready_symbols: list[str] = []
    for job in jobs:
        with _write_connection() as conn:
            with conn.cursor() as cur:
                counts = _coverage_counts(cur, str(job["symbol"]))
                ready = (
                    counts["annual_indexed"] >= int(job["target_annual_reports"])
                    and counts["recent_indexed"] >= int(job["target_recent_reports"])
                    and counts["xbrl_fact_count"] > 0
                )
                if ready:
                    job_status, coverage_status = "completed", "ready"
                    ready_symbols.append(str(job["symbol"]))
                elif counts["pending_documents"] > 0:
                    job_status, coverage_status = "waiting_index", "indexing"
                else:
                    job_status, coverage_status = "partial", "partial"
                cur.execute(
                    """
                    update research_company_coverage
                    set status = %s, annual_indexed = %s, recent_indexed = %s,
                        xbrl_fact_count = %s,
                        last_sync_completed_at = case when %s <> 'indexing' then now() else last_sync_completed_at end,
                        updated_at = now()
                    where symbol = %s
                    """,
                    [
                        coverage_status, counts["annual_indexed"], counts["recent_indexed"],
                        counts["xbrl_fact_count"], coverage_status, job["symbol"],
                    ],
                )
                cur.execute(
                    """
                    update research_coverage_jobs
                    set status = %s,
                        completed_at = case when %s <> 'waiting_index' then now() else completed_at end,
                        updated_at = now()
                    where id = %s
                    """,
                    [job_status, job_status, job["id"]],
                )
            conn.commit()
        summary[coverage_status] += 1
    for symbol in ready_symbols:
        try:
            _ensure_change_detection(symbol)
        except Exception:
            continue
    return summary


def get_coverage_summary(*, limit: int = 100) -> dict[str, Any]:
    safe_limit = max(1, min(int(limit), 1000))
    with _write_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("select count(*)::integer as count from research_company_coverage")
            target = int(cur.fetchone()["count"])
            cur.execute(
                """
                select status, count(*)::integer as count
                from research_company_coverage group by status order by status
                """
            )
            status_counts = {str(row["status"]): int(row["count"]) for row in cur.fetchall()}
            cur.execute(
                """
                select c.*, m.stock_name, m.market,
                       j.status as job_status, j.attempt_count, j.last_error_code as job_error_code
                from research_company_coverage c
                join us_stock_master m using (symbol)
                left join lateral (
                  select status, attempt_count, last_error_code
                  from research_coverage_jobs where symbol = c.symbol
                  order by created_at desc limit 1
                ) j on true
                order by c.priority_rank limit %s
                """,
                [safe_limit],
            )
            companies = [dict(row) for row in cur.fetchall()]
            cur.execute(
                """
                select count(*)::integer queued_documents
                from research_documents where status in ('uploaded', 'processing')
                """
            )
            queued_documents = int(cur.fetchone()["queued_documents"])
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "target": target,
        "status_counts": status_counts,
        "queued_documents": queued_documents,
        "companies": companies,
    }
