from __future__ import annotations

from datetime import datetime, timezone

from app.core.market import market_status
from app.domain.models import ActionDecisionItem, ActionDecisionResponse, Position, TradePlan


def build_action_decision_report(plans: list[TradePlan], positions: dict[str, Position]) -> ActionDecisionResponse:
    items = [_decision_for_plan(plan, positions.get(plan.code)) for plan in plans]
    planned_codes = {plan.code for plan in plans}
    for code, position in positions.items():
        if code not in planned_codes:
            items.append(_missing_position_decision(code, position))
    status = _portfolio_action_status(items)
    warnings: list[str] = []
    if any(item.side in {"BUY", "SELL"} for item in items):
        warnings.append("动作信号来自规则和量化分数，不代表成交保证；下单前必须复核实时价格、溢价和仓位。")
    if any(item.confidence == "low" for item in items):
        warnings.append("部分标的信号置信度低，避免自动执行。")
    if any(item.action == "WAIT_DATA" and item.has_position for item in items):
        warnings.append("有持仓尚未拿到最新行情；等待下一轮采集后再执行动作。")
    return ActionDecisionResponse(
        generated_at=datetime.now(timezone.utc),
        scope="fixed_pool_plus_positions",
        market_status=market_status(),
        status=status,
        items=items,
        warnings=warnings,
        assumptions=[
            "动作决策覆盖固定池ETF和用户已登记持仓。",
            "空仓时只输出首仓、等待低吸区或回避；首仓默认不超过20%。",
            "有持仓时优先输出持有、止盈、减仓或离场，并显示浮盈和建议处理比例。",
            "动态ETF候选未进入固定池且未登记为持仓前，只作为开仓候选，不生成完整买卖点。",
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
        position_shares=position.shares if position else None,
        floating_profit_pct=plan.hold_plan.get("floating_profit_pct") if position else None,
        suggested_position_pct=_suggested_position_pct(action),
        execution_note=_execution_note(action, position),
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


def _missing_position_decision(code: str, position: Position) -> ActionDecisionItem:
    return ActionDecisionItem(
        code=code,
        name=code,
        role="position",
        has_position=True,
        action="WAIT_DATA",
        side="WAIT",
        urgency="low",
        confidence="low",
        action_score=0,
        signal="wait_data",
        current_price=None,
        entry_price=position.entry_price,
        position_shares=position.shares,
        floating_profit_pct=None,
        suggested_position_pct=None,
        execution_note="持仓已记录，等待下一轮行情采集后再计算动作。",
        direction_score=0,
        low_buy_score=0,
        hold_score=0,
        take_profit_score=0,
        risk_score=0,
        reasons=["持仓已登记"],
        risk_flags=["未获取到该持仓最新行情，禁止动作"],
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


def _suggested_position_pct(action: str) -> int | None:
    mapping = {
        "BUY_FIRST_BATCH": 20,
        "SELL_PARTIAL_50": 50,
        "SELL_PARTIAL_20_30": 30,
        "SELL_ALL": 100,
        "REDUCE_OR_HOLD_TIGHT": 20,
    }
    return mapping.get(action)


def _execution_note(action: str, position: Position | None) -> str:
    if action == "BUY_FIRST_BATCH":
        return "空仓首仓不超过20%，只在低吸区内分批执行。"
    if action == "WAIT_BUY_ZONE":
        return "方向可跟踪，但价格未触发；空仓继续等低吸区。"
    if action == "WATCH_LOW_BUY":
        return "只观察，不追涨；回踩且数据质量通过后再评估首仓。"
    if action == "WAIT_PULLBACK":
        return "现价偏高，等待回落到低吸区。"
    if action == "SELL_ALL":
        return "风险触发，按纪律优先离场。"
    if action == "SELL_PARTIAL_50":
        return "强止盈信号，建议先兑现约50%。"
    if action == "SELL_PARTIAL_20_30":
        return "部分止盈信号，建议兑现20-30%。"
    if action == "REDUCE_OR_HOLD_TIGHT":
        return "持仓转弱，减仓约20%或收紧防守线。"
    if action == "HOLD":
        return "继续持有，按防守线和止盈线跟踪。"
    if action == "HOLD_WATCH":
        return "持有但不加仓，观察承接和防守线。"
    if action == "WAIT_DATA":
        return "等待行情数据恢复后再动作。"
    if action == "AVOID":
        return "不符合低吸和风控条件，回避新开仓。"
    if position:
        return "已有持仓，继续按持有/风控规则跟踪。"
    return "空仓等待更清晰的低吸触发。"


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
