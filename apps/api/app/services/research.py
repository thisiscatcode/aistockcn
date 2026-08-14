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
    "sec_financial_facts",
    "hybrid_document_search",
)


def normalize_us_symbol(value: Any) -> str:
    symbol = str(value or "").strip().upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,14}", symbol):
        raise ResearchError("invalid_symbol")
    return symbol


def normalize_research_market(value: Any) -> str:
    market = str(value or "US").strip().upper()
    if market not in {"CN", "US"}:
        raise ResearchError("unsupported_market")
    return market


def normalize_research_symbol(value: Any, market: Any = "US") -> str:
    normalized_market = normalize_research_market(market)
    if normalized_market == "US":
        return normalize_us_symbol(value)
    symbol = str(value or "").strip().upper()
    symbol = re.sub(r"^(?:SH|SZ|BJ)[.:]?", "", symbol)
    symbol = re.sub(r"\.(?:SH|SZ|BJ)$", "", symbol)
    if not re.fullmatch(r"\d{6}", symbol):
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


def search_companies(*, query: str = "", limit: int = 12, market: str = "US") -> dict[str, Any]:
    safe_limit = max(1, min(int(limit), 30))
    normalized_market = normalize_research_market(market)
    normalized_query = str(query or "").strip()
    wildcard = f"%{normalized_query}%"

    if normalized_market == "CN":
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select symbol, exchange as market, name as stock_name, name_zh as stock_name_zh,
                           null::text as stock_type, null::text as stock_industry,
                           null::text as stock_industry_en, null::text as stock_industry_short,
                           null::numeric as market_cap, null::numeric as earnings_per_share,
                           null::numeric as pe_ratio, currency,
                           null::date as trade_date, null::numeric as close, null::numeric as price_diff,
                           null::numeric as volume, null::numeric as turnover, null::numeric as average_trade
                    from research_issuers
                    where market = 'CN'
                      and (%s = '' or symbol ilike %s or coalesce(name, '') ilike %s or coalesce(name_zh, '') ilike %s)
                    order by case when symbol = %s then 0 else 1 end, symbol
                    limit %s
                    """,
                    [normalized_query, wildcard, wildcard, wildcard, normalized_query, safe_limit],
                )
                companies = [dict(row) for row in cur.fetchall()]
                cur.execute("select count(*) from research_issuers where market = 'CN'")
                total_active = int(cur.fetchone()["count"])
        return {
            "market": normalized_market,
            "query": normalized_query,
            "rows": len(companies),
            "total_active": total_active,
            "companies": records_to_json(companies),
        }

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
        "market": normalized_market,
        "query": normalized_query,
        "rows": len(companies),
        "total_active": total_active,
        "companies": records_to_json(companies),
    }


def get_company_snapshot(*, symbol: str, history_limit: int = 30, market: str = "US") -> dict[str, Any]:
    normalized_market = normalize_research_market(market)
    normalized_symbol = normalize_research_symbol(symbol, normalized_market)
    safe_history_limit = max(5, min(int(history_limit), 260))

    if normalized_market == "CN":
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select symbol, exchange as market, name as stock_name, name_zh as stock_name_zh,
                           currency, null::text as stock_industry, null::text as stock_industry_en,
                           null::numeric as close, null::numeric as price_diff, null::date as trade_date
                    from research_issuers where market = 'CN' and symbol = %s
                    """,
                    [normalized_symbol],
                )
                company = cur.fetchone()
                if not company:
                    raise ResearchError("company_not_found")
                cur.execute(
                    "select count(*) filter (where status = 'indexed') as indexed_documents from research_documents where market = 'CN' and symbol = %s",
                    [normalized_symbol],
                )
                document_coverage = dict(cur.fetchone() or {})
        return {
            "market": "CN",
            "company": records_to_json([dict(company)])[0],
            "history": [],
            "coverage": {"observations": 0, "date_min": None, "date_max": None},
            "research_readiness": {
                "market_data": "available_in_quant_platform",
                "official_filings": "ready" if int(document_coverage.get("indexed_documents") or 0) else "not_indexed",
                "financial_facts": "validation_required",
            },
        }

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
            cur.execute(
                """
                select count(*) filter (where status = 'indexed') as indexed_documents
                from research_documents where symbol = %s
                """,
                [normalized_symbol],
            )
            document_coverage = dict(cur.fetchone() or {})
            cur.execute(
                """
                select fact_count, status, synced_at
                from research_financial_sync_status where symbol = %s
                """,
                [normalized_symbol],
            )
            financial_coverage = dict(cur.fetchone() or {})

    return {
        "market": normalized_market,
        "company": records_to_json([dict(company)])[0],
        "history": records_to_json(history),
        "coverage": records_to_json([coverage])[0],
        "research_readiness": {
            "market_data": "ready",
            "sec_filings": "ready" if int(document_coverage.get("indexed_documents") or 0) else "not_indexed",
            "financial_facts": "ready" if financial_coverage.get("status") == "ready" else "not_indexed",
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


def _call_local_json_model(
    *,
    prompt: str,
    settings: Settings,
    max_output_tokens: int = 240,
    json_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "model": settings.research_llm_model,
        "stream": False,
        "format": json_schema or "json",
        "options": {
            "temperature": 0.1,
            "num_predict": max(64, min(int(max_output_tokens), 480)),
        },
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
        except TimeoutError as exc:
            last_error = exc
            break
        except (URLError, json.JSONDecodeError) as exc:
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
    fallback = [
        "company_lookup", "market_history", "financial_calculator",
        "sec_financial_facts", "hybrid_document_search",
    ]
    try:
        generated = _call_local_json_model(
            settings=resolved,
            max_output_tokens=96,
            json_schema={
                "type": "object",
                "properties": {
                    "tools": {"type": "array", "items": {"type": "string"}},
                    "reason": {"type": "string"},
                },
                "required": ["tools", "reason"],
            },
            prompt=(
                "You are a research-agent planner. Choose only the tools needed to answer the question. "
                "Available tools: company_lookup (identity and valuation snapshot), market_history "
                "(daily prices), financial_calculator (returns and volatility), sec_financial_facts "
                "(standardized SEC XBRL revenue, profit, EPS, cash flow and balance sheet facts), "
                "hybrid_document_search "
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
        financial_fact_terms = (
            "revenue", "sales", "profit", "income", "earnings", "eps", "margin",
            "cash flow", "free cash", "capex", "assets", "liabilities", "balance sheet",
            "financial", "year over year", "yoy", "growth",
        )
        if any(term in lower_question for term in market_signal_terms):
            for required_tool in ("market_history", "financial_calculator"):
                if required_tool not in tools:
                    tools.append(required_tool)
        if "financial_calculator" in tools and "market_history" not in tools:
            tools.append("market_history")
        if any(term in lower_question for term in financial_fact_terms):
            if "sec_financial_facts" not in tools:
                tools.append("sec_financial_facts")
            if not _question_requires_qualitative_synthesis(normalized_question):
                tools = [tool for tool in tools if tool != "hybrid_document_search"]
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
    financial_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    model_company_context = {
        key: company.get(key)
        for key in (
            "symbol", "stock_name", "stock_industry_en", "trade_date",
            "close", "price_diff", "pe_ratio", "earnings_per_share",
        )
        if company.get(key) is not None
    }

    def compact_period(
        period: dict[str, Any] | None, metrics: tuple[str, ...]
    ) -> dict[str, Any] | None:
        if not period:
            return None
        return {
            "fiscal_year": period.get("fiscal_year"),
            "end_date": period.get("end_date"),
            "metrics": {
                metric: {
                    key: fact.get(key)
                    for key in ("value", "unit", "locator")
                    if fact.get(key) is not None
                }
                for metric in metrics
                if (fact := (period.get("metrics") or {}).get(metric))
            },
        }

    model_financial_context = None
    if financial_context:
        annual_metrics = ("revenue", "net_income")
        quarter_metrics = ("revenue", "net_income")
        annual_changes = financial_context.get("annual_changes") or {}
        quarter_changes = financial_context.get("quarterly_yoy_changes") or {}
        model_financial_context = {
            "latest_annual": compact_period(
                financial_context.get("latest_annual"), annual_metrics
            ),
            "annual_changes": {
                metric: annual_changes.get(metric)
                for metric in (
                    "revenue", "operating_income", "net_income",
                    "gross_margin_pct", "operating_margin_pct", "net_margin_pct",
                )
                if annual_changes.get(metric) is not None
            },
        }
        if any(term in question.lower() for term in ("quarter", "quarterly", "latest results")):
            model_financial_context["latest_quarter"] = compact_period(
                financial_context.get("latest_quarter"), quarter_metrics
            )
            model_financial_context["quarterly_yoy_changes"] = {
                metric: quarter_changes.get(metric)
                for metric in quarter_metrics
                if quarter_changes.get(metric) is not None
            }

    prompt_documents = [
        {
            "filename": item.get("filename"),
            "locator": item.get("locator") or f"page {item.get('page_number')}",
            "content": str(item.get("content") or "")[:240],
        }
        for item in document_context[:3]
    ]
    filing_instruction = (
        "Use filing claims only when directly supported by the supplied document passages, and cite the exact "
        "supplied locator in the prose as [filename, locator]. Never describe an HTML passage as a PDF page."
        if document_context
        else
        "The SEC filing corpus returned no relevant passages, so do not claim knowledge of revenue, earnings "
        "trends, risk factors, guidance, management statements, or annual-report content."
    )
    financial_instruction = (
        "Use numeric financial claims only from the supplied SEC XBRL facts or deterministic calculations. "
        "Cite XBRL claims with their exact supplied locator as [SEC XBRL, locator]."
        if financial_context
        else
        "No standardized SEC XBRL facts were available, so qualify any numeric financial conclusion."
    )
    generated = _call_local_json_model(
        settings=settings,
        max_output_tokens=400,
        json_schema={
            "type": "object",
            "properties": {
                "answer": {"type": "string"},
                "model_inference": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 3,
                },
            },
            "required": ["answer", "model_inference"],
        },
        prompt=(
            "You are an equity research copilot. Answer only from the supplied market and document context. "
            f"{filing_instruction} {financial_instruction} "
            "If the question needs evidence that is not supplied, state that limitation. "
            "Return JSON only with keys answer (string) and "
            "model_inference (array of at most 3 short strings). Keep facts and interpretation distinct. "
            "Keep the answer under 100 words and return at most 2 brief inferences.\n\n"
            f"Question: {question}\n"
            f"Company context: {json.dumps(model_company_context, default=str)}\n"
            f"Deterministic calculations: {json.dumps(calculations, default=str)}\n"
            f"SEC XBRL financial facts: {json.dumps(model_financial_context or {}, default=str)}\n"
            f"Retrieved document passages: {json.dumps(prompt_documents, default=str)}"
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


def _compact_financial_context(summary: dict[str, Any]) -> dict[str, Any]:
    def compact_period(
        period: dict[str, Any] | None, *, include_locators: bool
    ) -> dict[str, Any] | None:
        if not period:
            return None
        selected_metrics = {}
        for metric in (
            "revenue", "gross_profit", "operating_income", "net_income", "eps_diluted",
            "operating_cash_flow", "assets", "liabilities",
        ):
            fact = period.get("metrics", {}).get(metric)
            if fact:
                selected_metrics[metric] = {
                    "value": fact.get("value"),
                    "unit": fact.get("unit"),
                }
                if include_locators:
                    selected_metrics[metric]["locator"] = fact.get("locator")
        return {
            "end_date": period.get("end_date"),
            "fiscal_year": period.get("fiscal_year"),
            "fiscal_period": period.get("fiscal_period"),
            "metrics": selected_metrics,
            "derived": period.get("derived") if include_locators else None,
        }

    return {
        "latest_annual": compact_period(summary.get("latest_annual"), include_locators=True),
        "previous_annual": compact_period(summary.get("previous_annual"), include_locators=False),
        "annual_changes": summary.get("annual_changes") or {},
        "latest_quarter": compact_period(summary.get("latest_quarter"), include_locators=True),
        "comparable_quarter": compact_period(summary.get("comparable_quarter"), include_locators=False),
        "quarterly_yoy_changes": summary.get("quarterly_yoy_changes") or {},
    }


def _run_sec_financial_tool(symbol: str) -> tuple[dict[str, Any] | None, str | None]:
    from app.services.research_financials import get_sec_financial_summary, sync_sec_companyfacts

    try:
        summary = get_sec_financial_summary(symbol=symbol)
        if not int(summary.get("coverage", {}).get("fact_rows") or 0):
            sync_sec_companyfacts(symbol=symbol)
            summary = get_sec_financial_summary(symbol=symbol)
        return summary, None
    except ResearchError as exc:
        return None, str(exc)


def _format_financial_value(value: Any, unit: str | None) -> str:
    number = _numeric(value)
    if number is None:
        return "unavailable"
    if unit == "USD/shares":
        return f"${number:,.2f} per diluted share"
    if unit == "USD":
        absolute = abs(number)
        if absolute >= 1_000_000_000:
            return f"${number / 1_000_000_000:,.2f} billion"
        if absolute >= 1_000_000:
            return f"${number / 1_000_000:,.2f} million"
        return f"${number:,.0f}"
    return f"{number:,.2f} {unit or ''}".strip()


def _change_phrase(value: Any, *, percentage_points: bool = False) -> str:
    number = _numeric(value)
    if number is None:
        return "with no comparable period available"
    direction = "up" if number >= 0 else "down"
    suffix = " percentage points" if percentage_points else "%"
    return f"{direction} {abs(number):.2f}{suffix} from the comparable period"


def _deterministic_financial_answer(*, summary: dict[str, Any], question: str) -> str:
    latest = summary.get("latest_annual")
    if not latest:
        return "No complete annual SEC XBRL period is available for this company."
    metrics = latest.get("metrics") or {}
    changes = summary.get("annual_changes") or {}
    fiscal_label = f"FY{latest.get('fiscal_year') or ''}".rstrip()
    period_label = f"{fiscal_label} ended {latest.get('end_date')}"
    sentences: list[str] = []
    lower_question = question.lower()
    wants_quarter = any(
        term in lower_question for term in ("quarter", "quarterly", "latest period", "recent results")
    )
    wants_annual = any(term in lower_question for term in ("annual", "year", "fy")) or not wants_quarter
    if wants_annual:
        for metric in ("revenue", "net_income", "eps_diluted", "operating_cash_flow"):
            fact = metrics.get(metric)
            if not fact:
                continue
            sentences.append(
                f"For {period_label}, {str(fact['label']).lower()} was "
                f"{_format_financial_value(fact.get('value'), fact.get('unit'))}, "
                f"{_change_phrase(changes.get(metric))} "
                f"[SEC XBRL, {fact['locator']}]."
            )
        derived = latest.get("derived") or {}
        margin_parts = []
        for metric, label in (
            ("gross_margin_pct", "Gross margin"),
            ("operating_margin_pct", "operating margin"),
            ("net_margin_pct", "net margin"),
        ):
            value = _numeric(derived.get(metric))
            if value is not None:
                margin_parts.append(
                    f"{label} was {value:.2f}% ({_change_phrase(changes.get(metric), percentage_points=True)})"
                )
        if margin_parts:
            revenue_fact = metrics.get("revenue")
            margin_locator = revenue_fact.get("locator") if revenue_fact else period_label
            sentences.append("; ".join(margin_parts) + f" [SEC XBRL calculations, {margin_locator}].")

    if wants_quarter:
        quarter = summary.get("latest_quarter")
        quarter_changes = summary.get("quarterly_yoy_changes") or {}
        if quarter:
            quarter_metrics = quarter.get("metrics") or {}
            for metric in ("revenue", "net_income", "eps_diluted"):
                fact = quarter_metrics.get(metric)
                if not fact:
                    continue
                sentences.append(
                    f"For the quarter ended {quarter.get('end_date')}, {str(fact['label']).lower()} was "
                    f"{_format_financial_value(fact.get('value'), fact.get('unit'))}, "
                    f"{_change_phrase(quarter_changes.get(metric))} "
                    f"[SEC XBRL, {fact['locator']}]."
                )
    return " ".join(sentences)


def _financial_comparison_context(summary: dict[str, Any] | None) -> dict[str, Any] | None:
    if not summary or not summary.get("latest_annual"):
        return None
    latest = summary["latest_annual"]
    metrics = latest.get("metrics") or {}
    return {
        "end_date": latest.get("end_date"),
        "fiscal_year": latest.get("fiscal_year"),
        "metrics": {
            metric: {
                "value": fact.get("value"),
                "unit": fact.get("unit"),
                "locator": fact.get("locator"),
            }
            for metric in ("revenue", "net_income", "eps_diluted")
            if (fact := metrics.get(metric))
        },
        "derived": {
            metric: latest.get("derived", {}).get(metric)
            for metric in ("gross_margin_pct", "operating_margin_pct", "net_margin_pct")
        },
        "annual_changes": {
            metric: summary.get("annual_changes", {}).get(metric)
            for metric in (
                "revenue", "net_income", "eps_diluted", "gross_margin_pct",
                "operating_margin_pct", "net_margin_pct",
            )
        },
    }


def _deterministic_financial_comparison(companies: list[dict[str, Any]]) -> str:
    statements = []
    for item in companies:
        financials = item.get("financials") or {}
        metrics = financials.get("metrics") or {}
        revenue = metrics.get("revenue")
        net_income = metrics.get("net_income")
        if not revenue and not net_income:
            continue
        parts = []
        if revenue:
            parts.append(
                f"revenue {_format_financial_value(revenue.get('value'), revenue.get('unit'))} "
                f"({_change_phrase(financials.get('annual_changes', {}).get('revenue'))}) "
                f"[SEC XBRL, {revenue.get('locator')}]"
            )
        if net_income:
            parts.append(
                f"net income {_format_financial_value(net_income.get('value'), net_income.get('unit'))} "
                f"({_change_phrase(financials.get('annual_changes', {}).get('net_income'))}) "
                f"[SEC XBRL, {net_income.get('locator')}]"
            )
        gross_margin = _numeric(financials.get("derived", {}).get("gross_margin_pct"))
        if gross_margin is not None:
            parts.append(f"gross margin {gross_margin:.2f}%")
        statements.append(
            f"{item['symbol']} FY{financials.get('fiscal_year') or ''} ended "
            f"{financials.get('end_date')}: " + "; ".join(parts) + "."
        )
    return " ".join(statements)


def _question_requires_qualitative_synthesis(question: str) -> bool:
    lower_question = question.lower()
    return any(
        term in lower_question
        for term in (
            "risk", "why", "driver", "management", "strategy", "outlook", "guidance",
            "positioning", "explain", "summar", "investment", "competitive", "product",
            "supply", "regulatory", "language", "commentary",
        )
    )


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
    financial_summary: dict[str, Any] | None = None
    financial_error: str | None = None
    if "sec_financial_facts" in selected_tools:
        financial_summary, financial_error = _run_sec_financial_tool(normalized_symbol)
    financial_context = _compact_financial_context(financial_summary) if financial_summary else None
    deterministic_financial_answer = (
        _deterministic_financial_answer(summary=financial_summary, question=normalized_question)
        if financial_summary and financial_summary.get("latest_annual") else None
    )
    synthesis_error: str | None = None
    if deterministic_financial_answer and not _question_requires_qualitative_synthesis(normalized_question):
        synthesis = {"answer": deterministic_financial_answer, "model_inference": []}
    else:
        try:
            synthesis = _generate_research_synthesis(
                question=normalized_question,
                company=company,
                calculations=calculations,
                document_context=document_context,
                settings=settings,
                financial_context=financial_context,
            )
        except ResearchError as exc:
            if str(exc) not in {"research_model_unavailable", "research_model_invalid_response"}:
                raise
            synthesis_error = str(exc)
            if deterministic_financial_answer:
                synthesis = {"answer": deterministic_financial_answer, "model_inference": []}
            elif document_context:
                synthesis = {
                    "answer": (
                        "AI synthesis is temporarily unavailable. The highest-ranked verified filing "
                        "evidence for this question is shown below."
                    ),
                    "model_inference": [],
                }
            else:
                raise
        if deterministic_financial_answer and not synthesis_error:
            synthesis["model_inference"] = [synthesis["answer"], *synthesis["model_inference"]][:3]
            synthesis["answer"] = deterministic_financial_answer

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
    if financial_summary:
        evidence.extend(financial_summary.get("evidence") or [])

    result = {
        "market": "US",
        "currency": "USD",
        "language": "en",
        "source_provider": ["SEC", "AiStockCN market data"],
        "symbol": normalized_symbol,
        "question": normalized_question,
        "answer": synthesis["answer"],
        "document_evidence": [
            {
                "id": item["chunk_id"],
                "document_id": item["document_id"],
                "claim": item["content"],
                "source": item["filename"],
                "locator": item.get("locator") or f"page {item['page_number']}",
                "locator_type": item.get("locator_type") or "page",
                "page_number": item["page_number"] if item.get("native_page_numbers", True) else None,
                "source_url": item.get("source_url"),
                "reranker_score": item.get("reranker_score"),
            }
            for item in document_context
        ],
        "data_evidence": evidence,
        "financial_evidence": [item for item in evidence if str(item.get("source") or "").startswith("SEC")],
        "model_inference": synthesis["model_inference"],
        "limitations": (
            ["Only the highest-ranked retrieved filing passages were supplied to the model."]
            if document_context
            else ["No relevant indexed filing passages were available; no filing-based claims are included."]
        ) + (
            ["Model synthesis was unavailable; the response was reduced to verified evidence."]
            if synthesis_error else []
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
                    "tool": "sec_financial_facts",
                    "status": "failed" if financial_error else "completed",
                    "detail": financial_error or (
                        f"{financial_summary.get('coverage', {}).get('fact_rows', 0)} canonical SEC XBRL facts"
                    ),
                }]
                if "sec_financial_facts" in selected_tools else []
            ),
            *(
                [{
                    "tool": "hybrid_document_search",
                    "status": "completed",
                    "detail": f"{len(document_context)} reranked passages",
                }]
                if "hybrid_document_search" in selected_tools else []
            ),
            {
                "tool": "evidence_synthesis",
                "status": "degraded" if synthesis_error else "completed",
                "detail": synthesis_error or settings.research_llm_model,
            },
        ],
        "tool_plan": plan,
        "retrieval": retrieval.get("retrieval"),
        "financials": financial_context,
        "model": {"provider": "ollama", "name": settings.research_llm_model},
        "duration_ms": round((time.perf_counter() - started_at) * 1000, 1),
    }
    result["execution_trace"] = result["agent_steps"]
    return result


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
    needs_qualitative_synthesis = _question_requires_qualitative_synthesis(normalized_question)

    companies: list[dict[str, Any]] = []
    document_evidence: list[dict[str, Any]] = []
    financial_evidence: list[dict[str, Any]] = []
    for symbol in normalized_symbols:
        snapshot = get_company_snapshot(symbol=symbol, history_limit=60)
        calculations = _market_calculations(snapshot["history"])
        financial_summary, _ = _run_sec_financial_tool(symbol)
        comparison_financials = _financial_comparison_context(financial_summary)
        companies.append({
            "symbol": symbol,
            "company": snapshot["company"],
            "calculations": calculations,
            "financials": comparison_financials,
        })
        for item in (financial_summary or {}).get("evidence") or []:
            financial_evidence.append({"symbol": symbol, **item})
        if needs_qualitative_synthesis:
            retrieval = _retrieve_document_evidence(symbol=symbol, question=normalized_question)
            for item in list(retrieval.get("results") or [])[:2]:
                document_evidence.append({
                    "symbol": symbol,
                    "id": item["chunk_id"],
                    "document_id": item["document_id"],
                    "claim": item["content"],
                    "source": item["filename"],
                    "locator": item.get("locator") or f"page {item['page_number']}",
                    "locator_type": item.get("locator_type") or "page",
                    "page_number": item["page_number"] if item.get("native_page_numbers", True) else None,
                    "source_url": item.get("source_url"),
                    "reranker_score": item.get("reranker_score"),
                })

    settings = get_settings()
    deterministic_comparison = _deterministic_financial_comparison(companies)
    if deterministic_comparison and not needs_qualitative_synthesis:
        answer = deterministic_comparison
        inference: list[Any] = []
    else:
        generated = _call_local_json_model(
            settings=settings,
            max_output_tokens=240,
            json_schema={
                "type": "object",
                "properties": {
                    "answer": {"type": "string"},
                    "model_inference": {
                        "type": "array",
                        "items": {"type": "string"},
                        "maxItems": 3,
                    },
                },
                "required": ["answer", "model_inference"],
            },
            prompt=(
                "You are an equity comparison agent. Compare only the supplied companies and evidence. "
                "Never invent filing facts. Separate directly observed evidence from interpretation. Return JSON "
                "only with answer (string) and model_inference (array of at most 3 strings). Cite document claims "
                "using the exact supplied locator as [SYMBOL, filename, locator]. Never call an HTML passage a page.\n"
                f"Question: {normalized_question}\n"
                f"Company data and calculations: {json.dumps(companies, default=str)}\n"
                "Document evidence: "
                + json.dumps(
                    [
                        {**item, "claim": str(item.get("claim") or "")[:700]}
                        for item in document_evidence
                    ],
                    default=str,
                )
            ),
        )
        answer = str(generated.get("answer") or "").strip()
        if not answer:
            raise ResearchError("research_model_invalid_response")
        inference = generated.get("model_inference")
        if not isinstance(inference, list):
            inference = []
        if deterministic_comparison:
            inference = [answer, *inference][:3]
            answer = deterministic_comparison
    result = {
        "market": "US",
        "currency": "USD",
        "language": "en",
        "source_provider": ["SEC", "AiStockCN market data"],
        "symbols": normalized_symbols,
        "question": normalized_question,
        "answer": answer,
        "companies": companies,
        "document_evidence": document_evidence,
        "financial_evidence": financial_evidence,
        "model_inference": [str(item).strip() for item in inference if str(item).strip()][:3],
        "agent_steps": [
            {"tool": "comparison_planner", "status": "completed", "detail": ", ".join(normalized_symbols)},
            {"tool": "company_lookup", "status": "completed", "detail": f"{len(companies)} companies"},
            {"tool": "financial_calculator", "status": "completed", "detail": "returns and volatility per company"},
            {"tool": "sec_financial_facts", "status": "completed", "detail": f"{len(financial_evidence)} cited facts"},
            *(
                [{"tool": "hybrid_document_search", "status": "completed", "detail": f"{len(document_evidence)} passages"}]
                if needs_qualitative_synthesis else []
            ),
            {
                "tool": "comparison_synthesis",
                "status": "completed",
                "detail": settings.research_llm_model if needs_qualitative_synthesis else "deterministic financial synthesis",
            },
        ],
        "model": {"provider": "ollama", "name": settings.research_llm_model},
    }
    result["execution_trace"] = result["agent_steps"]
    result["limitations"] = ["Market data can be delayed and this output is research assistance, not investment advice."]
    return result
