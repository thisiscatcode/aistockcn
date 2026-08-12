from __future__ import annotations

import json
import re
import time
from typing import Any
from uuid import uuid4

import torch

from app.config import get_settings
from app.services.research_documents import _write_connection
from app.services.research_models import rerank_pairs


BENCHMARK_CASES = [
    {
        "query": "What supply chain risk could affect operating results?",
        "relevant": "Supply chain concentration and dependence on a small number of manufacturers may adversely affect operating results.",
        "distractors": [
            "The company repurchased shares during the fiscal year.",
            "Cash and cash equivalents are held with major financial institutions.",
            "The board approved the appointment of a new independent director.",
        ],
    },
    {
        "query": "How did services revenue change year over year?",
        "relevant": "Services revenue increased year over year, driven by cloud subscriptions and payment services.",
        "distractors": [
            "Property and equipment depreciation uses the straight-line method.",
            "The common stock trades on the Nasdaq Global Select Market.",
            "Foreign currency translation adjustments are recorded in comprehensive income.",
        ],
    },
    {
        "query": "Why did gross margin improve?",
        "relevant": "Gross margin improved primarily because of a more favorable product and services mix.",
        "distractors": [
            "The annual meeting will be held in May.",
            "Inventories are stated at the lower of cost and net realizable value.",
            "The audit committee met eight times during the year.",
        ],
    },
    {
        "query": "What does management expect for AI investment?",
        "relevant": "Management expects continued investment in artificial intelligence infrastructure and product development.",
        "distractors": [
            "Dividends are declared at the discretion of the board.",
            "The company leases office facilities under operating leases.",
            "The fiscal year ends on the last Saturday of September.",
        ],
    },
    {
        "query": "What regulatory issue is identified as a risk?",
        "relevant": "Increasing regulatory scrutiny and potential antitrust actions could restrict business practices and raise compliance costs.",
        "distractors": [
            "Revenue is recognized when control transfers to the customer.",
            "The company maintains insurance coverage for certain losses.",
            "No material changes were made to the code of ethics.",
        ],
    },
    {
        "query": "What drove the decline in operating profit?",
        "relevant": "Operating profit declined due to higher research and development spending and restructuring charges.",
        "distractors": [
            "The transfer agent maintains shareholder records.",
            "Basic earnings per share uses the weighted average shares outstanding.",
            "The company has authorized but unissued preferred shares.",
        ],
    },
]


def _tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", value.lower()))


def _baseline_score(query: str, passage: str) -> float:
    query_tokens = _tokens(query)
    if not query_tokens:
        return 0.0
    return len(query_tokens & _tokens(passage)) / len(query_tokens)


def run_reranker_evaluation() -> dict[str, Any]:
    started_at = time.perf_counter()
    settings = get_settings()
    details: list[dict[str, Any]] = []
    reciprocal_ranks: list[float] = []
    top1_hits = 0
    baseline_hits = 0

    for case_index, case in enumerate(BENCHMARK_CASES, start=1):
        passages = [case["distractors"][0], case["relevant"], *case["distractors"][1:]]
        scores = rerank_pairs(case["query"], passages)
        ranked = sorted(range(len(passages)), key=lambda index: scores[index], reverse=True)
        relevant_index = 1
        rank = ranked.index(relevant_index) + 1
        reciprocal_ranks.append(1.0 / rank)
        if rank == 1:
            top1_hits += 1

        baseline_scores = [_baseline_score(case["query"], passage) for passage in passages]
        baseline_ranked = sorted(range(len(passages)), key=lambda index: baseline_scores[index], reverse=True)
        baseline_rank = baseline_ranked.index(relevant_index) + 1
        if baseline_rank == 1:
            baseline_hits += 1
        details.append({
            "case": case_index,
            "query": case["query"],
            "relevant_rank": rank,
            "reranker_top_passage": passages[ranked[0]],
            "reranker_top_score": round(float(scores[ranked[0]]), 4),
            "baseline_relevant_rank": baseline_rank,
            "passed": rank == 1,
        })

    case_count = len(BENCHMARK_CASES)
    duration_ms = round((time.perf_counter() - started_at) * 1000, 1)
    result = {
        "id": str(uuid4()),
        "benchmark_name": "financial_passage_ranking_v1",
        "model_name": settings.research_reranker_model,
        "framework": "PyTorch",
        "torch_version": torch.__version__,
        "case_count": case_count,
        "top1_accuracy": round(top1_hits / case_count, 4),
        "mean_reciprocal_rank": round(sum(reciprocal_ranks) / case_count, 4),
        "baseline_top1_accuracy": round(baseline_hits / case_count, 4),
        "duration_ms": duration_ms,
        "details": details,
    }
    with _write_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into research_evaluation_runs (
                  id, benchmark_name, model_name, case_count, top1_accuracy,
                  mean_reciprocal_rank, baseline_top1_accuracy, details, duration_ms
                ) values (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                """,
                [
                    result["id"], result["benchmark_name"], result["model_name"], case_count,
                    result["top1_accuracy"], result["mean_reciprocal_rank"],
                    result["baseline_top1_accuracy"], json.dumps(details), duration_ms,
                ],
            )
        conn.commit()
    return result


def list_evaluation_runs(limit: int = 10) -> dict[str, Any]:
    safe_limit = max(1, min(int(limit), 30))
    with _write_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select id, benchmark_name, model_name, case_count, top1_accuracy,
                       mean_reciprocal_rank, baseline_top1_accuracy, duration_ms, created_at
                from research_evaluation_runs
                order by created_at desc
                limit %s
                """,
                [safe_limit],
            )
            runs = [dict(row) for row in cur.fetchall()]
    return {"rows": len(runs), "runs": runs}
