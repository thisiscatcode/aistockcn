from __future__ import annotations

import json
import re
import time
from typing import Any
from uuid import uuid4

import torch

from app.services.research_documents import _write_connection
from app.services.research_models import rerank_pairs
from app.services.research_models import model_profile


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

CN_BENCHMARK_CASES = [
    {"query": "公司面临哪些供应链风险？", "relevant": "主要原材料供应商集中度较高，供应中断可能对生产经营造成重大不利影响。", "distractors": ["公司召开了年度股东大会。", "董事会审议通过利润分配方案。", "公司注册地址未发生变化。"]},
    {"query": "营业收入同比变化的原因是什么？", "relevant": "营业收入同比增长主要由核心产品销量增加及新客户贡献带动。", "distractors": ["公司采用直线法计提固定资产折旧。", "证券简称保持不变。", "审计委员会召开了四次会议。"]},
    {"query": "毛利率为什么下降？", "relevant": "毛利率下降主要受到原材料价格上涨和产品结构变化影响。", "distractors": ["年度股东大会将在五月举行。", "存货按成本与可变现净值孰低计量。", "公司变更了办公地址。"]},
    {"query": "管理层如何描述未来研发投入？", "relevant": "管理层预计继续加大研发投入，重点推进人工智能和核心产品平台建设。", "distractors": ["股利分配由董事会审议。", "公司租赁部分办公场所。", "会计年度自一月一日起。"]},
    {"query": "最新年报新增了什么监管风险？", "relevant": "监管要求持续变化可能增加合规成本，并对部分业务模式形成限制。", "distractors": ["收入在控制权转移时确认。", "公司购买了财产保险。", "员工人数有所增加。"]},
    {"query": "净利润下降的主要原因是什么？", "relevant": "净利润下降主要由于研发费用增加、资产减值以及一次性重组支出。", "distractors": ["公司聘任了证券事务代表。", "每股收益按加权平均股数计算。", "公司章程进行了文字修订。"]},
]


def _tokens(value: str) -> set[str]:
    lowered = value.lower()
    latin = set(re.findall(r"[a-z0-9]+", lowered))
    chinese = "".join(re.findall(r"[\u3400-\u9fff]", lowered))
    return latin | {chinese[index:index + 2] for index in range(max(0, len(chinese) - 1))}


def _baseline_score(query: str, passage: str) -> float:
    query_tokens = _tokens(query)
    if not query_tokens:
        return 0.0
    return len(query_tokens & _tokens(passage)) / len(query_tokens)


def run_reranker_evaluation(market: str = "US") -> dict[str, Any]:
    started_at = time.perf_counter()
    normalized_market = "CN" if str(market).upper() == "CN" else "US"
    profile = model_profile(normalized_market)
    cases = CN_BENCHMARK_CASES if normalized_market == "CN" else BENCHMARK_CASES
    details: list[dict[str, Any]] = []
    reciprocal_ranks: list[float] = []
    top1_hits = 0
    baseline_hits = 0

    for case_index, case in enumerate(cases, start=1):
        passages = [case["distractors"][0], case["relevant"], *case["distractors"][1:]]
        scores = rerank_pairs(case["query"], passages, market=normalized_market)
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

    case_count = len(cases)
    duration_ms = round((time.perf_counter() - started_at) * 1000, 1)
    result = {
        "id": str(uuid4()),
        "market": normalized_market,
        "benchmark_name": f"financial_passage_ranking_{normalized_market.lower()}_v1",
        "model_name": profile["reranker_model"],
        "retrieval_profile": profile,
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
                  mean_reciprocal_rank, baseline_top1_accuracy, details, duration_ms,
                  market, retrieval_profile
                ) values (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s::jsonb)
                """,
                [
                    result["id"], result["benchmark_name"], result["model_name"], case_count,
                    result["top1_accuracy"], result["mean_reciprocal_rank"],
                    result["baseline_top1_accuracy"], json.dumps(details), duration_ms,
                    normalized_market, json.dumps(profile),
                ],
            )
        conn.commit()
    return result


def list_evaluation_runs(limit: int = 10, market: str | None = None) -> dict[str, Any]:
    safe_limit = max(1, min(int(limit), 30))
    with _write_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select id, market, benchmark_name, model_name, retrieval_profile, case_count, top1_accuracy,
                       mean_reciprocal_rank, baseline_top1_accuracy, duration_ms, created_at
                from research_evaluation_runs
                where (%s::text is null or market = %s::text)
                order by created_at desc
                limit %s
                """,
                [market.upper() if market else None, market.upper() if market else None, safe_limit],
            )
            runs = [dict(row) for row in cur.fetchall()]
    return {"rows": len(runs), "runs": runs}
