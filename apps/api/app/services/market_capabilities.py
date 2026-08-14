from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from app.services.model_registry import get_active_deployment
from app.services.us_market import UsMarketError, get_us_model_status


Market = Literal["CN", "US"]


class MarketCapabilityError(ValueError):
    pass


def normalize_market(value: str) -> Market:
    market = str(value or "").strip().upper()
    if market not in {"CN", "US"}:
        raise MarketCapabilityError("unsupported_market")
    return market  # type: ignore[return-value]


def _stage(
    market: Market,
    stage: str,
    status: str,
    mode: str,
    actions: list[str],
    *,
    as_of: str,
    blockers: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "market": market,
        "stage": stage,
        "status": status,
        "mode": mode,
        "as_of": as_of,
        "actions": actions,
        "blockers": blockers or [],
    }


def _deployment(market: Market) -> dict[str, Any] | None:
    try:
        return get_active_deployment(market, sync=False)
    except Exception:
        return None


def get_market_capabilities(value: str) -> dict[str, Any]:
    market = normalize_market(value)
    generated_at = datetime.now(UTC).isoformat()

    if market == "CN":
        deployment = _deployment("CN")
        model = deployment or {}
        validation = str(model.get("validation_status") or "")
        paper_enabled = bool((deployment or {}).get("paper_enabled"))
        quant_live = validation in {"passed", "legacy_unreviewed"}
        execution_live = quant_live and paper_enabled
        stages = [
            _stage("CN", "overview", "live", "market_and_account", ["view_market", "view_account"], as_of=generated_at),
            _stage(
                "CN",
                "research",
                "in_validation",
                "official_disclosures",
                ["search_companies", "open_disclosures"],
                as_of=generated_at,
                blockers=["Chinese retrieval evaluation is still being expanded."],
            ),
            _stage(
                "CN",
                "quant",
                "live" if quant_live else "in_validation",
                "model_and_rules",
                ["view_signals", "inspect_methodology", "explore_data", "view_walk_forward"],
                as_of=str((deployment or {}).get("updated_at") or generated_at),
            ),
            _stage("CN", "portfolio", "live", "broker_and_targets", ["view_positions", "view_pnl", "view_targets"], as_of=generated_at),
            _stage(
                "CN",
                "execution",
                "live" if execution_live else "in_validation",
                "controlled_execution",
                ["view_orders", "view_fills"] + (["control_daemon"] if execution_live else []),
                as_of=str((deployment or {}).get("updated_at") or generated_at),
                blockers=[] if execution_live else ["The active model and paper permission must both pass the registry gate."],
            ),
        ]
    else:
        try:
            model_status = get_us_model_status()
        except (UsMarketError, RuntimeError):
            model_status = {"as_of": generated_at, "gate": {"blockers": ["US market services are unavailable."]}}
        gate = model_status.get("gate") or {}
        training_ready = bool(gate.get("training_ready"))
        walk_forward_ready = bool(gate.get("walk_forward_ready"))
        deployment = _deployment("US")
        as_of = str(model_status.get("as_of") or generated_at)
        model_blockers = [str(item) for item in gate.get("blockers") or []]
        stages = [
            _stage("US", "overview", "live", "market_intelligence", ["view_market", "open_company"], as_of=as_of),
            _stage("US", "research", "live", "source_grounded_research", ["ask_ai", "view_filings", "compare_companies", "review_changes"], as_of=as_of),
            _stage(
                "US",
                "quant",
                "live" if walk_forward_ready else "in_validation",
                "rules_live_model_validation",
                ["view_rule_signals", "inspect_methodology", "explore_data"] + (["view_model_signals", "view_walk_forward"] if training_ready else []),
                as_of=as_of,
                blockers=model_blockers,
            ),
            _stage(
                "US",
                "portfolio",
                "live",
                "research_portfolio",
                ["view_research_basket"] + (["view_backtest_holdings", "view_target_basket"] if training_ready else []),
                as_of=as_of,
                blockers=model_blockers,
            ),
            _stage(
                "US",
                "execution",
                "in_validation",
                "readiness_only",
                ["view_readiness_gates"],
                as_of=as_of,
                blockers=model_blockers + ["US broker order submission is intentionally disabled."],
            ),
        ]

    return {
        "market": market,
        "as_of": generated_at,
        "stages": stages,
        "by_stage": {stage["stage"]: stage for stage in stages},
    }
