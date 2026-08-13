from __future__ import annotations

from typing import Any

from app.config import get_settings
from app.services.research import normalize_us_symbol
from app.services.research_documents import ResearchDocumentError, _write_connection
from app.services.research_models import embed_texts, rerank_pairs


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{value:.8f}" for value in values) + "]"


def _candidate(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "chunk_id": row["chunk_id"],
        "document_id": row["document_id"],
        "filename": row["filename"],
        "document_type": row["document_type"],
        "filing_date": row["filing_date"],
        "fiscal_year": row["fiscal_year"],
        "source_url": row["source_url"],
        "page_number": row["page_number"],
        "locator_type": row.get("locator_type") or "page",
        "locator": row.get("locator") or f"page {row['page_number']}",
        "native_page_numbers": bool(row.get("native_page_numbers", True)),
        "source_format": row.get("source_format") or "pdf",
        "content": row["content"],
    }


def retrieve_document_evidence(
    *,
    symbol: str,
    question: str,
    top_k: int = 6,
    candidate_limit: int = 24,
) -> dict[str, Any]:
    normalized_symbol = normalize_us_symbol(symbol)
    normalized_question = " ".join(str(question or "").split())
    if not normalized_question:
        raise ResearchDocumentError("question_required")
    safe_top_k = max(1, min(int(top_k), 12))
    safe_candidate_limit = max(safe_top_k, min(int(candidate_limit), 60))

    with _write_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select count(*) as count from research_documents where symbol = %s and status = 'indexed'",
                [normalized_symbol],
            )
            indexed_document_count = int(cur.fetchone()["count"])
    settings = get_settings()
    if indexed_document_count == 0:
        return {
            "symbol": normalized_symbol,
            "question": normalized_question,
            "retrieval": {
                "strategy": "hybrid_rrf_cross_encoder",
                "embedding_model": settings.research_embedding_model,
                "reranker_model": settings.research_reranker_model,
                "indexed_documents": 0,
                "lexical_candidates": 0,
                "vector_candidates": 0,
                "merged_candidates": 0,
            },
            "results": [],
        }

    embeddings = embed_texts([normalized_question])
    if not embeddings:
        raise ResearchDocumentError("query_embedding_failed")
    query_vector = _vector_literal(embeddings[0])

    select_fields = """
      c.id as chunk_id, c.document_id, c.page_number, c.locator_type, c.locator, c.content,
      d.filename, d.document_type, d.filing_date, d.fiscal_year, d.source_url,
      d.native_page_numbers, d.source_format
    """
    with _write_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                select {select_fields},
                       ts_rank_cd(c.search_vector, websearch_to_tsquery('english', %s)) as lexical_score
                from research_document_chunks c
                join research_documents d on d.id = c.document_id
                where d.symbol = %s
                  and d.status = 'indexed'
                  and c.search_vector @@ websearch_to_tsquery('english', %s)
                order by lexical_score desc
                limit %s
                """,
                [normalized_question, normalized_symbol, normalized_question, safe_candidate_limit],
            )
            lexical_rows = [dict(row) for row in cur.fetchall()]

            cur.execute(
                f"""
                select {select_fields},
                       (c.embedding <=> %s::vector) as vector_distance
                from research_document_chunks c
                join research_documents d on d.id = c.document_id
                where d.symbol = %s
                  and d.status = 'indexed'
                  and c.embedding is not null
                order by c.embedding <=> %s::vector
                limit %s
                """,
                [query_vector, normalized_symbol, query_vector, safe_candidate_limit],
            )
            vector_rows = [dict(row) for row in cur.fetchall()]

    merged: dict[str, dict[str, Any]] = {}
    rrf_k = 60.0
    for rank, row in enumerate(lexical_rows, start=1):
        item = merged.setdefault(row["chunk_id"], {**_candidate(row), "rrf_score": 0.0})
        item["rrf_score"] += 1.0 / (rrf_k + rank)
        item["lexical_rank"] = rank
        item["lexical_score"] = float(row["lexical_score"])
    for rank, row in enumerate(vector_rows, start=1):
        item = merged.setdefault(row["chunk_id"], {**_candidate(row), "rrf_score": 0.0})
        item["rrf_score"] += 1.0 / (rrf_k + rank)
        item["vector_rank"] = rank
        item["vector_score"] = max(0.0, 1.0 - float(row["vector_distance"]))

    candidates = sorted(merged.values(), key=lambda item: item["rrf_score"], reverse=True)
    rerank_candidates = candidates[:safe_candidate_limit]
    if rerank_candidates:
        reranker_scores = rerank_pairs(
            normalized_question,
            [str(item["content"]) for item in rerank_candidates],
        )
        for item, score in zip(rerank_candidates, reranker_scores, strict=True):
            item["reranker_score"] = score
        rerank_candidates.sort(key=lambda item: item["reranker_score"], reverse=True)

    change_terms = ("change", "changed", "across", "compared", "year over year", "trend")
    diversify_by_document = any(term in normalized_question.lower() for term in change_terms)
    if diversify_by_document:
        results = []
        per_document: dict[str, int] = {}
        for item in rerank_candidates:
            document_id = str(item["document_id"])
            if per_document.get(document_id, 0) >= 2:
                continue
            results.append(item)
            per_document[document_id] = per_document.get(document_id, 0) + 1
            if len(results) >= safe_top_k:
                break
    else:
        results = rerank_candidates[:safe_top_k]
    return {
        "symbol": normalized_symbol,
        "question": normalized_question,
        "retrieval": {
            "strategy": "hybrid_rrf_cross_encoder",
            "embedding_model": settings.research_embedding_model,
            "reranker_model": settings.research_reranker_model,
            "indexed_documents": indexed_document_count,
            "lexical_candidates": len(lexical_rows),
            "vector_candidates": len(vector_rows),
            "merged_candidates": len(candidates),
            "diversified_by_document": diversify_by_document,
        },
        "results": results,
    }
