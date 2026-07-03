from __future__ import annotations

from datetime import datetime, timezone

from app.core.market import market_status
from app.domain.models import (
    ActionDecisionItem,
    ActionDecisionResponse,
    MarketDirection,
    MarketFlowResponse,
    MarketStockCandidate,
    PoolRecommendationItem,
    PoolRecommendationResponse,
    QuantDecisionResponse,
    QuantDirectionDecision,
    QuantEtfDecision,
    QuantStockDecision,
)


def build_quant_decision_report(
    market_flow: MarketFlowResponse,
    pool: PoolRecommendationResponse | None = None,
    actions: ActionDecisionResponse | None = None,
) -> QuantDecisionResponse:
    top_direction = market_flow.directions[0] if market_flow.directions else None
    direction_decision = _direction_decision(top_direction)
    etfs = _etf_decisions(pool, actions) if pool is not None and actions is not None else []
    stocks = _stock_decisions(top_direction)
    fixed_actions = [_fixed_action_decision(item) for item in actions.items] if actions is not None else []
    conclusion = _conclusion(direction_decision, stocks, fixed_actions)
    warnings = [*market_flow.warnings[:4]]
    if top_direction and top_direction.state != "confirmed_mainline":
        warnings.insert(0, "当前方向不是确认主升，A股操作以等待回踩和验证承接为主。")
    if top_direction and not top_direction.linked_stocks:
        warnings.insert(0, "当前方向缺少龙头/二龙头样本，不能给个股候选动作。")
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
            "当前为A股个股聚焦模式：先识别市场资金方向，再筛方向内龙头、二龙头和扩散股。",
            "龙头/二龙头来自方向内成分股的涨幅、成交额、量比、资金流代理和带动性排序。",
            "个股候选不是自动买入指令；缺少Level-2、盘口队列和个股多周期K线前，不输出精确买卖价。",
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
        action, operation, risks = _stock_action(direction, stock)
        result.append(
            QuantStockDecision(
                code=stock.code,
                name=stock.name,
                action=action,
                operation=operation,
                score=stock.score,
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
                reasons=(stock.evidence[:5] or ["方向龙头/二龙头候选"]),
                risk_flags=_dedupe([*stock.risk_flags[:5], *risks])[:8],
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


def _conclusion(direction: QuantDirectionDecision, stocks: list[QuantStockDecision], fixed_actions: list[QuantEtfDecision]) -> str:
    sell = [item for item in fixed_actions if item.action.startswith("SELL") or item.action == "REDUCE_OR_HOLD_TIGHT"]
    low_buy = [item for item in stocks if item.action == "WATCH_LOW_BUY"]
    hot = [item for item in stocks if item.action in {"WAIT_PULLBACK", "DO_NOT_CHASE", "OBSERVE_NEXT_DAY"}]
    if sell:
        return f"{direction.direction_label or '市场'}处于{direction.phase_label}；已有持仓优先按卖出/减仓信号处理。"
    if low_buy:
        names = "、".join(f"{item.name}({item.code})" for item in low_buy[:3])
        return f"{direction.direction_label or '市场'}处于{direction.phase_label}；A股候选为 {names}，只等回踩承接，不追高。"
    if hot:
        return f"{direction.direction_label or '市场'}处于{direction.phase_label}；方向龙头/二龙头偏热或需次日承接，当前不追。"
    if stocks:
        return f"{direction.direction_label or '市场'}处于{direction.phase_label}；已有龙头/二龙头样本，但当前只观察验证。"
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
