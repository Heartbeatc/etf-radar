from __future__ import annotations

from datetime import datetime, timezone

from app.core.market import market_clock
from app.domain.models import (
    ActionDecisionItem,
    ActionDecisionResponse,
    MarketDirection,
    MarketFlowResponse,
    MarketStockCandidate,
    PoolRecommendationItem,
    PoolRecommendationResponse,
    Position,
    QuantDecisionResponse,
    QuantDirectionDecision,
    QuantEtfDecision,
    QuantHoldingDecision,
    QuantStockDecision,
    QuantStockExecutionCondition,
    QuantStockExecutionPlan,
    TradePlan,
)
from app.services.holding_decision import build_holding_decisions


def build_quant_decision_report(
    market_flow: MarketFlowResponse,
    pool: PoolRecommendationResponse | None = None,
    actions: ActionDecisionResponse | None = None,
    positions: dict[str, Position] | None = None,
    plans: list[TradePlan] | None = None,
) -> QuantDecisionResponse:
    top_direction = market_flow.directions[0] if market_flow.directions else None
    direction_decision = _direction_decision(top_direction)
    etfs = _etf_decisions(pool, actions) if pool is not None and actions is not None else []
    stocks = _stock_decisions(top_direction)
    bottom_candidates = _bottom_candidates(stocks)
    holdings: list[QuantHoldingDecision] = build_holding_decisions(market_flow, positions or {}, plans or []) if positions else []
    fixed_actions = [_fixed_action_decision(item) for item in actions.items] if actions is not None else []
    conclusion = _conclusion(direction_decision, stocks, fixed_actions, holdings)
    clock = market_clock()
    generated_at = datetime.now(timezone.utc)
    data_time = _latest_data_time(market_flow, plans or [], stocks, holdings)
    data_age_seconds = round((generated_at - data_time).total_seconds(), 2) if data_time else None
    warnings = [*market_flow.warnings[:4]]
    if top_direction and top_direction.state != "confirmed_mainline":
        warnings.insert(0, "当前方向不是确认主升，A股操作以等待回踩和验证承接为主。")
    if top_direction and not top_direction.linked_stocks:
        warnings.insert(0, "当前方向缺少龙头/二龙头样本，不能给个股候选动作。")
    return QuantDecisionResponse(
        generated_at=generated_at,
        server_time=clock.market_time,
        data_time=data_time,
        data_age_seconds=data_age_seconds,
        market_status=clock.status,
        market_status_label=clock.status_label,
        is_trading_day=clock.is_trading_day,
        should_poll_realtime=clock.should_poll_realtime,
        last_trading_day=clock.last_trading_day,
        next_trading_day=clock.next_trading_day,
        market_note=clock.note,
        conclusion=conclusion,
        direction=direction_decision,
        etfs=etfs,
        stocks=stocks,
        bottom_candidates=bottom_candidates,
        holdings=holdings,
        fixed_pool_actions=fixed_actions,
        warnings=_dedupe(warnings)[:8],
        assumptions=[
            "当前为A股个股聚焦模式：先识别市场资金方向，再筛方向内龙头、二龙头和扩散股。",
            "龙头/二龙头来自方向内成分股的涨幅、成交额、量比、资金流代理和带动性排序。",
            "个股候选会输出估算低吸区、触发信号、防守价和止盈参考；缺少Level-2时只能小仓试错，不自动下单。",
            "主升确认需要至少3个交易日的驻留样本、承接、扩散和反证过滤；单日热点不等于主升。",
        ],
    )


def _latest_data_time(
    market_flow: MarketFlowResponse,
    plans: list[TradePlan],
    stocks: list[QuantStockDecision],
    holdings: list[QuantHoldingDecision],
) -> datetime | None:
    values: list[datetime] = []
    for plan in plans:
        if plan.source_time is not None:
            values.append(plan.source_time)
        elif plan.fetched_at is not None:
            values.append(plan.fetched_at)
    for stock in stocks:
        if stock.source_time is not None:
            values.append(stock.source_time)
    for holding in holdings:
        if holding.source_time is not None:
            values.append(holding.source_time)
    return max((_as_utc(value) for value in values), default=None)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _direction_decision(direction: MarketDirection | None) -> QuantDirectionDecision:
    if direction is None:
        return QuantDirectionDecision(
            phase="no_direction",
            phase_label="无主线",
            phase_score=0,
            confidence="low",
            operation="等待，不开新仓。",
            evidence=[],
            risk_flags=["没有可用市场流向数据"],
        )
    phase, label, confidence, operation = _phase(direction)
    evidence = [
        f"7日方向 {direction.factor_scores.get('seven_day_score', 0)}",
        f"主线概率 {direction.mainline_probability}",
        f"资金驻留 {direction.residency_score}",
        f"承接 {direction.retention_score}",
        f"强股确认 {direction.factor_scores.get('stock_confirmation', direction.stock_confirmation_score)}",
        f"历史天数 {direction.factor_scores.get('history_days', 0)}",
        f"驻留持续 {direction.factor_scores.get('persistence', 0)}",
        f"脉冲风险 {direction.factor_scores.get('impulse_risk', 0)}",
        f"低吸适配 {direction.low_buy_readiness_score}",
    ] + direction.evidence[:4]
    return QuantDirectionDecision(
        direction_key=direction.direction_key,
        direction_label=direction.direction_label,
        phase=phase,
        phase_label=label,
        phase_score=direction.mainline_probability,
        confidence=confidence,
        operation=operation,
        mainline_probability=direction.mainline_probability,
        seven_day_score=direction.factor_scores.get("seven_day_score"),
        residency_score=direction.residency_score,
        retention_score=direction.retention_score,
        low_buy_readiness_score=direction.low_buy_readiness_score,
        evidence=evidence[:8],
        risk_flags=direction.risk_flags[:8],
    )


def _phase(direction: MarketDirection) -> tuple[str, str, str, str]:
    if direction.state == "confirmed_mainline" and direction.low_buy_readiness_score >= 65:
        return "main_up_low_buy", "主升低吸段", "high", "允许围绕方向龙头/二龙头等待低吸确认，不追高。"
    if direction.state == "confirmed_mainline":
        return "main_up_hold", "主升持有段", "high", "方向处于主升，已有个股按趋势持有/止盈规则执行，新仓等回踩。"
    if direction.state == "candidate":
        return "candidate", "方向候选段", "medium-low", "先验证多日驻留以及龙头/二龙头承接，个股只等回踩承接。"
    if direction.state == "hot_today":
        return "hot_today", "单日爆发段", "medium-low", "观察次日承接，禁止追高个股。"
    if direction.state == "overheated":
        return "overheated", "加速过热段", "medium-low", "不追高，等回落或止盈。"
    if direction.state == "weakening":
        return "weakening", "退潮弱化段", "low", "回避新开仓，已有仓位按风控减仓。"
    if direction.state == "weak_direction":
        return "weak", "弱方向", "low", "等待，不参与。"
    return "watch", "观察震荡段", "medium-low", "观察，不做主动买入。"


def _stock_decisions(direction: MarketDirection | None) -> list[QuantStockDecision]:
    if direction is None:
        return []
    stocks = direction.linked_stocks[:6]
    if not stocks and direction.representative_stock:
        stocks = [direction.representative_stock]
    result: list[QuantStockDecision] = []
    for stock in stocks:
        base_action, operation, risks = _stock_action(direction, stock)
        execution = _stock_execution_plan(direction, stock, base_action, risks)
        action = _stock_final_action(base_action, execution)
        bottom_score, bottom_state, bottom_label = _bottom_profile(direction, stock, execution, action)
        result.append(
            QuantStockDecision(
                code=stock.code,
                name=stock.name,
                action=action,
                operation=operation,
                score=stock.score,
                bottom_score=bottom_score,
                bottom_state=bottom_state,
                bottom_label=bottom_label,
                direction_label=direction.direction_label,
                board_name=stock.board_name,
                verifier_role=stock.verifier_role,
                price=stock.price,
                change_pct=stock.change_pct,
                amount=stock.amount,
                volume_ratio=stock.volume_ratio,
                main_net_inflow=stock.main_net_inflow,
                main_net_inflow_pct=stock.main_net_inflow_pct,
                source_time=stock.source_time,
                execution=execution,
                reasons=(stock.evidence[:5] or ["方向龙头/二龙头候选"]),
                risk_flags=_dedupe([*stock.risk_flags[:5], *risks, *execution.blockers])[:8],
            )
        )
    result.sort(key=lambda item: item.score, reverse=True)
    return result[:6]


def _stock_action(direction: MarketDirection, stock: MarketStockCandidate) -> tuple[str, str, list[str]]:
    risks: list[str] = []
    change = stock.change_pct if stock.change_pct is not None else 0.0
    inflow_pct = stock.main_net_inflow_pct if stock.main_net_inflow_pct is not None else 0.0
    if direction.state in {"weakening", "weak_direction"}:
        return "AVOID", "方向弱化或无主线，不做个股开仓。", ["方向阶段不支持个股参与"]
    if change >= 9:
        return "DO_NOT_CHASE", "方向龙头/二龙头已明显加速，只看承接，不追涨。", ["接近涨停或短线加速"]
    if change >= 6:
        return "WAIT_PULLBACK", "个股偏热，等回踩后仍有资金承接再观察。", ["短线涨幅偏高"]
    if inflow_pct < -5:
        return "VERIFY_ONLY", "个股资金流代理偏弱，只能验证方向，暂不作为低吸候选。", ["个股主力资金代理为净流出"]
    if direction.state == "confirmed_mainline" and stock.score >= 72 and direction.low_buy_readiness_score >= 60:
        return "WATCH_LOW_BUY", "主线内龙头/二龙头，等待回踩不破分时均价/关键均线并重新放量承接。", []
    if direction.state == "candidate" and stock.score >= 68:
        return "WATCH_LOW_BUY", "方向候选内龙头/二龙头，等次日/回踩承接确认；未确认前不主动追。", ["方向仍是候选段"]
    if direction.state == "hot_today":
        return "OBSERVE_NEXT_DAY", "单日热点个股，至少等下一交易日承接确认。", ["单日热点不能确认资金驻留"]
    if stock.score >= 65:
        return "VERIFY_DIRECTION", "作为方向强弱验证股，等待更明确阶段。", []
    return "WATCH", "关联度一般，只观察不操作。", ["个股强度不足"]


def _stock_execution_plan(
    direction: MarketDirection,
    stock: MarketStockCandidate,
    base_action: str,
    base_risks: list[str],
) -> QuantStockExecutionPlan:
    zone_low, zone_high, avoid_above, stop_price, take_profit_price = _stock_price_levels(stock)
    price = stock.price
    change = stock.change_pct if stock.change_pct is not None else 0.0
    inflow_pct = stock.main_net_inflow_pct if stock.main_net_inflow_pct is not None else 0.0
    volume_ratio = stock.volume_ratio
    history_days = int(direction.factor_scores.get("history_days", 0) or 0)
    seven_day_score = int(direction.factor_scores.get("seven_day_score", 0) or 0)

    direction_ready = direction.state == "confirmed_mainline" or (
        direction.state == "candidate"
        and history_days >= 3
        and seven_day_score >= 60
        and direction.low_buy_readiness_score >= 62
        and direction.residency_score >= 60
        and direction.retention_score >= 60
    )
    if direction.state in {"weakening", "weak_direction"}:
        direction_status = "failed"
        direction_reason = "方向处于弱化段，不支持新开仓"
    elif direction_ready:
        direction_status = "passed"
        direction_reason = "方向阶段和7日驻留达到低吸前置条件"
    elif direction.state == "candidate":
        direction_status = "pending"
        direction_reason = "方向仍是候选段，等待至少3个交易日驻留或承接增强"
    else:
        direction_status = "pending"
        direction_reason = "方向尚未进入可低吸阶段"

    price_in_zone = price is not None and zone_low is not None and zone_high is not None and zone_low <= price <= zone_high
    price_above_avoid = price is not None and avoid_above is not None and price > avoid_above
    if price is None or zone_low is None or zone_high is None:
        price_status = "pending"
        price_reason = "缺少现价，不能计算低吸区"
    elif price_in_zone:
        price_status = "passed"
        price_reason = "现价已经进入低吸区"
    elif price_above_avoid:
        price_status = "failed"
        price_reason = "现价高于不追价，等待回踩"
    elif price < zone_low:
        price_status = "pending"
        price_reason = "现价低于低吸区，等重新企稳进入区间"
    else:
        price_status = "pending"
        price_reason = "现价尚未回到低吸区"

    if inflow_pct >= 2 and direction.residency_score >= 60 and direction.retention_score >= 60:
        capital_status = "passed"
        capital_reason = "个股资金流代理和方向驻留/承接同时达标"
    elif inflow_pct >= 0 and direction.retention_score >= 55:
        capital_status = "pending"
        capital_reason = "承接尚可，但资金流强度还不够买入触发"
    else:
        capital_status = "failed"
        capital_reason = "资金流代理偏弱，价格到了也不能直接买"

    if change >= 9:
        heat_status = "failed"
        heat_reason = "接近涨停或已经加速，禁止追高"
    elif change > 6.5:
        heat_status = "pending"
        heat_reason = "短线涨幅偏高，需要更多回踩"
    elif change >= -3:
        heat_status = "passed"
        heat_reason = "短线热度处于可观察区间"
    else:
        heat_status = "pending"
        heat_reason = "跌幅较大，需确认不是破位"

    if volume_ratio is None:
        volume_status = "pending"
        volume_reason = "缺少量比，等待下一轮数据"
    elif 1.0 <= volume_ratio <= 5.0:
        volume_status = "passed"
        volume_reason = "量比支持承接且未明显失控"
    elif volume_ratio > 5.0:
        volume_status = "pending"
        volume_reason = "量比过高，可能是加速脉冲"
    else:
        volume_status = "pending"
        volume_reason = "量能不足，等待放量承接"

    if stock.score >= 72 and stock.verifier_role in {"leader", "second_leader", "expansion"}:
        stock_status = "passed"
        stock_reason = "个股强度和方向角色达标"
    elif stock.score >= 65:
        stock_status = "pending"
        stock_reason = "个股只适合验证方向，暂不升级为买点"
    else:
        stock_status = "failed"
        stock_reason = "个股强度不足，不能作为低吸标的"

    conditions = [
        _stock_condition(
            "direction_phase",
            "方向阶段",
            direction_status,
            f"{direction.phase_label if hasattr(direction, 'phase_label') else direction.state} / 7日{seven_day_score} / 历史{history_days}天",
            "确认主线，或候选方向历史>=3天且7日分>=60",
            direction_reason,
        ),
        _stock_condition(
            "price_zone",
            "价格区间",
            price_status,
            _price_range_text(zone_low, zone_high, current=price),
            "现价进入低吸区且不高于不追价",
            price_reason,
        ),
        _stock_condition(
            "capital_acceptance",
            "资金承接",
            capital_status,
            f"净流入占比{inflow_pct:.2f}% / 驻留{direction.residency_score} / 承接{direction.retention_score}",
            "净流入占比>=2%，驻留和承接>=60",
            capital_reason,
        ),
        _stock_condition(
            "heat_control",
            "热度控制",
            heat_status,
            f"涨跌幅{change:.2f}%",
            "涨幅低于6.5%，且不是破位下跌",
            heat_reason,
        ),
        _stock_condition(
            "volume_shape",
            "量能形态",
            volume_status,
            "-" if volume_ratio is None else f"量比{volume_ratio:.2f}",
            "量比1.0-5.0",
            volume_reason,
        ),
        _stock_condition(
            "stock_quality",
            "个股质量",
            stock_status,
            f"分{stock.score} / {stock.verifier_role}",
            "方向角色明确，强度分>=72",
            stock_reason,
        ),
    ]

    hard_no = base_action in {"AVOID", "DO_NOT_CHASE", "VERIFY_ONLY"} or direction.state in {"weakening", "weak_direction"}
    required = {"direction_phase", "price_zone", "capital_acceptance", "heat_control", "stock_quality"}
    required_passed = all(item.status == "passed" for item in conditions if item.key in required)
    blockers = [item.reason for item in conditions if item.status == "failed"]

    if hard_no:
        decision_state = "no_buy"
        decision_label = "不买"
        decision_reason = "方向或个股热度触发硬过滤，当前不开仓。"
        position_plan = "不开仓。"
    elif required_passed:
        decision_state = "buy_probe"
        decision_label = "可试仓"
        decision_reason = "价格、方向、资金承接和热度同时达标，只允许小仓位试错。"
        position_plan = "候选方向首仓不超过10%；确认主线可提高到15%，禁止一次打满。"
    elif price_in_zone:
        decision_state = "wait_confirmation"
        decision_label = "等承接"
        decision_reason = "价格到了，但方向阶段或资金承接还没过阈值；下一轮价格离开区间则自动回到等待。"
        position_plan = "0仓等待，承接条件过阈值后再考虑试仓。"
    elif price_above_avoid:
        decision_state = "wait_pullback"
        decision_label = "等回踩"
        decision_reason = "现价高于不追价，不能把追高当低吸。"
        position_plan = "0仓等待回踩到低吸区。"
    else:
        decision_state = "wait_buy_zone"
        decision_label = "等低吸区"
        decision_reason = "价格还没有进入低吸区，先不买。"
        position_plan = "0仓等待价格和承接同时满足。"

    trigger_signal = _trigger_signal(zone_low, zone_high)
    invalidation_signal = _invalidation_signal(stop_price)
    capital_exit_signal = _capital_exit_signal(direction, stock, zone_low, stop_price)
    reduce_signal = _reduce_signal(zone_low, inflow_pct)
    hard_exit_signal = _hard_exit_signal(stop_price)
    after_buy_plan = _after_buy_plan(decision_state)
    return QuantStockExecutionPlan(
        decision_state=decision_state,
        decision_label=decision_label,
        decision_reason=decision_reason,
        order_style="人工限价；只在低吸区内执行，不追市价单",
        buy_zone_low=zone_low,
        buy_zone_high=zone_high,
        avoid_above=avoid_above,
        stop_price=stop_price,
        take_profit_price=take_profit_price,
        trigger_signal=trigger_signal,
        invalidation_signal=invalidation_signal,
        capital_exit_signal=capital_exit_signal,
        reduce_signal=reduce_signal,
        hard_exit_signal=hard_exit_signal,
        after_buy_plan=after_buy_plan,
        position_plan=position_plan,
        conditions=conditions,
        blockers=_dedupe([*base_risks, *blockers])[:8],
    )


def _capital_exit_signal(direction: MarketDirection, stock: MarketStockCandidate, zone_low: float | None, stop_price: float | None) -> str:
    zone = "-" if zone_low is None else f"{zone_low:.2f}"
    stop = "-" if stop_price is None else f"{stop_price:.2f}"
    return (
        f"买后若方向由{direction.state}转弱、方向跌出前排，或个股主力净流入占比连续两轮<0；"
        f"同时价格跌破低吸区下沿{zone}，先减仓；跌破防守{stop}直接离场。"
    )


def _reduce_signal(zone_low: float | None, inflow_pct: float) -> str:
    zone = "-" if zone_low is None else f"{zone_low:.2f}"
    return (
        f"买后若净流入占比从买入时转为<-3%，或当前净流入占比{inflow_pct:.2f}%继续恶化，"
        f"且价格不能重新站回{zone}，减仓50%或撤退。"
    )


def _hard_exit_signal(stop_price: float | None) -> str:
    stop = "-" if stop_price is None else f"{stop_price:.2f}"
    return f"任何时候跌破防守价{stop}，不再等待主力回流，直接按风险失败处理。"


def _after_buy_plan(decision_state: str) -> str:
    if decision_state == "buy_probe":
        return "买入后只观察承接是否延续；资金转负或方向掉队先减仓，跌破防守价离场。"
    if decision_state == "wait_confirmation":
        return "价格到了但未买；若后续承接不过阈值，不做交易。"
    if decision_state in {"wait_pullback", "wait_buy_zone"}:
        return "尚未买入；继续等待价格和资金条件同时满足。"
    return "当前不开仓；不需要承担买后资金撤退风险。"


def _stock_final_action(base_action: str, execution: QuantStockExecutionPlan) -> str:
    if base_action == "DO_NOT_CHASE":
        return "DO_NOT_CHASE"
    if base_action == "VERIFY_ONLY":
        return "VERIFY_ONLY"
    if base_action == "OBSERVE_NEXT_DAY":
        return "OBSERVE_NEXT_DAY"
    if execution.decision_state == "buy_probe":
        return "BUY_PROBE"
    if execution.decision_state == "wait_confirmation":
        return "WAIT_CONFIRMATION"
    if execution.decision_state == "wait_pullback":
        return "WAIT_PULLBACK"
    if execution.decision_state == "wait_buy_zone":
        return "WAIT_BUY_ZONE"
    if execution.decision_state == "no_buy":
        return "AVOID"
    return base_action


def _bottom_candidates(stocks: list[QuantStockDecision]) -> list[QuantStockDecision]:
    rank = {"ready": 0, "wait_acceptance": 1, "wait_price": 2}
    candidates = [
        item
        for item in stocks
        if item.bottom_state in rank and item.bottom_score >= 60
    ]
    candidates.sort(key=lambda item: (rank.get(item.bottom_state, 9), -item.bottom_score, -item.score))
    return candidates[:6]


def _bottom_profile(
    direction: MarketDirection,
    stock: MarketStockCandidate,
    execution: QuantStockExecutionPlan,
    action: str,
) -> tuple[int, str, str]:
    statuses = {condition.key: condition.status for condition in execution.conditions}
    score = 0.0
    score += _condition_points(statuses.get("direction_phase"), 22)
    score += _condition_points(statuses.get("price_zone"), 22)
    score += _condition_points(statuses.get("capital_acceptance"), 22)
    score += _condition_points(statuses.get("heat_control"), 14)
    score += _condition_points(statuses.get("volume_shape"), 8)
    score += _condition_points(statuses.get("stock_quality"), 12)

    change = stock.change_pct if stock.change_pct is not None else 0.0
    inflow_pct = stock.main_net_inflow_pct if stock.main_net_inflow_pct is not None else 0.0
    volume_ratio = stock.volume_ratio if stock.volume_ratio is not None else 0.0
    hard_block = action in {"AVOID", "DO_NOT_CHASE", "VERIFY_ONLY"} or execution.decision_state == "no_buy"
    if hard_block:
        score -= 30
    if direction.state in {"weakening", "weak_direction"}:
        score -= 40
    if inflow_pct < -5:
        score -= 18
    if change <= -5:
        score -= 14
    if volume_ratio > 6:
        score -= 8

    price_passed = statuses.get("price_zone") == "passed"
    stock_passed = statuses.get("stock_quality") == "passed"
    capital_failed = statuses.get("capital_acceptance") == "failed"
    score = _clamp_score(round(score))

    if hard_block or capital_failed:
        return min(score, 45), "avoid", "不抄底"
    if not stock_passed:
        return min(score, 58), "watch", "只验证不抄底"
    if execution.decision_state == "buy_probe" and score >= 75:
        return score, "ready", "可小仓抄底"
    if price_passed and score >= 60:
        return score, "wait_acceptance", "价到等承接"
    if score >= 60:
        return score, "wait_price", "等低吸区"
    if score >= 50:
        return score, "watch", "观察不抄底"
    return score, "avoid", "不抄底"


def _condition_points(status: str | None, max_points: int) -> float:
    if status == "passed":
        return float(max_points)
    if status == "pending":
        return max_points * 0.45
    return 0.0


def _clamp_score(value: int) -> int:
    return max(0, min(100, value))


def _stock_price_levels(stock: MarketStockCandidate) -> tuple[float | None, float | None, float | None, float | None, float | None]:
    price = stock.price
    if price is None or price <= 0:
        return None, None, None, None, None
    change = stock.change_pct if stock.change_pct is not None else 0.0
    previous_close = price / (1 + change / 100) if change > -95 else price
    if change >= 9:
        zone_low = max(previous_close * 1.025, price * 0.94)
        zone_high = min(previous_close * 1.055, price * 0.975)
    elif change >= 6:
        zone_low = max(previous_close * 1.015, price * 0.955)
        zone_high = min(previous_close * 1.045, price * 0.985)
    elif change >= 2:
        zone_low = max(previous_close, price * 0.975)
        zone_high = min(previous_close * 1.035, price * 1.003)
    elif change >= -1.5:
        zone_low = price * 0.985
        zone_high = price * 1.012
    else:
        zone_low = price * 0.98
        zone_high = price * 1.005
    if zone_low > zone_high:
        zone_low, zone_high = zone_high, zone_low
    zone_low = _round_price(zone_low)
    zone_high = _round_price(zone_high)
    avoid_above = _round_price(zone_high * 1.012)
    stop_price = _round_price(zone_low * 0.965)
    take_profit_price = _round_price(zone_high * 1.065)
    return zone_low, zone_high, avoid_above, stop_price, take_profit_price


def _stock_condition(key: str, label: str, status: str, value: str | None, threshold: str | None, reason: str) -> QuantStockExecutionCondition:
    return QuantStockExecutionCondition(
        key=key,
        label=label,
        status=status,
        value=value,
        threshold=threshold,
        reason=reason,
    )


def _trigger_signal(zone_low: float | None, zone_high: float | None) -> str:
    zone = _price_range_text(zone_low, zone_high)
    return f"价格进入{zone}；方向仍在前排；个股主力净流入占比>=2%；回踩缩量后反弹放量。"


def _invalidation_signal(stop_price: float | None) -> str:
    stop = "-" if stop_price is None else f"{stop_price:.2f}"
    return f"跌破防守价{stop}，或方向跌出前排，或主力净流入占比转<-3%，取消低吸。"


def _price_range_text(low: float | None, high: float | None, current: float | None = None) -> str:
    zone = "-" if low is None or high is None else f"{low:.2f}-{high:.2f}"
    if current is None:
        return zone
    return f"现价{current:.2f} / 区间{zone}"


def _round_price(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value + 1e-9, 2)


# ETF path is kept only for legacy API compatibility. The main web page no longer displays it.
def _etf_decisions(pool: PoolRecommendationResponse, actions: ActionDecisionResponse) -> list[QuantEtfDecision]:
    action_by_code = {item.code: item for item in actions.items}
    selected = [item for item in pool.items if item.recommended_role in {"main", "backup"}]
    if not selected:
        selected = pool.items[:3]
    result: list[QuantEtfDecision] = []
    for item in selected[:5]:
        fixed_action = action_by_code.get(item.code)
        if fixed_action:
            result.append(_fixed_action_decision(fixed_action, direction_label=item.direction_label, pool_score=item.score))
        else:
            result.append(_pool_candidate_decision(item))
    return result


def _pool_candidate_decision(item: PoolRecommendationItem) -> QuantEtfDecision:
    return QuantEtfDecision(
        code=item.code,
        name=item.name,
        role=item.recommended_role,
        action=item.action,
        operation="ETF路径已降为兼容输出；当前主页面以A股个股候选为准。",
        score=item.score,
        direction_label=item.direction_label,
        price=item.price,
        suggested_position_pct=None,
        reasons=item.reasons[:6],
        risk_flags=item.risk_flags[:6],
    )


def _fixed_action_decision(item: ActionDecisionItem, direction_label: str | None = None, pool_score: int | None = None) -> QuantEtfDecision:
    return QuantEtfDecision(
        code=item.code,
        name=item.name,
        role=item.role,
        action=item.action,
        operation=_fixed_operation(item),
        score=pool_score if pool_score is not None else item.action_score,
        direction_label=direction_label,
        price=item.current_price,
        has_position=item.has_position,
        floating_profit_pct=item.floating_profit_pct,
        suggested_position_pct=item.suggested_position_pct,
        buy_zone_low=item.buy_zone_low,
        buy_zone_high=item.buy_zone_high,
        avoid_above=item.avoid_above,
        take_profit_price=item.first_take_profit_price,
        exit_price=item.effective_exit_price,
        reasons=item.reasons[:6],
        risk_flags=item.risk_flags[:6],
    )


def _fixed_operation(item: ActionDecisionItem) -> str:
    mapping = {
        "BUY_FIRST_BATCH": "价格进入低吸区，可执行首仓。",
        "WAIT_BUY_ZONE": "方向和低吸分够，但价格未到低吸区。",
        "WATCH_LOW_BUY": "观察低吸，等回踩。",
        "WAIT_PULLBACK": "等回落，不追。",
        "SELL_ALL": "风险触发，优先离场。",
        "SELL_PARTIAL_50": "强止盈，减半。",
        "SELL_PARTIAL_20_30": "部分止盈，卖出20-30%。",
        "REDUCE_OR_HOLD_TIGHT": "减仓或收紧防守线。",
        "HOLD": "持有，按防守线跟踪。",
        "HOLD_WATCH": "持有观察。",
        "AVOID": "回避，不开新仓。",
        "WAIT": "等待，无动作。",
        "WAIT_DATA": "等待数据恢复。",
    }
    return mapping.get(item.action, item.action)


def _conclusion(
    direction: QuantDirectionDecision,
    stocks: list[QuantStockDecision],
    fixed_actions: list[QuantEtfDecision],
    holdings: list[QuantHoldingDecision] | None = None,
) -> str:
    holdings = holdings or []
    urgent_holding = next((item for item in holdings if item.action in {"EXIT", "REDUCE_OR_EXIT", "REDUCE_ON_REBOUND"}), None)
    if urgent_holding:
        return f"持仓优先：{urgent_holding.name} 当前{urgent_holding.action_label}，先处理风控，不要盲目补仓。"
    sell = [item for item in fixed_actions if item.action.startswith("SELL") or item.action == "REDUCE_OR_HOLD_TIGHT"]
    buy_probe = [item for item in stocks if item.bottom_state == "ready"]
    wait_buy = [item for item in stocks if item.bottom_state in {"wait_acceptance", "wait_price"}]
    hot = [item for item in stocks if item.action in {"WAIT_PULLBACK", "DO_NOT_CHASE", "OBSERVE_NEXT_DAY"}]
    if sell:
        return f"{direction.direction_label or '市场'}处于{direction.phase_label}；已有持仓优先按卖出/减仓信号处理。"
    if buy_probe:
        names = "、".join(f"{item.name}({item.code})" for item in buy_probe[:2])
        return f"{direction.direction_label or '市场'}处于{direction.phase_label}；{names} 满足低吸触发，只允许小仓试错。"
    if wait_buy:
        names = "、".join(f"{item.name}({item.code})" for item in wait_buy[:3])
        return f"{direction.direction_label or '市场'}处于{direction.phase_label}；A股候选为 {names}，等待低吸区和承接同时满足。"
    if hot:
        return f"{direction.direction_label or '市场'}处于{direction.phase_label}；方向龙头/二龙头偏热或需次日承接，当前不追。"
    if stocks:
        return f"{direction.direction_label or '市场'}处于{direction.phase_label}；已有龙头/二龙头样本，但当前没有抄底候选，只观察验证。"
    return f"{direction.direction_label or '市场'}处于{direction.phase_label}；当前没有可用A股候选。"


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not value or value in seen:
            continue
        result.append(value)
        seen.add(value)
    return result
