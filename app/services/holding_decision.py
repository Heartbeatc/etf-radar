from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.domain.models import (
    MarketDirection,
    MarketFlowResponse,
    Position,
    QuantHoldingDecision,
    QuantStockExecutionCondition,
    TradePlan,
)

CN_TZ = timezone(timedelta(hours=8))


def build_holding_decisions(
    market_flow: MarketFlowResponse,
    positions: dict[str, Position],
    plans: list[TradePlan],
) -> list[QuantHoldingDecision]:
    plan_by_code = {plan.code: plan for plan in plans}
    result = [_holding_decision(market_flow, position, plan_by_code.get(code)) for code, position in positions.items()]
    result.sort(key=_holding_sort_key)
    return result


def _holding_decision(market_flow: MarketFlowResponse, position: Position, plan: TradePlan | None) -> QuantHoldingDecision:
    if plan is None:
        return QuantHoldingDecision(
            code=position.code,
            name=position.code,
            entry_price=position.entry_price,
            entry_date=position.entry_date,
            shares=position.shares,
            updated_at=position.updated_at,
            action="WAIT_DATA",
            action_label="等行情",
            urgency="low",
            risk_level="unknown",
            main_force_state="unknown",
            direction_match="unknown",
            position_plan="持仓已记录，等待下一轮行情采集后再计算。",
            exit_plan="无实时价格时不做动作。",
            reasons=["持仓已登记"],
            risk_flags=["缺少实时行情，禁止动作"],
        )

    direction, match = _related_direction(market_flow, plan.code)
    price = plan.current_price
    pnl_pct = _pnl_pct(price, position.entry_price)
    pnl_amount = _pnl_amount(price, position.entry_price, position.shares)
    market_value = _market_value(price, position.shares)
    fallback_stop = _fallback_stop(position.entry_price)
    raw_stop = _first_number(plan.exit_plan.get("hard_stop_price"))
    stop_price = min(raw_stop, fallback_stop) if raw_stop is not None else fallback_stop
    weak_exit_price = _first_number(plan.exit_plan.get("effective_exit_price"), raw_stop, stop_price)
    take_profit_price = _first_number(plan.take_profit_plan.get("first_take_profit_price"))
    rebound_reduce_price = _rebound_reduce_price(position.entry_price, price)
    sellable, tplus_reason = _t_plus_state(position)
    main_force_state = _main_force_state(plan, direction, match)
    action, action_label, urgency, risk_level = _holding_action(
        plan=plan,
        pnl_pct=pnl_pct,
        price=price,
        stop_price=stop_price,
        weak_exit_price=weak_exit_price,
        take_profit_price=take_profit_price,
        main_force_state=main_force_state,
        sellable=sellable,
    )
    can_add = _can_add_position(plan, pnl_pct, main_force_state, match, action)
    conditions = _conditions(plan, pnl_pct, price, stop_price, weak_exit_price, main_force_state, match, sellable, tplus_reason)
    position_plan, exit_plan = _plans(action, sellable, weak_exit_price, rebound_reduce_price, stop_price)
    reasons = _dedupe([
        f"持仓成本 {position.entry_price:.2f}",
        f"浮盈亏 {pnl_pct:.2f}%" if pnl_pct is not None else "暂无有效现价",
        _match_reason(match, direction),
        *plan.evidence[:3],
    ])
    risk_flags = _dedupe([
        *plan.warnings[:4],
        *(["当前不允许补仓"] if not can_add else []),
        *(["T+1或交易时段限制：先计划，等可卖时执行"] if not sellable else []),
        *(["浮亏超过3%，优先风控而不是摊低成本"] if pnl_pct is not None and pnl_pct <= -3 else []),
        *(["个股不在当前前排方向，不能按主线持仓处理"] if match == "not_frontline" else []),
    ])
    return QuantHoldingDecision(
        code=plan.code,
        name=plan.name,
        entry_price=position.entry_price,
        entry_date=position.entry_date,
        shares=position.shares,
        current_price=price,
        source_time=plan.source_time,
        updated_at=position.updated_at,
        floating_profit_pct=_round_pct(pnl_pct),
        floating_profit_amount=_round_money(pnl_amount),
        market_value=_round_money(market_value),
        action=action,
        action_label=action_label,
        urgency=urgency,
        risk_level=risk_level,
        main_force_state=main_force_state,
        direction_match=match,
        related_direction_label=direction.direction_label if direction else None,
        can_add_position=can_add,
        stop_price=_round_price(stop_price),
        weak_exit_price=_round_price(weak_exit_price),
        rebound_reduce_price=_round_price(rebound_reduce_price),
        take_profit_price=_round_price(take_profit_price),
        position_plan=position_plan,
        exit_plan=exit_plan,
        conditions=conditions,
        reasons=reasons[:8],
        risk_flags=risk_flags[:8],
    )


def _holding_action(
    *,
    plan: TradePlan,
    pnl_pct: float | None,
    price: float | None,
    stop_price: float | None,
    weak_exit_price: float | None,
    take_profit_price: float | None,
    main_force_state: str,
    sellable: bool,
) -> tuple[str, str, str, str]:
    if plan.data_state != "fresh" or price is None:
        return "WAIT_DATA", "等行情", "low", "unknown"
    if take_profit_price is not None and price >= take_profit_price and pnl_pct is not None and pnl_pct > 0:
        return "TAKE_PROFIT", "止盈", "medium", "medium"
    stop_broken = stop_price is not None and price < stop_price
    weak_broken = weak_exit_price is not None and price < weak_exit_price
    if stop_broken or plan.signal == "exit_first" or plan.risk_score >= 80:
        return "EXIT", "计划离场" if not sellable else "离场", "high", "high"
    if weak_broken or (pnl_pct is not None and pnl_pct <= -4.0) or main_force_state == "left":
        return "REDUCE_OR_EXIT", "计划减仓" if not sellable else "减仓/离场", "high", "high"
    if pnl_pct is not None and pnl_pct <= -2.5 and main_force_state in {"weak", "unknown"}:
        return "REDUCE_ON_REBOUND", "计划反抽减亏" if not sellable else "等反抽减亏", "medium", "medium"
    if plan.take_profit_score >= 65 and pnl_pct is not None and pnl_pct > 0:
        return "TAKE_PROFIT", "止盈", "medium", "medium"
    if plan.hold_score >= 65 and main_force_state in {"present", "watch"}:
        return "HOLD", "持有", "normal", "low"
    return "HOLD_TIGHT", "收紧持仓", "medium", "medium"


def _conditions(
    plan: TradePlan,
    pnl_pct: float | None,
    price: float | None,
    stop_price: float | None,
    weak_exit_price: float | None,
    main_force_state: str,
    match: str,
    sellable: bool,
    tplus_reason: str,
) -> list[QuantStockExecutionCondition]:
    return [
        _condition("sellable", "T+1", "passed" if sellable else "pending", "可卖" if sellable else "受限", "买入次一交易日才能卖", tplus_reason),
        _condition("pnl", "浮盈亏", _pnl_status(pnl_pct), "-" if pnl_pct is None else f"{pnl_pct:.2f}%", "亏损不超过3%或已转强", _pnl_reason(pnl_pct)),
        _condition("main_force", "主力承接", "passed" if main_force_state == "present" else "pending" if main_force_state == "watch" else "failed", main_force_state, "承接在，风险分低", _main_force_reason(main_force_state)),
        _condition("direction", "方向匹配", "passed" if match == "frontline" else "pending" if match == "related" else "failed", match, "持仓属于当前前排方向", _match_status_reason(match)),
        _condition("price_guard", "价格防线", _guard_status(price, weak_exit_price, stop_price), _guard_value(price, weak_exit_price, stop_price), "不跌破弱防线/硬止损", _guard_reason(price, weak_exit_price, stop_price)),
        _condition("risk_score", "风险分", "passed" if plan.risk_score < 55 else "pending" if plan.risk_score < 75 else "failed", str(plan.risk_score), "风险分<55", f"当前风险分 {plan.risk_score}"),
    ]


def _plans(action: str, sellable: bool, weak_exit: float | None, rebound: float | None, stop: float | None) -> tuple[str, str]:
    weak = "-" if weak_exit is None else f"{weak_exit:.2f}"
    rebound_text = "-" if rebound is None else f"{rebound:.2f}"
    stop_text = "-" if stop is None else f"{stop:.2f}"
    if action == "EXIT":
        return "不补仓；优先处理风险。", f"跌破硬防守或风险失败，{'等可卖后' if not sellable else ''}执行离场纪律；硬防守 {stop_text}。"
    if action == "REDUCE_OR_EXIT":
        return "不补仓；先降风险。", f"若不能重新站回弱防线 {weak}，减仓或离场；跌破 {stop_text} 不再等反抽。"
    if action == "REDUCE_ON_REBOUND":
        return "不补仓；等反抽减亏。", f"反抽到 {rebound_text} 附近但量能/主力不回流，先减亏；跌破 {weak} 直接降仓。"
    if action == "TAKE_PROFIT":
        return "不加仓；先兑现部分利润。", "达到止盈区，分批兑现，留底仓跟踪方向。"
    if action == "HOLD":
        return "持有为主；只有盈利且主力继续回流才考虑极小幅滚动。", f"守弱防线 {weak}，跌破后从持有切到减仓。"
    if action == "WAIT_DATA":
        return "等行情，不操作。", "行情缺失时不做交易判断。"
    return "只拿原仓，不补仓。", f"收紧到弱防线 {weak}；反抽到 {rebound_text} 仍不转强则减仓。"


def _main_force_state(plan: TradePlan, direction: MarketDirection | None, match: str) -> str:
    if plan.data_state != "fresh":
        return "unknown"
    if plan.risk_score >= 80 or plan.signal == "exit_first":
        return "left"
    if plan.risk_score >= 60 and plan.hold_score < 60:
        return "weak"
    if match == "frontline" and direction and direction.retention_score >= 60 and plan.hold_score >= 65:
        return "present"
    if plan.hold_score >= 60 and plan.risk_score < 65:
        return "watch"
    return "weak"


def _can_add_position(plan: TradePlan, pnl_pct: float | None, main_force_state: str, match: str, action: str) -> bool:
    return action == "HOLD" and match == "frontline" and main_force_state == "present" and plan.risk_score < 45 and pnl_pct is not None and pnl_pct >= 0


def _related_direction(market_flow: MarketFlowResponse, code: str) -> tuple[MarketDirection | None, str]:
    top = market_flow.directions[0] if market_flow.directions else None
    related = None
    for direction in market_flow.directions:
        if any(stock.code == code for stock in direction.linked_stocks):
            related = direction
            break
    if related is None:
        return None, "not_frontline"
    if top and related.direction_key == top.direction_key:
        return related, "frontline"
    return related, "related"


def _t_plus_state(position: Position) -> tuple[bool, str]:
    if not position.entry_date:
        return True, "未记录买入日，按已可卖处理"
    today = datetime.now(CN_TZ).date().isoformat()
    if position.entry_date >= today:
        return False, "今日买入，A股T+1限制；只能先制定下个交易日风控计划"
    return True, "买入日早于今天，可按规则卖出"


def _condition(key: str, label: str, status: str, value: str, threshold: str, reason: str) -> QuantStockExecutionCondition:
    return QuantStockExecutionCondition(key=key, label=label, status=status, value=value, threshold=threshold, reason=reason)


def _pnl_pct(price: float | None, entry: float) -> float | None:
    if price is None or entry <= 0:
        return None
    return (price / entry - 1) * 100


def _pnl_amount(price: float | None, entry: float, shares: float | None) -> float | None:
    if price is None or shares is None:
        return None
    return (price - entry) * shares


def _market_value(price: float | None, shares: float | None) -> float | None:
    if price is None or shares is None:
        return None
    return price * shares


def _fallback_stop(entry: float) -> float:
    return entry * 0.96


def _rebound_reduce_price(entry: float, price: float | None) -> float | None:
    if price is None or price >= entry:
        return None
    return min(entry * 0.995, price + (entry - price) * 0.45)


def _first_number(*values: float | None) -> float | None:
    for value in values:
        if value is not None:
            return float(value)
    return None


def _pnl_status(pnl: float | None) -> str:
    if pnl is None:
        return "pending"
    if pnl <= -4:
        return "failed"
    if pnl <= -2:
        return "pending"
    return "passed"


def _pnl_reason(pnl: float | None) -> str:
    if pnl is None:
        return "缺少现价"
    if pnl <= -4:
        return "亏损已进入强风控区"
    if pnl <= -2:
        return "亏损需要盯反抽和防线，不补仓"
    return "亏损仍可控或已有盈利"


def _main_force_reason(state: str) -> str:
    return {
        "present": "承接仍在，允许继续观察持有",
        "watch": "承接未完全坏，但不能加仓",
        "weak": "承接走弱，优先防守",
        "left": "风险条件显示主力可能撤退",
        "unknown": "数据不足，不能判断主力",
    }.get(state, state)


def _match_reason(match: str, direction: MarketDirection | None) -> str:
    if match == "frontline" and direction:
        return f"属于当前前排方向 {direction.direction_label}"
    if match == "related" and direction:
        return f"只属于非第一方向 {direction.direction_label}"
    return "不在当前前排方向样本内"


def _match_status_reason(match: str) -> str:
    if match == "frontline":
        return "持仓仍在当前前排方向内"
    if match == "related":
        return "持仓方向不是第一方向，按降级持仓处理"
    return "持仓没有被当前方向验证"


def _guard_status(price: float | None, weak: float | None, stop: float | None) -> str:
    if price is None:
        return "pending"
    if stop is not None and price < stop:
        return "failed"
    if weak is not None and price < weak:
        return "pending"
    return "passed"


def _guard_value(price: float | None, weak: float | None, stop: float | None) -> str:
    return f"现价{_text_price(price)} / 弱{_text_price(weak)} / 止损{_text_price(stop)}"


def _guard_reason(price: float | None, weak: float | None, stop: float | None) -> str:
    if price is None:
        return "缺少现价"
    if stop is not None and price < stop:
        return "跌破硬止损"
    if weak is not None and price < weak:
        return "跌破弱防线，必须等待快速收回，否则降仓"
    return "价格仍在防线之上"


def _text_price(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f}"


def _holding_sort_key(item: QuantHoldingDecision) -> tuple[int, str]:
    order = {"EXIT": 0, "REDUCE_OR_EXIT": 1, "REDUCE_ON_REBOUND": 2, "TAKE_PROFIT": 3, "HOLD_TIGHT": 4, "HOLD": 5, "WAIT_DATA": 6}
    return (order.get(item.action, 9), item.code)


def _round_price(value: float | None) -> float | None:
    return None if value is None else round(value, 2)


def _round_pct(value: float | None) -> float | None:
    return None if value is None else round(value, 2)


def _round_money(value: float | None) -> float | None:
    return None if value is None else round(value, 2)


def _dedupe(items: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result
