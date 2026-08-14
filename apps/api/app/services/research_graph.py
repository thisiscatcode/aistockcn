from __future__ import annotations

import operator
import time
from typing import Annotated, Any

from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from app.services.research import answer_research_question, plan_research_tools
from app.services.research_citations import validate_research_citations


GRAPH_VERSION = "research_graph_v1"


class ResearchGraphState(TypedDict, total=False):
    symbol: str
    question: str
    supplied_plan: dict[str, Any] | None
    tool_plan: dict[str, Any]
    result: dict[str, Any]
    trace: Annotated[list[dict[str, Any]], operator.add]


def _trace_event(
    *, node: str, started_at: float, detail: str, status: str = "completed"
) -> dict[str, Any]:
    return {
        "node": node,
        "status": status,
        "duration_ms": round((time.perf_counter() - started_at) * 1000, 1),
        "detail": detail,
    }


def plan_node(state: ResearchGraphState) -> dict[str, Any]:
    started_at = time.perf_counter()
    plan = state.get("supplied_plan") or plan_research_tools(question=state["question"])
    tools = [str(item) for item in plan.get("tools") or []]
    event = _trace_event(
        node="plan",
        started_at=started_at,
        detail=f"{plan.get('planner')}: {', '.join(tools)}",
    )
    if state.get("supplied_plan") and plan.get("planner_duration_ms") is not None:
        event["duration_ms"] = round(float(plan["planner_duration_ms"]), 1)
    return {
        "tool_plan": plan,
        "trace": [event],
    }


def execute_node(state: ResearchGraphState) -> dict[str, Any]:
    started_at = time.perf_counter()
    result = answer_research_question(
        symbol=state["symbol"],
        question=state["question"],
        tool_plan=state["tool_plan"],
    )
    return {
        "result": result,
        "trace": [
            _trace_event(
                node="execute_tools_and_synthesize",
                started_at=started_at,
                detail=(
                    f"{len(result.get('agent_steps') or [])} tool steps · "
                    f"{len(result.get('document_evidence') or [])} document passages"
                ),
            )
        ],
    }


def validate_node(state: ResearchGraphState) -> dict[str, Any]:
    started_at = time.perf_counter()
    result = dict(state["result"])
    degraded = any(
        str(step.get("status")) == "degraded"
        for step in result.get("agent_steps") or []
    )
    validation = validate_research_citations(result=result, synthesis_degraded=degraded)
    result["citation_validation"] = validation
    return {
        "result": result,
        "trace": [
            _trace_event(
                node="validate_citations",
                started_at=started_at,
                detail=(
                    f"{validation['status']} · {validation['cited_document_citations']} cited / "
                    f"{validation['available_document_citations']} available"
                ),
                status="completed" if validation["status"] in {"passed", "warning"} else validation["status"],
            )
        ],
    }


def build_research_graph():
    builder = StateGraph(ResearchGraphState)
    builder.add_node("plan", plan_node)
    builder.add_node("execute_tools_and_synthesize", execute_node)
    builder.add_node("validate_citations", validate_node)
    builder.add_edge(START, "plan")
    builder.add_edge("plan", "execute_tools_and_synthesize")
    builder.add_edge("execute_tools_and_synthesize", "validate_citations")
    builder.add_edge("validate_citations", END)
    return builder.compile()


RESEARCH_GRAPH = build_research_graph()


def run_research_graph(
    *, symbol: str, question: str, tool_plan: dict[str, Any] | None = None
) -> dict[str, Any]:
    final_state = RESEARCH_GRAPH.invoke(
        {
            "symbol": symbol,
            "question": question,
            "supplied_plan": tool_plan,
            "trace": [],
        }
    )
    result = dict(final_state["result"])
    graph_trace = list(final_state.get("trace") or [])
    result["graph"] = {
        "framework": "LangGraph",
        "version": GRAPH_VERSION,
        "nodes": ["plan", "execute_tools_and_synthesize", "validate_citations"],
    }
    result["graph_trace"] = graph_trace
    result["duration_ms"] = round(
        sum(float(item.get("duration_ms") or 0) for item in graph_trace), 1
    )
    return result
