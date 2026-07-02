from __future__ import annotations

from datetime import datetime, timezone

from app.domain.models import RiskItem, RiskReport, TradePlan


def build_risk_report(plans: list[TradePlan]) -> RiskReport:
    items: list[RiskItem] = []
    for plan in plans:
        level = _level(plan.risk_score, plan.take_profit_score, plan.warnings)
        items.append(
            RiskItem(
                code=plan.code,
                name=plan.name,
                signal=plan.signal,
                current_price=plan.current_price,
                risk_score=plan.risk_score,
                risk_level=level,
                take_profit_score=plan.take_profit_score,
                take_profit_action=str(plan.take_profit_plan.get("action")),
                hard_stop_price=plan.exit_plan.get("hard_stop_price"),
                trend_exit_price=plan.exit_plan.get("trend_exit_price"),
                effective_exit_price=plan.exit_plan.get("effective_exit_price"),
                warnings=plan.warnings,
            )
        )
    high = sum(1 for item in items if item.risk_level in {"high", "critical"})
    state = "normal"
    if high >= 2:
        state = "risk_off"
    elif high == 1:
        state = "watch"
    return RiskReport(
        generated_at=datetime.now(timezone.utc),
        risk_budget_state=state,
        high_risk_count=high,
        items=items,
        rules=[
            "Do not add when risk_level is high or critical.",
            "Treat effective_exit_price as a defense/invalid line before considering new low-buy entries.",
            "When take_profit_score >= 65, protect gains before chasing direction.",
            "AI explanations are secondary; rule evidence and source quality dominate.",
        ],
    )


def _level(risk_score: int, take_profit_score: int, warnings: list[str]) -> str:
    if risk_score >= 80:
        return "critical"
    if risk_score >= 65 or len(warnings) >= 3:
        return "high"
    if risk_score >= 45 or take_profit_score >= 65:
        return "medium"
    return "low"
