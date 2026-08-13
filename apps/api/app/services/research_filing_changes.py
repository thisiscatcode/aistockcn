from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import Any
from uuid import uuid4

from app.services.research import ResearchError, normalize_us_symbol
from app.services.research_documents import _write_connection


ALGORITHM_VERSION = "filing-change-v1.1"
DEFAULT_PARAMETERS: dict[str, Any] = {
    "added_deleted_similarity_max": 0.62,
    "unchanged_similarity_min": 0.985,
    "minimum_characters": 160,
    "minimum_materiality": 0.42,
    "max_changes": 24,
    "evidence_characters": 1400,
}

TOPIC_TERMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Cybersecurity and data", ("cyber", "data breach", "information security", "privacy")),
    ("Regulation and legal", ("regulat", "litigation", "legal proceeding", "compliance", "government")),
    ("Competition", ("compet", "market share", "pricing pressure")),
    ("Supply chain", ("supply chain", "supplier", "manufactur", "inventory", "shortage")),
    ("Demand and revenue", ("revenue", "sales", "demand", "customer", "commercial")),
    ("Profitability and costs", ("profit", "margin", "expense", "cost", "impairment")),
    ("Liquidity and capital", ("liquidity", "cash flow", "capital", "debt", "credit")),
    ("Macroeconomic exposure", ("inflation", "interest rate", "foreign exchange", "recession", "macroeconomic")),
    ("Management outlook", ("management", "expect", "outlook", "strategy", "priority", "forecast")),
    ("Operations and controls", ("internal control", "material weakness", "operation", "personnel", "employee")),
    ("Climate and environment", ("climate", "environment", "carbon", "weather")),
    ("General risk disclosure", ("risk", "uncertain", "adverse", "material effect", "threat")),
)

STRONG_LANGUAGE = (
    "material adverse", "significant", "substantial", "severe", "critical", "heightened",
    "increasingly", "material weakness", "likely", "unable", "adversely affect", "will",
)
HEDGED_LANGUAGE = (
    "may", "might", "could", "potential", "possible", "generally", "from time to time",
    "not expected", "unlikely",
)


class FilingChangeError(ResearchError):
    pass


def _json_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _topic(text: str) -> tuple[str, float]:
    lowered = text.lower()
    best_topic = "Other material disclosure"
    best_hits = 0
    for topic, terms in TOPIC_TERMS:
        hits = sum(lowered.count(term) for term in terms)
        if hits > best_hits:
            best_topic = topic
            best_hits = hits
    return best_topic, min(1.0, 0.24 + best_hits * 0.16)


def _language_strength(text: str) -> float:
    lowered = text.lower()
    words = max(1, len(lowered.split()))
    strong = sum(lowered.count(term) for term in STRONG_LANGUAGE)
    hedged = sum(lowered.count(term) for term in HEDGED_LANGUAGE)
    numeric = len(re.findall(r"(?:\$|\b)\d+(?:\.\d+)?%?", lowered))
    return round(((strong * 1.35) - (hedged * 0.45) + min(numeric, 4) * 0.12) * 200 / words, 4)


def _change_type(*, similarity: float, older_text: str, newer_text: str, direction: str) -> str:
    if similarity <= float(DEFAULT_PARAMETERS["added_deleted_similarity_max"]):
        return "added" if direction == "newer_to_older" else "deleted"
    strength_delta = _language_strength(newer_text) - _language_strength(older_text)
    if strength_delta >= 0.8:
        return "strengthened"
    if strength_delta <= -0.8:
        return "weakened"
    return "rewritten"


def _materiality(*, similarity: float, older_text: str, newer_text: str, topic_relevance: float) -> float:
    divergence = max(0.0, min(1.0, 1.0 - similarity))
    strength_delta = abs(_language_strength(newer_text) - _language_strength(older_text))
    number_delta = 1.0 if re.findall(r"\d+(?:\.\d+)?%?", older_text) != re.findall(r"\d+(?:\.\d+)?%?", newer_text) else 0.0
    score = 0.16 + divergence * 0.48 + topic_relevance * 0.25 + min(strength_delta / 5, 1) * 0.08 + number_delta * 0.03
    return round(max(0.0, min(1.0, score)), 4)


def _evidence(row: dict[str, Any], prefix: str, *, max_characters: int) -> dict[str, Any]:
    page_number = row.get(f"{prefix}_page_number")
    locator = row.get(f"{prefix}_locator") or (
        f"page {page_number}" if page_number else "source passage"
    )
    content = _clean_text(row.get(f"{prefix}_content"))
    return {
        "chunk_id": row.get(f"{prefix}_chunk_id"),
        "document_id": row.get(f"{prefix}_document_id"),
        "filename": row.get(f"{prefix}_filename"),
        "document_type": row.get(f"{prefix}_document_type"),
        "filing_date": _json_value(row.get(f"{prefix}_filing_date")),
        "fiscal_year": row.get(f"{prefix}_fiscal_year"),
        "page_number": page_number if row.get(f"{prefix}_native_page_numbers") else None,
        "locator_type": row.get(f"{prefix}_locator_type") or "page",
        "locator": locator,
        "source_url": row.get(f"{prefix}_source_url"),
        "quote": content[:max_characters],
    }


def _summary(change_type: str, topic: str) -> str:
    labels = {
        "added": "The newer filing introduces materially different disclosure.",
        "deleted": "Disclosure in the older filing is no longer stated comparably in the newer filing.",
        "strengthened": "The newer filing uses stronger or more definite language.",
        "weakened": "The newer filing softens or qualifies the earlier language.",
        "rewritten": "The disclosure is materially rewritten while retaining a related topic.",
    }
    return f"{topic}: {labels[change_type]}"


def _candidate_from_pair(row: dict[str, Any], *, direction: str, parameters: dict[str, Any]) -> dict[str, Any] | None:
    older_text = _clean_text(row.get("older_content"))
    newer_text = _clean_text(row.get("newer_content"))
    if min(len(older_text), len(newer_text)) < int(parameters["minimum_characters"]):
        return None
    similarity = max(0.0, min(1.0, float(row.get("similarity_score") or 0.0)))
    if similarity >= float(parameters["unchanged_similarity_min"]):
        return None
    combined = f"{older_text} {newer_text}"
    topic, relevance = _topic(combined)
    if topic == "Other material disclosure":
        return None
    change_type = _change_type(
        similarity=similarity,
        older_text=older_text,
        newer_text=newer_text,
        direction=direction,
    )
    materiality = _materiality(
        similarity=similarity,
        older_text=older_text,
        newer_text=newer_text,
        topic_relevance=relevance,
    )
    if materiality < float(parameters["minimum_materiality"]):
        return None
    old_strength = _language_strength(older_text)
    new_strength = _language_strength(newer_text)
    return {
        "change_type": change_type,
        "topic": topic,
        "materiality_score": materiality,
        "similarity_score": round(similarity, 4),
        "summary": _summary(change_type, topic),
        "rationale": (
            f"Deterministic {ALGORITHM_VERSION}: semantic similarity {similarity:.3f}; "
            f"language-strength score changed from {old_strength:.2f} to {new_strength:.2f}. "
            "The result remains pending until a person confirms or rejects it."
        ),
        "older_chunk_id": row.get("older_chunk_id"),
        "newer_chunk_id": row.get("newer_chunk_id"),
        "older_evidence": _evidence(row, "older", max_characters=int(parameters["evidence_characters"])),
        "newer_evidence": _evidence(row, "newer", max_characters=int(parameters["evidence_characters"])),
    }


def build_change_candidates(
    pairs: list[tuple[dict[str, Any], str]],
    *,
    parameters: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Build reproducible candidates from reciprocal nearest-neighbour chunk pairs."""
    resolved = {**DEFAULT_PARAMETERS, **(parameters or {})}
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for row, direction in pairs:
        candidate = _candidate_from_pair(row, direction=direction, parameters=resolved)
        if not candidate:
            continue
        identity = (
            str(candidate["older_chunk_id"]),
            str(candidate["newer_chunk_id"]),
            str(candidate["change_type"]),
        )
        if identity in seen:
            continue
        seen.add(identity)
        candidates.append(candidate)
    candidates.sort(
        key=lambda item: (
            float(item["materiality_score"]),
            1.0 - float(item["similarity_score"]),
            str(item["topic"]),
        ),
        reverse=True,
    )
    limit = max(1, min(int(resolved["max_changes"]), 100))
    selected: list[dict[str, Any]] = []
    used_older: set[tuple[str, str]] = set()
    used_newer: set[tuple[str, str]] = set()
    for candidate in candidates:
        change_type = str(candidate["change_type"])
        older_key = (change_type, str(candidate["older_chunk_id"]))
        newer_key = (change_type, str(candidate["newer_chunk_id"]))
        if older_key in used_older or newer_key in used_newer:
            continue
        selected.append(candidate)
        used_older.add(older_key)
        used_newer.add(newer_key)
        if len(selected) >= limit:
            break
    return selected


def _document_pair(cur: Any, older_document_id: str, newer_document_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    cur.execute(
        """
        select id, symbol, filename, document_type, filing_date, fiscal_year, source_url, sha256,
               source_format, native_page_numbers, status, chunk_count
        from research_documents where id in (%s, %s)
        """,
        [older_document_id, newer_document_id],
    )
    rows = {str(row["id"]): dict(row) for row in cur.fetchall()}
    if older_document_id not in rows or newer_document_id not in rows:
        raise FilingChangeError("filing_change_document_not_found")
    older, newer = rows[older_document_id], rows[newer_document_id]
    if older["symbol"] != newer["symbol"]:
        raise FilingChangeError("filing_change_symbol_mismatch")
    if older["document_type"] != "annual_report" or newer["document_type"] != "annual_report":
        raise FilingChangeError("filing_change_annual_reports_required")
    if older["status"] != "indexed" or newer["status"] != "indexed":
        raise FilingChangeError("filing_change_documents_not_ready")
    older_date = older.get("filing_date")
    newer_date = newer.get("filing_date")
    if older_date and newer_date and older_date >= newer_date:
        raise FilingChangeError("filing_change_period_order_invalid")
    if not (older_date and newer_date):
        older_year = older.get("fiscal_year")
        newer_year = newer.get("fiscal_year")
        if older_year and newer_year and int(older_year) >= int(newer_year):
            raise FilingChangeError("filing_change_period_order_invalid")
    return older, newer


def create_filing_change_run(
    *,
    symbol: str,
    older_document_id: str,
    newer_document_id: str,
    requested_by: str | None,
    parameters: dict[str, Any] | None = None,
    retry_of_run_id: str | None = None,
) -> dict[str, Any]:
    normalized_symbol = normalize_us_symbol(symbol)
    if older_document_id == newer_document_id:
        raise FilingChangeError("filing_change_documents_must_differ")
    resolved = {**DEFAULT_PARAMETERS, **(parameters or {})}
    resolved["max_changes"] = max(1, min(int(resolved["max_changes"]), 100))
    run_id = str(uuid4())
    with _write_connection() as conn:
        with conn.cursor() as cur:
            older, newer = _document_pair(cur, older_document_id, newer_document_id)
            if str(older["symbol"]) != normalized_symbol:
                raise FilingChangeError("filing_change_symbol_mismatch")
            cur.execute(
                """
                select array_remove(array_agg(distinct embedding_model), null) as models
                from research_document_chunks where document_id in (%s, %s)
                """,
                [older_document_id, newer_document_id],
            )
            model_row = cur.fetchone()
            resolved.update({
                "older_document_sha256": str(older["sha256"]),
                "newer_document_sha256": str(newer["sha256"]),
                "embedding_models": list(model_row["models"] or []),
            })
            if retry_of_run_id:
                cur.execute("select id from research_filing_change_runs where id = %s", [retry_of_run_id])
                if not cur.fetchone():
                    raise FilingChangeError("filing_change_run_not_found")
            cur.execute(
                """
                insert into research_filing_change_runs (
                  id, symbol, older_document_id, newer_document_id, status,
                  algorithm_version, parameters, requested_by, retry_of_run_id
                ) values (%s, %s, %s, %s, 'queued', %s, %s::jsonb, %s, %s)
                returning *
                """,
                [
                    run_id, normalized_symbol, older_document_id, newer_document_id,
                    ALGORITHM_VERSION, json.dumps(resolved), (requested_by or "").strip()[:120] or None,
                    retry_of_run_id,
                ],
            )
            result = dict(cur.fetchone())
        conn.commit()
    return result


def _pair_rows(cur: Any, older_document_id: str, newer_document_id: str) -> list[tuple[dict[str, Any], str]]:
    fields = """
      o.id as older_chunk_id, o.document_id as older_document_id,
      o.page_number as older_page_number, o.locator_type as older_locator_type,
      o.locator as older_locator, o.content as older_content,
      od.filename as older_filename, od.document_type as older_document_type,
      od.filing_date as older_filing_date, od.fiscal_year as older_fiscal_year,
      od.source_url as older_source_url, od.native_page_numbers as older_native_page_numbers,
      n.id as newer_chunk_id, n.document_id as newer_document_id,
      n.page_number as newer_page_number, n.locator_type as newer_locator_type,
      n.locator as newer_locator, n.content as newer_content,
      nd.filename as newer_filename, nd.document_type as newer_document_type,
      nd.filing_date as newer_filing_date, nd.fiscal_year as newer_fiscal_year,
      nd.source_url as newer_source_url, nd.native_page_numbers as newer_native_page_numbers,
      greatest(0.0, 1.0 - (n.embedding <=> o.embedding)) as similarity_score
    """
    cur.execute(
        f"""
        select {fields}
        from research_document_chunks o
        join research_documents od on od.id = o.document_id
        cross join lateral (
          select candidate.*
          from research_document_chunks candidate
          where candidate.document_id = %s and candidate.embedding is not null
          order by candidate.embedding <=> o.embedding
          limit 1
        ) n
        join research_documents nd on nd.id = n.document_id
        where o.document_id = %s and o.embedding is not null
        """,
        [newer_document_id, older_document_id],
    )
    forward = [(dict(row), "older_to_newer") for row in cur.fetchall()]
    cur.execute(
        f"""
        select {fields}
        from research_document_chunks n
        join research_documents nd on nd.id = n.document_id
        cross join lateral (
          select candidate.*
          from research_document_chunks candidate
          where candidate.document_id = %s and candidate.embedding is not null
          order by candidate.embedding <=> n.embedding
          limit 1
        ) o
        join research_documents od on od.id = o.document_id
        where n.document_id = %s and n.embedding is not null
        """,
        [older_document_id, newer_document_id],
    )
    return forward + [(dict(row), "newer_to_older") for row in cur.fetchall()]


def run_filing_change_detection(run_id: str) -> dict[str, Any]:
    with _write_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("select * from research_filing_change_runs where id = %s for update", [run_id])
            row = cur.fetchone()
            if not row:
                raise FilingChangeError("filing_change_run_not_found")
            run = dict(row)
            if run["status"] == "completed":
                return get_filing_change_run(run_id)
            cur.execute(
                """
                update research_filing_change_runs
                set status = 'running', started_at = coalesce(started_at, now()),
                    completed_at = null, error_code = null, error_message = null, updated_at = now()
                where id = %s
                """,
                [run_id],
            )
        conn.commit()

    try:
        with _write_connection() as conn:
            with conn.cursor() as cur:
                _document_pair(cur, str(run["older_document_id"]), str(run["newer_document_id"]))
                pairs = _pair_rows(cur, str(run["older_document_id"]), str(run["newer_document_id"]))
        if not pairs:
            raise FilingChangeError("filing_change_no_comparable_chunks")
        parameters = dict(run.get("parameters") or DEFAULT_PARAMETERS)
        candidates = build_change_candidates(pairs, parameters=parameters)
        with _write_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("delete from research_filing_changes where run_id = %s", [run_id])
                for sequence, candidate in enumerate(candidates, start=1):
                    cur.execute(
                        """
                        insert into research_filing_changes (
                          id, run_id, sequence, change_type, topic, materiality_score,
                          similarity_score, summary, rationale, older_chunk_id, newer_chunk_id,
                          older_evidence, newer_evidence
                        ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)
                        """,
                        [
                            str(uuid4()), run_id, sequence, candidate["change_type"], candidate["topic"],
                            candidate["materiality_score"], candidate["similarity_score"],
                            candidate["summary"], candidate["rationale"], candidate["older_chunk_id"],
                            candidate["newer_chunk_id"], json.dumps(candidate["older_evidence"]),
                            json.dumps(candidate["newer_evidence"]),
                        ],
                    )
                cur.execute(
                    """
                    update research_filing_change_runs
                    set status = 'completed', result_count = %s, completed_at = now(), updated_at = now()
                    where id = %s
                    """,
                    [len(candidates), run_id],
                )
            conn.commit()
        return get_filing_change_run(run_id)
    except Exception as exc:
        code = str(exc) if isinstance(exc, FilingChangeError) else "filing_change_detection_failed"
        with _write_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    update research_filing_change_runs
                    set status = 'failed', error_code = %s, error_message = %s,
                        completed_at = now(), updated_at = now()
                    where id = %s
                    """,
                    [code[:120], str(exc)[:1000], run_id],
                )
            conn.commit()
        raise


def run_filing_change_detection_safely(run_id: str) -> None:
    try:
        run_filing_change_detection(run_id)
    except Exception:
        return


def claim_next_filing_change_run() -> str | None:
    with _write_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select id from research_filing_change_runs
                where status = 'queued'
                   or (status = 'running' and updated_at < now() - interval '30 minutes')
                order by created_at
                for update skip locked
                limit 1
                """
            )
            row = cur.fetchone()
            if not row:
                conn.rollback()
                return None
            run_id = str(row["id"])
            cur.execute(
                """
                update research_filing_change_runs
                set status = 'running', started_at = coalesce(started_at, now()), updated_at = now()
                where id = %s
                """,
                [run_id],
            )
        conn.commit()
    return run_id


def _run_select() -> str:
    return """
      select r.*,
             od.filename as older_filename, od.filing_date as older_filing_date,
             od.fiscal_year as older_fiscal_year, od.source_url as older_source_url,
             nd.filename as newer_filename, nd.filing_date as newer_filing_date,
             nd.fiscal_year as newer_fiscal_year, nd.source_url as newer_source_url,
             (select count(*) from research_filing_changes c
               where c.run_id = r.id and c.review_status <> 'pending') as reviewed_count
      from research_filing_change_runs r
      join research_documents od on od.id = r.older_document_id
      join research_documents nd on nd.id = r.newer_document_id
    """


def list_filing_change_runs(*, symbol: str, limit: int = 20) -> dict[str, Any]:
    normalized_symbol = normalize_us_symbol(symbol)
    safe_limit = max(1, min(int(limit), 100))
    with _write_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                _run_select() + " where r.symbol = %s order by r.created_at desc limit %s",
                [normalized_symbol, safe_limit],
            )
            runs = [dict(row) for row in cur.fetchall()]
    return {"symbol": normalized_symbol, "rows": len(runs), "runs": runs}


def get_filing_change_run(run_id: str) -> dict[str, Any]:
    with _write_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(_run_select() + " where r.id = %s", [run_id])
            row = cur.fetchone()
            if not row:
                raise FilingChangeError("filing_change_run_not_found")
            run = dict(row)
            cur.execute(
                """
                select c.*,
                       coalesce((
                         select jsonb_agg(jsonb_build_object(
                           'decision', v.decision, 'reviewer', v.reviewer,
                           'note', v.note, 'created_at', v.created_at
                         ) order by v.created_at)
                         from research_filing_change_reviews v where v.change_id = c.id
                       ), '[]'::jsonb) as review_history
                from research_filing_changes c
                where c.run_id = %s order by c.sequence
                """,
                [run_id],
            )
            changes = [dict(change) for change in cur.fetchall()]
    return {**run, "changes": changes}


def rerun_filing_change_detection(*, run_id: str, requested_by: str | None) -> dict[str, Any]:
    previous = get_filing_change_run(run_id)
    return create_filing_change_run(
        symbol=str(previous["symbol"]),
        older_document_id=str(previous["older_document_id"]),
        newer_document_id=str(previous["newer_document_id"]),
        requested_by=requested_by,
        parameters=dict(previous.get("parameters") or {}),
        retry_of_run_id=run_id,
    )


def review_filing_change(
    *,
    change_id: str,
    decision: str,
    reviewer: str,
    note: str | None,
) -> dict[str, Any]:
    normalized_decision = str(decision).strip().lower()
    if normalized_decision not in {"confirmed", "rejected", "needs_edit"}:
        raise FilingChangeError("filing_change_review_invalid")
    normalized_reviewer = _clean_text(reviewer)[:120]
    if not normalized_reviewer:
        raise FilingChangeError("filing_change_reviewer_required")
    normalized_note = _clean_text(note)[:2000] or None
    with _write_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("select id from research_filing_changes where id = %s", [change_id])
            if not cur.fetchone():
                raise FilingChangeError("filing_change_not_found")
            cur.execute(
                """
                insert into research_filing_change_reviews (id, change_id, decision, reviewer, note)
                values (%s, %s, %s, %s, %s)
                """,
                [str(uuid4()), change_id, normalized_decision, normalized_reviewer, normalized_note],
            )
            cur.execute(
                """
                update research_filing_changes
                set review_status = %s, reviewed_by = %s, reviewer_note = %s, reviewed_at = now()
                where id = %s returning *
                """,
                [normalized_decision, normalized_reviewer, normalized_note, change_id],
            )
            result = dict(cur.fetchone())
        conn.commit()
    return result
