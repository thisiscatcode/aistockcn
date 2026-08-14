from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import uuid4

from app.services.research_documents import _write_connection


def record_agent_run(
    *,
    run_type: str,
    symbols: list[str],
    question: str,
    status: str,
    duration_ms: float | None = None,
    evidence_count: int = 0,
    tool_plan: dict[str, Any] | None = None,
    trace: list[dict[str, Any]] | None = None,
    citation_metrics: dict[str, Any] | None = None,
    model: dict[str, Any] | None = None,
    graph_version: str | None = None,
    error_code: str | None = None,
) -> str | None:
    """Persist privacy-conscious usage telemetry without storing the question text."""
    question_hash = hashlib.sha256(question.strip().encode("utf-8")).hexdigest()
    run_id = str(uuid4())
    try:
        with _write_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    insert into research_agent_runs (
                      id, run_type, symbols, question_sha256, status, duration_ms,
                      evidence_count, tool_plan, trace, citation_metrics, model,
                      graph_version, error_code
                    ) values (
                      %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb,
                      %s::jsonb, %s::jsonb, %s, %s
                    )
                    """,
                    [
                        run_id, run_type, symbols, question_hash, status, duration_ms,
                        evidence_count, json.dumps(tool_plan) if tool_plan else None,
                        json.dumps(trace or []), json.dumps(citation_metrics or {}),
                        json.dumps(model or {}), graph_version, error_code,
                    ],
                )
            conn.commit()
        return run_id
    except Exception:
        # Telemetry must never break a user-facing research answer.
        return None


def get_agent_quality_summary(limit: int = 100) -> dict[str, Any]:
    safe_limit = max(10, min(int(limit), 500))
    with _write_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select id, run_type, symbols, status, duration_ms, evidence_count,
                       citation_metrics, model, graph_version, error_code, created_at
                from research_agent_runs
                order by created_at desc
                limit %s
                """,
                [safe_limit],
            )
            rows = [dict(row) for row in cur.fetchall()]

    durations = sorted(
        float(row["duration_ms"])
        for row in rows
        if row.get("duration_ms") is not None and float(row["duration_ms"]) >= 0
    )

    def percentile(values: list[float], fraction: float) -> float | None:
        if not values:
            return None
        index = min(round((len(values) - 1) * fraction), len(values) - 1)
        return round(values[index], 1)

    cited_rows = [
        row for row in rows
        if isinstance(row.get("citation_metrics"), dict) and row["citation_metrics"].get("status")
    ]
    citation_passed = sum(
        1
        for row in cited_rows
        if row["citation_metrics"].get("status") == "passed"
        and row["citation_metrics"].get("answer_has_document_citation") is True
    )
    degraded = sum(
        1 for row in cited_rows if row["citation_metrics"].get("status") == "degraded"
    )
    completed = sum(1 for row in rows if row.get("status") == "completed")
    return {
        "sample_size": len(rows),
        "completed_rate": round(completed / len(rows), 4) if rows else None,
        "citation_sample_size": len(cited_rows),
        "citation_pass_rate": round(citation_passed / len(cited_rows), 4) if cited_rows else None,
        "degraded_rate": round(degraded / len(cited_rows), 4) if cited_rows else None,
        "latency_ms": {
            "p50": percentile(durations, 0.50),
            "p95": percentile(durations, 0.95),
        },
        "recent_runs": rows[:20],
    }
