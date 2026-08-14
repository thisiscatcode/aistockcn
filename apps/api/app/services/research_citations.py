from __future__ import annotations

import re
from typing import Any


DOCUMENT_CITATION_PATTERN = re.compile(r"\[(D\d+)\]")


def validate_research_citations(
    *, result: dict[str, Any], synthesis_degraded: bool = False
) -> dict[str, Any]:
    """Validate model citation identifiers against server-returned evidence records."""
    documents = list(result.get("document_evidence") or [])
    available = {
        str(item.get("citation_id"))
        for item in documents
        if str(item.get("citation_id") or "").strip()
    }
    answer_markers = set(DOCUMENT_CITATION_PATTERN.findall(str(result.get("answer") or "")))
    declared = {
        str(item)
        for item in (result.get("cited_evidence_ids") or [])
        if str(item).strip()
    }
    requested = answer_markers | declared
    visible_valid = sorted(answer_markers & available)
    invalid = sorted(requested - available)

    if synthesis_degraded:
        status = "degraded"
    elif invalid:
        status = "failed"
    elif available and not visible_valid:
        status = "warning"
    else:
        status = "passed"

    denominator = len(visible_valid) + len(invalid)
    return {
        "status": status,
        "available_document_citations": len(available),
        "cited_document_citations": len(visible_valid),
        "valid_citation_ids": visible_valid,
        "invalid_citation_ids": invalid,
        "answer_has_document_citation": bool(visible_valid),
        "citation_validity_rate": round(len(visible_valid) / denominator, 4) if denominator else (1.0 if not available else 0.0),
        "locator_source": "server_evidence_records",
    }
