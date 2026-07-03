from __future__ import annotations

from datetime import datetime, timezone

from app.core.market import market_status
from app.domain.models import (
    ActionDecisionItem,
    ActionDecisionResponse,
    MarketDirection,
    MarketFlowResponse,
    PoolRecommendationItem,
    PoolRecommendationResponse,
    QuantDecisionResponse,
    QuantDirectionDecision,
    QuantEtfDecision,
    QuantStockDecision,
)


def build_quant_decision_report(
    market_flow: MarketFlowResponse,
    pool: PoolRecommendationResponse,
    actions: ActionDecisionResponse,
) -> QuantDecisionResponse:
    top_direction = market_flow.directions[0] if market_flow.directions else None
    direction_decision = _direction_decision(top_direction)
    etfs = _etf_decisions(pool, actions)
    stocks = _stock_decisions(top_direction)
    fixed_actions = [_fixed_action_decision(item) for item in actions.items]
    conclusion = _conclusion(direction_decision, etfs, fixed_actions)
    warnings = [*market_flow.warnings[:2], *pool.warnings[:2], *actions.warnings[:2]]
    if top_direction and top_direction.state != "confirmed_mainline":
        warnings.insert(0, "当前方向不是确认主升，操作以等待回踩和验证承接为主。")
    return QuantDecisionResponse(
        generated_at=datetime.now(timezone.utc),
        market_status=market_status(),
        conclusion=conclusion,
        direction=direction_decision,
        etfs=etfs,
        stocks=stocks,
        fixed_pool_actions=fixed_actions,
        warnings=_dedupe(warnings)[:8],
        assumptions=[
            "第一屏只给最终量化结论，其余页面作为证据。",
            "ETF完整买卖动作覆盖量化候选和用户已登记持仓。",
            "动态候选ETF只给空仓开仓候选，必须入池或登记持仓后才有完整低吸/止盈/防守线。",
            "个股目前用于验证方向强弱，不直接输出个股买卖点。",
            "主升确认需要至少3个交易日的驻留样本、承接、扩散和反证过滤；单日热点不等于主升。",
        ],
    )


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
        f"主线概率 {direction.mainline_probability}",
        f"资金驻留 {direction.residency_score}",
        f"承接 {direction.retention_score}",
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
        residency_score=direction.residency_score,
        retention_score=direction.retention_score,
        low_buy_readiness_score=direction.low_buy_readiness_score,
        evidence=evidence[:8],
        risk_flags=direction.risk_flags[:8],
    )


def _phase(direction: MarketDirection) -> tuple[str, str, str, str]:
    if direction.state == "confirmed_mainline" and direction.low_buy_readiness_score >= 65:
        return "main_up_low_buy", "主升低吸段", "high", "允许围绕量化候选ETF执行低吸计划，不追高。"
    if direction.state == "confirmed_mainline":
        return "main_up_hold", "主升持有段", "high", "方向处于主升，已有仓位按持有/止盈规则执行，新仓等回踩。"
    if direction.state == "candidate":
        return "candidate", "方向候选段", "medium-low", "先验证多日驻留和承接，ETF只等低吸区，不追涨。"
    if direction.state == "hot_today":
        return "hot_today", "单日爆发段", "medium-low", "观察次日承接，禁止追高。"
    if direction.state == "overheated":
        return "overheated", "加速过热段", "medium-low", "不追高，等回落或止盈。"
    if direction.state == "weakening":
        return "weakening", "退潮弱化段", "low", "回避新开仓，已有仓位按风控减仓。"
    if direction.state == "weak_direction":
        return "weak", "弱方向", "low", "等待，不参与。"
    return "watch", "观察震荡段", "medium-low", "观察，不做主动买入。"


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
    suggested_position_pct = None
    operation = "空仓候选：等待低吸区、防守线和承接信号同时满足后再决定。"
    if item.recommended_role is None:
        operation = "强关联观察ETF：方向或低吸闸门未通过，只看不买。"
    elif item.direction_state == "confirmed_mainline" and item.low_buy_readiness_score and item.low_buy_readiness_score >= 65:
        suggested_position_pct = 20
        operation = "空仓开仓候选；入池后等待低吸触发，首仓上限20%，未触发不买。"
    elif item.direction_state == "candidate":
        operation = "方向候选载体，先等回踩和多日承接；未确认前不追。"
    elif item.direction_state == "hot_today":
        operation = "单日热点关联ETF，等待次日承接，不作为开仓信号。"
    return QuantEtfDecision(
        code=item.code,
        name=item.name,
        role=item.recommended_role,
        action=item.action,
        operation=operation,
        score=item.score,
        direction_label=item.direction_label,
        price=item.price,
        suggested_position_pct=suggested_position_pct,
        reasons=item.reasons[:6],
        risk_flags=item.risk_flags[:6] + ["未进入量化候选或持仓监控，暂无完整买卖点"],
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


def _stock_decisions(direction: MarketDirection | None) -> list[QuantStockDecision]:
    if direction is None:
        return []
    stocks = direction.linked_stocks[:3]
    if not stocks and direction.representative_stock:
        stocks = [direction.representative_stock]
    result: list[QuantStockDecision] = []
    for stock in stocks:
        result.append(
            QuantStockDecision(
                code=stock.code,
                name=stock.name,
                action="VERIFY_DIRECTION",
                operation="作为强股验证方向，不直接给个股买卖点。",
                score=stock.score,
                direction_label=direction.direction_label,
                change_pct=stock.change_pct,
                reasons=stock.evidence[:5] or ["方向代表股"],
                risk_flags=stock.risk_flags[:5],
            )
        )
    return result


def _conclusion(direction: QuantDirectionDecision, etfs: list[QuantEtfDecision], fixed_actions: list[QuantEtfDecision]) -> str:
    buy = [item for item in fixed_actions if item.action == "BUY_FIRST_BATCH"]
    sell = [item for item in fixed_actions if item.action.startswith("SELL") or item.action == "REDUCE_OR_HOLD_TIGHT"]
    holding = [item for item in fixed_actions if item.has_position]
    candidate_open = [item for item in etfs if item.suggested_position_pct]
    if sell:
        return f"{direction.direction_label or '市场'}处于{direction.phase_label}；当前优先处理卖出/减仓信号。"
    if holding:
        return f"{direction.direction_label or '市场'}处于{direction.phase_label}；已有持仓按持有/止盈/防守线跟踪。"
    if buy:
        return f"{direction.direction_label or '市场'}处于{direction.phase_label}；量化候选出现可执行低吸。"
    if candidate_open:
        return f"{direction.direction_label or '市场'}处于{direction.phase_label}；空仓只等候选ETF入池后的低吸触发。"
    return f"{direction.direction_label or '市场'}处于{direction.phase_label}；当前不追高，以等待和验证为主。"


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not value or value in seen:
            continue
        result.append(value)
        seen.add(value)
    return result
