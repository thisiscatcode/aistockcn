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
    error_code: str | None = None,
) -> None:
    """Persist privacy-conscious usage telemetry without storing the question text."""
    question_hash = hashlib.sha256(question.strip().encode("utf-8")).hexdigest()
    try:
        with _write_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    insert into research_agent_runs (
                      id, run_type, symbols, question_sha256, status, duration_ms,
                      evidence_count, tool_plan, error_code
                    ) values (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                    """,
                    [
                        str(uuid4()), run_type, symbols, question_hash, status, duration_ms,
                        evidence_count, json.dumps(tool_plan) if tool_plan else None, error_code,
                    ],
                )
            conn.commit()
    except Exception:
        # Telemetry must never break a user-facing research answer.
        return
