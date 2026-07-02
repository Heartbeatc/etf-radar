from __future__ import annotations

from datetime import datetime, timezone

from app.core.market import market_status
from app.domain.models import ActionDecisionItem, ActionDecisionResponse, Position, TradePlan


def build_action_decision_report(plans: list[TradePlan], positions: dict[str, Position]) -> ActionDecisionResponse:
    items = [_decision_for_plan(plan, positions.get(plan.code)) for plan in plans]
    status = _portfolio_action_status(items)
    warnings: list[str] = []
    if any(item.side in {"BUY", "SELL"} for item in items):
        warnings.append("动作信号来自规则和量化分数，不代表成交保证；下单前必须复核实时价格、溢价和仓位。")
    if any(item.confidence == "low" for item in items):
        warnings.append("部分标的信号置信度低，避免自动执行。")
    return ActionDecisionResponse(
        generated_at=datetime.now(timezone.utc),
        scope="fixed_pool",
        market_status=market_status(),
        status=status,
        items=items,
        warnings=warnings,
        assumptions=[
            "第一版动作决策只覆盖固定池ETF。",
            "无持仓时只输出低吸买入、等待或回避；有持仓时输出持有、止盈、减仓或离场。",
            "动态ETF载体必须先进入固定池，才会获得完整动作信号。",
            "系统不自动下单，动作信号用于辅助人工执行。",
        ],
    )


def _decision_for_plan(plan: TradePlan, position: Position | None) -> ActionDecisionItem:
    has_position = position is not None
    action, side, urgency, score, reasons, risks = _action_fields(plan, position)
    return ActionDecisionItem(
        code=plan.code,
        name=plan.name,
        role=plan.role,
        has_position=has_position,
        action=action,
        side=side,
        urgency=urgency,
        confidence=plan.confidence,
        action_score=score,
        signal=plan.signal,
        current_price=plan.current_price,
        entry_price=position.entry_price if position else None,
        buy_zone_low=plan.buy_zone.get("zone_low"),
        buy_zone_high=plan.buy_zone.get("zone_high"),
        avoid_above=plan.buy_zone.get("avoid_above"),
        first_take_profit_price=plan.take_profit_plan.get("first_take_profit_price"),
        second_take_profit_price=plan.take_profit_plan.get("second_take_profit_price"),
        effective_exit_price=plan.exit_plan.get("effective_exit_price"),
        direction_score=plan.direction_score,
        low_buy_score=plan.low_buy_score,
        hold_score=plan.hold_score,
        take_profit_score=plan.take_profit_score,
        risk_score=plan.risk_score,
        reasons=reasons[:8],
        risk_flags=risks[:8],
    )


def _action_fields(plan: TradePlan, position: Position | None) -> tuple[str, str, str, int, list[str], list[str]]:
    reasons = list(plan.evidence[:5])
    risks = list(plan.warnings[:5])
    price = plan.current_price
    zone_low = plan.buy_zone.get("zone_low")
    zone_high = plan.buy_zone.get("zone_high")
    avoid_above = plan.buy_zone.get("avoid_above")

    if plan.data_state != "fresh":
        return "WAIT_DATA", "WAIT", "low", 0, ["行情数据不是fresh"], risks or ["数据质量不允许动作"]
    if price is None or price <= 0:
        return "WAIT_DATA", "WAIT", "low", 0, ["价格无效"], risks or ["缺少有效价格"]

    if position:
        if plan.risk_score >= 80 or plan.signal == "exit_first":
            return "SELL_ALL", "SELL", "high", plan.risk_score, reasons + ["风险分触发离场"], risks
        if plan.take_profit_score >= 80 or plan.signal == "strong_take_profit":
            return "SELL_PARTIAL_50", "SELL", "high", plan.take_profit_score, reasons + ["止盈分达到强止盈区"], risks
        if plan.take_profit_score >= 65 or plan.signal == "partial_take_profit":
            return "SELL_PARTIAL_20_30", "SELL", "medium", plan.take_profit_score, reasons + ["止盈分达到部分止盈区"], risks
        if plan.risk_score >= 55 and plan.hold_score < 60:
            return "REDUCE_OR_HOLD_TIGHT", "SELL", "medium", max(plan.risk_score, 100 - plan.hold_score), reasons + ["持有分转弱且风险抬升"], risks
        if plan.hold_score >= 65:
            return "HOLD", "HOLD", "normal", plan.hold_score, reasons + ["持有条件仍成立"], risks
        return "HOLD_WATCH", "HOLD", "medium", plan.hold_score, reasons + ["持有但需要观察"], risks

    if plan.risk_score >= 75 or plan.signal == "no_trade":
        return "AVOID", "AVOID", "high", plan.risk_score, reasons, risks + ["风险分不允许新开仓"]
    if avoid_above is not None and price > avoid_above:
        return "WAIT_PULLBACK", "WAIT", "medium", plan.low_buy_score, reasons, risks + ["现价高于回避价，不追"]
    if zone_low is not None and zone_high is not None and zone_low <= price <= zone_high and plan.low_buy_score >= 70:
        urgency = "high" if plan.low_buy_score >= 82 else "medium"
        return "BUY_FIRST_BATCH", "BUY", urgency, plan.low_buy_score, reasons + ["价格进入低吸区间"], risks
    if plan.low_buy_score >= 80:
        return "WAIT_BUY_ZONE", "WAIT", "medium", plan.low_buy_score, reasons + ["低吸分高，但价格未到低吸区"], risks
    if plan.low_buy_score >= 65 or plan.signal == "watch_low_buy":
        return "WATCH_LOW_BUY", "WAIT", "normal", plan.low_buy_score, reasons + ["等待回踩进入低吸区"], risks
    return "WAIT", "WAIT", "normal", max(plan.low_buy_score, plan.direction_score), reasons, risks


def _portfolio_action_status(items: list[ActionDecisionItem]) -> str:
    if any(item.action == "SELL_ALL" for item in items):
        return "risk_exit"
    if any(item.side == "SELL" for item in items):
        return "sell_or_reduce"
    if any(item.side == "BUY" for item in items):
        return "buy_available"
    if any(item.action in {"WAIT_BUY_ZONE", "WATCH_LOW_BUY"} for item in items):
        return "wait_low_buy"
    return "wait"
