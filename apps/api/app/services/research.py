from __future__ import annotations

import json
import math
import re
import statistics
import time
from contextlib import contextmanager
from typing import Any, Iterator
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.config import Settings, get_settings
from app.serializers import records_to_json

try:
    import psycopg
    from psycopg.rows import dict_row
except Exception:  # pragma: no cover - runtime dependency availability is environment-specific
    psycopg = None
    dict_row = None


class ResearchError(RuntimeError):
    pass


RESEARCH_TOOLS = (
    "company_lookup",
    "market_history",
    "financial_calculator",
    "hybrid_document_search",
)


def normalize_us_symbol(value: Any) -> str:
    symbol = str(value or "").strip().upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,14}", symbol):
        raise ResearchError("invalid_symbol")
    return symbol


@contextmanager
def _connect(settings: Settings | None = None) -> Iterator[Any]:
    resolved = settings or get_settings()
    if not resolved.paper_db_url:
        raise ResearchError("database_not_configured")
    if psycopg is None or dict_row is None:
        raise ResearchError("database_driver_unavailable")
    with psycopg.connect(
        resolved.paper_db_url,
        row_factory=dict_row,
        connect_timeout=5,
        options="-c default_transaction_read_only=on",
    ) as conn:
        yield conn


COMPANY_SELECT_SQL = """
select
  m.symbol,
  m.market,
  m.stock_name,
  m.stock_name_zh,
  m.stock_type,
  m.stock_industry,
  m.stock_industry_en,
  m.stock_industry_short,
  m.market_cap,
  m.earnings_per_share,
  m.pe_ratio,
  m.currency,
  latest.trade_date,
  latest.close,
  latest.price_diff,
  latest.volume,
  latest.turnover,
  latest.average_trade
from us_stock_master m
left join lateral (
  select
    d.trade_date,
    d.close,
    d.price_diff,
    d.volume,
    d.turnover,
    d.average_trade
  from us_stock_daily_metrics d
  where d.symbol = m.symbol
  order by d.trade_date desc
  limit 1
) latest on true
"""


def search_companies(*, query: str = "", limit: int = 12) -> dict[str, Any]:
    safe_limit = max(1, min(int(limit), 30))
    normalized_query = str(query or "").strip()
    wildcard = f"%{normalized_query}%"

    where = """
      where m.is_active = true
        and m.del_flg = false
    """
    params: list[Any] = []
    if normalized_query:
        where += """
          and (
            m.symbol ilike %s
            or coalesce(m.stock_name, '') ilike %s
            or coalesce(m.stock_name_zh, '') ilike %s
          )
        """
        params.extend([wildcard, wildcard, wildcard])

    sql = COMPANY_SELECT_SQL + where + """
      order by
        case when upper(m.symbol) = upper(%s) then 0 else 1 end,
        case when exists (
          select 1 from us_stock_favorite_stocks f where f.symbol = m.symbol
        ) then 0 else 1 end,
        m.market_cap desc nulls last,
        m.symbol
      limit %s
    """
    params.extend([normalized_query, safe_limit])

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            companies = [dict(row) for row in cur.fetchall()]
            cur.execute(
                "select count(*) from us_stock_master where is_active = true and del_flg = false"
            )
            total_active = int(cur.fetchone()["count"])

    return {
        "query": normalized_query,
        "rows": len(companies),
        "total_active": total_active,
        "companies": records_to_json(companies),
    }


def get_company_snapshot(*, symbol: str, history_limit: int = 30) -> dict[str, Any]:
    normalized_symbol = normalize_us_symbol(symbol)
    safe_history_limit = max(5, min(int(history_limit), 260))

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                COMPANY_SELECT_SQL
                + """
                  where m.symbol = %s
                    and m.is_active = true
                    and m.del_flg = false
                """,
                [normalized_symbol],
            )
            company = cur.fetchone()
            if not company:
                raise ResearchError("company_not_found")

            cur.execute(
                """
                select
                  trade_date,
                  close,
                  price_diff,
                  volume,
                  turnover,
                  average_trade,
                  transaction_count
                from us_stock_daily_metrics
                where symbol = %s
                order by trade_date desc
                limit %s
                """,
                [normalized_symbol, safe_history_limit],
            )
            history = [dict(row) for row in cur.fetchall()]

            cur.execute(
                """
                select count(*) as observations, min(trade_date) as date_min, max(trade_date) as date_max
                from us_stock_daily_metrics
                where symbol = %s
                """,
                [normalized_symbol],
            )
            coverage = dict(cur.fetchone() or {})

    return {
        "company": records_to_json([dict(company)])[0],
        "history": records_to_json(history),
        "coverage": records_to_json([coverage])[0],
        "research_readiness": {
            "market_data": "ready",
            "sec_filings": "not_indexed",
            "financial_facts": "not_indexed",
        },
    }


def _numeric(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _percent_change(latest: float | None, earlier: float | None) -> float | None:
    if latest is None or earlier in (None, 0):
        return None
    return round((latest / earlier - 1.0) * 100.0, 2)


def _market_calculations(history: list[dict[str, Any]]) -> dict[str, Any]:
    closes = [_numeric(row.get("close")) for row in history]
    closes = [value for value in closes if value is not None]
    result: dict[str, Any] = {
        "return_1d_pct": _percent_change(closes[0], closes[1]) if len(closes) > 1 else None,
        "return_5d_pct": _percent_change(closes[0], closes[5]) if len(closes) > 5 else None,
        "return_20d_pct": _percent_change(closes[0], closes[20]) if len(closes) > 20 else None,
        "annualized_volatility_pct": None,
    }
    daily_returns = [
        closes[index - 1] / closes[index] - 1.0
        for index in range(1, len(closes))
        if closes[index] != 0
    ]
    if len(daily_returns) >= 2:
        result["annualized_volatility_pct"] = round(
            statistics.stdev(daily_returns) * math.sqrt(252) * 100.0,
            2,
        )
    return result


def _extract_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE)
    try:
        value = json.loads(cleaned)
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            return {}
        try:
            value = json.loads(cleaned[start : end + 1])
            return value if isinstance(value, dict) else {}
        except json.JSONDecodeError:
            return {}


def _call_local_json_model(*, prompt: str, settings: Settings) -> dict[str, Any]:
    payload = {
        "model": settings.research_llm_model,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.1},
        "prompt": prompt,
    }
    request = Request(
        f"{settings.research_llm_base_url}/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    raw: dict[str, Any] | None = None
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with urlopen(request, timeout=settings.research_llm_timeout_seconds) as response:
                raw = json.loads(response.read().decode("utf-8"))
            break
        except HTTPError as exc:
            last_error = exc
            if exc.code < 500:
                break
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
        if attempt < 2:
            time.sleep(0.25 * (2 ** attempt))
    if raw is None:
        raise ResearchError("research_model_unavailable") from last_error
    return _extract_json_object(str(raw.get("response") or ""))


def plan_research_tools(*, question: str, settings: Settings | None = None) -> dict[str, Any]:
    """Ask the local LLM for a structured tool plan, then validate it server-side."""
    resolved = settings or get_settings()
    normalized_question = " ".join(str(question or "").split())
    fallback = ["company_lookup", "market_history", "financial_calculator", "hybrid_document_search"]
    try:
        generated = _call_local_json_model(
            settings=resolved,
            prompt=(
                "You are a research-agent planner. Choose only the tools needed to answer the question. "
                "Available tools: company_lookup (identity and valuation snapshot), market_history "
                "(daily prices), financial_calculator (returns and volatility), hybrid_document_search "
                "(annual reports, filings, risks and management language). Return JSON only: "
                '{"tools":["tool_name"],"reason":"one short sentence"}. '
                "Use hybrid_document_search for any question about company performance, financial results, "
                "risks, strategy, guidance, management statements or source evidence. Always include "
                f"company_lookup. Question: {normalized_question}"
            ),
        )
        requested = generated.get("tools")
        tools = []
        if isinstance(requested, list):
            for item in requested:
                name = str(item).strip()
                if name in RESEARCH_TOOLS and name not in tools:
                    tools.append(name)
        if "company_lookup" not in tools:
            tools.insert(0, "company_lookup")
        lower_question = normalized_question.lower()
        market_signal_terms = (
            "return", "volatility", "price", "market", "momentum", "20-day", "20 day",
            "5-day", "5 day", "risk signal",
        )
        if any(term in lower_question for term in market_signal_terms):
            for required_tool in ("market_history", "financial_calculator"):
                if required_tool not in tools:
                    tools.append(required_tool)
        if "financial_calculator" in tools and "market_history" not in tools:
            tools.append("market_history")
        if not tools:
            tools = fallback
        tools = [tool for tool in RESEARCH_TOOLS if tool in tools]
        reason = str(generated.get("reason") or "Validated structured plan from the local model.").strip()
        return {"tools": tools, "reason": reason, "planner": "local_llm_structured_output"}
    except ResearchError:
        return {
            "tools": fallback,
            "reason": "Deterministic fallback plan used because the local planner was unavailable.",
            "planner": "deterministic_fallback",
        }


def _generate_research_synthesis(
    *,
    question: str,
    company: dict[str, Any],
    calculations: dict[str, Any],
    document_context: list[dict[str, Any]],
    settings: Settings,
) -> dict[str, Any]:
    filing_instruction = (
        "Use filing claims only when directly supported by the supplied document passages, and cite the page "
        "in the prose as [filename, p. N]."
        if document_context
        else
        "The SEC filing corpus returned no relevant passages, so do not claim knowledge of revenue, earnings "
        "trends, risk factors, guidance, management statements, or annual-report content."
    )
    generated = _call_local_json_model(
        settings=settings,
        prompt=(
            "You are an equity research copilot. Answer only from the supplied market and document context. "
            f"{filing_instruction} If the question needs evidence that is not supplied, state that limitation. "
            "Return JSON only with keys answer (string) and "
            "model_inference (array of at most 3 short strings). Keep facts and interpretation distinct.\n\n"
            f"Question: {question}\n"
            f"Company context: {json.dumps(company, default=str)}\n"
            f"Deterministic calculations: {json.dumps(calculations, default=str)}\n"
            f"Retrieved document passages: {json.dumps(document_context, default=str)}"
        ),
    )
    answer = str(generated.get("answer") or "").strip()
    inferences = generated.get("model_inference")
    if not answer:
        raise ResearchError("research_model_invalid_response")
    if not isinstance(inferences, list):
        inferences = []
    return {
        "answer": answer,
        "model_inference": [str(item).strip() for item in inferences if str(item).strip()][:3],
    }


def _retrieve_document_evidence(*, symbol: str, question: str) -> dict[str, Any]:
    from app.services.research_retrieval import retrieve_document_evidence

    return retrieve_document_evidence(symbol=symbol, question=question, top_k=6)


def answer_research_question(
    *,
    symbol: str,
    question: str,
    tool_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    started_at = time.perf_counter()
    normalized_symbol = normalize_us_symbol(symbol)
    normalized_question = " ".join(str(question or "").split())
    if not normalized_question:
        raise ResearchError("question_required")
    if len(normalized_question) > 800:
        raise ResearchError("question_too_long")

    snapshot = get_company_snapshot(symbol=normalized_symbol, history_limit=60)
    company = snapshot["company"]
    history = snapshot["history"]
    calculations = _market_calculations(history)
    settings = get_settings()
    plan = tool_plan or plan_research_tools(question=normalized_question, settings=settings)
    selected_tools = list(plan.get("tools") or [])
    retrieval = (
        _retrieve_document_evidence(symbol=normalized_symbol, question=normalized_question)
        if "hybrid_document_search" in selected_tools
        else {"results": [], "retrieval": {"strategy": "not_selected_by_agent"}}
    )
    document_context = list(retrieval.get("results") or [])
    synthesis = _generate_research_synthesis(
        question=normalized_question,
        company=company,
        calculations=calculations,
        document_context=document_context,
        settings=settings,
    )

    latest_date = company.get("trade_date")
    evidence: list[dict[str, Any]] = [
        {
            "id": "market-snapshot",
            "claim": (
                f"Latest close: {company.get('close')}; daily change: {company.get('price_diff')}; "
                f"volume: {company.get('volume')}."
            ),
            "source": "AiStockCN PostgreSQL",
            "locator": f"us_stock_daily_metrics · {normalized_symbol} · {latest_date}",
            "as_of": latest_date,
        },
        {
            "id": "company-fundamentals",
            "claim": f"P/E: {company.get('pe_ratio')}; EPS: {company.get('earnings_per_share')}.",
            "source": "AiStockCN PostgreSQL",
            "locator": f"us_stock_master · {normalized_symbol}",
            "as_of": latest_date,
        },
        {
            "id": "calculated-market-signals",
            "claim": (
                f"1-day return: {calculations.get('return_1d_pct')}%; "
                f"5-day return: {calculations.get('return_5d_pct')}%; "
                f"20-day return: {calculations.get('return_20d_pct')}%; "
                f"annualized volatility: {calculations.get('annualized_volatility_pct')}%."
            ),
            "source": "AiStockCN calculation tool",
            "locator": f"60 most recent observations ending {latest_date}",
            "as_of": latest_date,
        },
    ]
    if "financial_calculator" not in selected_tools:
        evidence = [item for item in evidence if item["id"] != "calculated-market-signals"]

    return {
        "symbol": normalized_symbol,
        "question": normalized_question,
        "answer": synthesis["answer"],
        "document_evidence": [
            {
                "id": item["chunk_id"],
                "document_id": item["document_id"],
                "claim": item["content"],
                "source": item["filename"],
                "locator": f"page {item['page_number']}",
                "page_number": item["page_number"],
                "source_url": item.get("source_url"),
                "reranker_score": item.get("reranker_score"),
            }
            for item in document_context
        ],
        "data_evidence": evidence,
        "model_inference": synthesis["model_inference"],
        "limitations": (
            ["Only the retrieved filing passages shown as evidence were available to the model."]
            if document_context
            else ["No relevant indexed filing passages were available; no filing-based claims are included."]
        ) + ["Market data can be delayed and this output is research assistance, not investment advice."],
        "agent_steps": [
            {
                "tool": "agent_planner",
                "status": "completed",
                "detail": f"{plan.get('planner')}: {', '.join(selected_tools)}",
            },
            {"tool": "company_lookup", "status": "completed", "detail": normalized_symbol},
            *(
                [{"tool": "market_history", "status": "completed", "detail": f"{len(history)} observations"}]
                if "market_history" in selected_tools else []
            ),
            *(
                [{"tool": "financial_calculator", "status": "completed", "detail": "returns and volatility"}]
                if "financial_calculator" in selected_tools else []
            ),
            *(
                [{
                    "tool": "hybrid_document_search",
                    "status": "completed",
                    "detail": f"{len(document_context)} reranked passages",
                }]
                if "hybrid_document_search" in selected_tools else []
            ),
            {"tool": "evidence_synthesis", "status": "completed", "detail": settings.research_llm_model},
        ],
        "tool_plan": plan,
        "retrieval": retrieval.get("retrieval"),
        "model": {"provider": "ollama", "name": settings.research_llm_model},
        "duration_ms": round((time.perf_counter() - started_at) * 1000, 1),
    }


def compare_research_companies(*, symbols: list[str], question: str) -> dict[str, Any]:
    normalized_symbols: list[str] = []
    for raw_symbol in symbols:
        symbol = normalize_us_symbol(raw_symbol)
        if symbol not in normalized_symbols:
            normalized_symbols.append(symbol)
    if not 2 <= len(normalized_symbols) <= 3:
        raise ResearchError("comparison_requires_two_or_three_companies")
    normalized_question = " ".join(str(question or "").split())
    if not normalized_question:
        raise ResearchError("question_required")

    companies: list[dict[str, Any]] = []
    document_evidence: list[dict[str, Any]] = []
    for symbol in normalized_symbols:
        snapshot = get_company_snapshot(symbol=symbol, history_limit=60)
        calculations = _market_calculations(snapshot["history"])
        companies.append({"symbol": symbol, "company": snapshot["company"], "calculations": calculations})
        retrieval = _retrieve_document_evidence(symbol=symbol, question=normalized_question)
        for item in list(retrieval.get("results") or [])[:3]:
            document_evidence.append({
                "symbol": symbol,
                "id": item["chunk_id"],
                "document_id": item["document_id"],
                "claim": item["content"],
                "source": item["filename"],
                "locator": f"page {item['page_number']}",
                "page_number": item["page_number"],
                "source_url": item.get("source_url"),
                "reranker_score": item.get("reranker_score"),
            })

    settings = get_settings()
    generated = _call_local_json_model(
        settings=settings,
        prompt=(
            "You are an equity comparison agent. Compare only the supplied companies and evidence. "
            "Never invent filing facts. Separate directly observed evidence from interpretation. Return JSON "
            "only with answer (string) and model_inference (array of at most 3 strings). Cite document claims "
            "as [SYMBOL, filename, p. N].\n"
            f"Question: {normalized_question}\n"
            f"Company data and calculations: {json.dumps(companies, default=str)}\n"
            f"Document evidence: {json.dumps(document_evidence, default=str)}"
        ),
    )
    answer = str(generated.get("answer") or "").strip()
    if not answer:
        raise ResearchError("research_model_invalid_response")
    inference = generated.get("model_inference")
    if not isinstance(inference, list):
        inference = []
    return {
        "symbols": normalized_symbols,
        "question": normalized_question,
        "answer": answer,
        "companies": companies,
        "document_evidence": document_evidence,
        "model_inference": [str(item).strip() for item in inference if str(item).strip()][:3],
        "agent_steps": [
            {"tool": "comparison_planner", "status": "completed", "detail": ", ".join(normalized_symbols)},
            {"tool": "company_lookup", "status": "completed", "detail": f"{len(companies)} companies"},
            {"tool": "financial_calculator", "status": "completed", "detail": "returns and volatility per company"},
            {"tool": "hybrid_document_search", "status": "completed", "detail": f"{len(document_evidence)} passages"},
            {"tool": "comparison_synthesis", "status": "completed", "detail": settings.research_llm_model},
        ],
        "model": {"provider": "ollama", "name": settings.research_llm_model},
    }
