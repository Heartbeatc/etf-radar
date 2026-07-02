from __future__ import annotations

from datetime import datetime, timezone
from statistics import mean

from app.core.config import Settings
from app.core.market import market_status
from app.domain.models import (
    ActionDecisionItem,
    ActionDecisionResponse,
    MarketDirection,
    MarketFlowResponse,
    PoolRecommendationItem,
    PoolRecommendationResponse,
    Position,
    QuantExecutionAdvice,
    QuantFeatureRow,
    QuantFrameworkResponse,
    QuantFrameworkValidation,
    QuantInsight,
    QuantPortfolioTarget,
    QuantRiskAdjustment,
    QuantUniverseAsset,
)

ARCHITECTURE = [
    "Universe Selection: select tradable directions, ETF carriers, and held assets",
    "Feature Engineering: convert raw board/ETF/action data into auditable factor rows",
    "Alpha Model: emit direction/magnitude/confidence/horizon insights",
    "Portfolio Construction: translate insights into target weights or position deltas",
    "Risk Management: cap, block, or reduce targets before execution",
    "Execution Advice: produce manual ETF order guidance; no automatic order placement",
]
MAX_RESEARCH_TOTAL_WEIGHT = 40.0
MAX_SINGLE_ETF_WEIGHT = 20.0


def build_quant_framework_report(
    settings: Settings,
    market_flow: MarketFlowResponse,
    pool: PoolRecommendationResponse,
    actions: ActionDecisionResponse,
    positions: dict[str, Position],
) -> QuantFrameworkResponse:
    universe = _build_universe(market_flow, pool, actions, positions)
    features = _build_features(market_flow, pool, actions)
    insights = _build_insights(market_flow, pool, actions)
    targets = _build_portfolio_targets(pool, actions, insights, positions)
    risk_adjustments = _apply_risk_management(targets, actions)
    execution_plan = _build_execution_plan(risk_adjustments, actions, pool)
    validation = _validation(market_flow, pool, actions, positions)
    warnings = _warnings(market_flow, pool, actions, validation)
    return QuantFrameworkResponse(
        generated_at=datetime.now(timezone.utc),
        market_status=market_status(),
        architecture=ARCHITECTURE,
        universe=universe,
        features=features,
        insights=insights,
        portfolio_targets=targets,
        risk_adjustments=risk_adjustments,
        execution_plan=execution_plan,
        final_actions=actions.items,
        validation=validation,
        warnings=warnings,
        assumptions=[
            "This endpoint follows a LEAN/Qlib-style decision chain rather than a dashboard summary.",
            "Free public data can support research-grade signals, not unattended live trading.",
            "Opening trades require both alpha approval and risk/execution approval; a hot direction alone is not enough.",
            "Held ETFs are handled by risk and execution modules even if they are no longer top universe candidates.",
            "Position sizing is capped until paid Level-2/order-book data and statistically validated multi-day samples are added.",
        ],
    )


def _build_universe(
    market_flow: MarketFlowResponse,
    pool: PoolRecommendationResponse,
    actions: ActionDecisionResponse,
    positions: dict[str, Position],
) -> list[QuantUniverseAsset]:
    assets: list[QuantUniverseAsset] = []
    for rank, direction in enumerate(market_flow.directions[:6], start=1):
        selected = direction.state in {"confirmed_mainline", "candidate"} and rank <= 3
        assets.append(
            QuantUniverseAsset(
                asset_type="direction",
                name=direction.direction_label,
                direction_key=direction.direction_key,
                direction_label=direction.direction_label,
                role="mainline_candidate" if selected else "monitor",
                rank=rank,
                selected=selected,
                reason=_direction_reason(direction),
                evidence=direction.evidence[:6],
                risk_flags=direction.risk_flags[:6],
            )
        )
    seen_codes: set[str] = set()
    for item in pool.items[:10]:
        selected = item.recommended_role is not None or item.action in {"keep", "promote"}
        assets.append(
            QuantUniverseAsset(
                asset_type="etf",
                code=item.code,
                name=item.name,
                direction_key=item.direction_key,
                direction_label=item.direction_label,
                role=item.recommended_role or item.current_role or "watch",
                rank=item.rank,
                selected=selected,
                reason=_pool_reason(item),
                evidence=item.reasons[:6],
                risk_flags=item.risk_flags[:6],
            )
        )
        seen_codes.add(item.code)
    for action in actions.items:
        if action.code in seen_codes and not action.has_position:
            continue
        if action.has_position or action.code in positions:
            assets.append(
                QuantUniverseAsset(
                    asset_type="etf",
                    code=action.code,
                    name=action.name,
                    role="held_position",
                    selected=True,
                    reason="registered holding; risk module must manage it even if not a top candidate",
                    evidence=action.reasons[:6],
                    risk_flags=action.risk_flags[:6],
                )
            )
    return assets


def _build_features(
    market_flow: MarketFlowResponse,
    pool: PoolRecommendationResponse,
    actions: ActionDecisionResponse,
) -> list[QuantFeatureRow]:
    rows: list[QuantFeatureRow] = []
    for direction in market_flow.directions[:8]:
        features = dict(direction.factor_scores)
        features.update(
            {
                "board_count": direction.board_count,
                "positive_board_count": direction.positive_board_count,
                "total_amount": direction.total_amount,
                "main_net_inflow": direction.main_net_inflow,
                "avg_change_pct": direction.avg_change_pct,
                "breadth_pct": direction.breadth_pct,
                "capital_concentration_pct": direction.capital_concentration_pct,
            }
        )
        rows.append(
            QuantFeatureRow(
                asset_type="direction",
                name=direction.direction_label,
                direction_key=direction.direction_key,
                direction_label=direction.direction_label,
                feature_set="market_flow_v1",
                features=features,
                score=direction.score,
                evidence=direction.evidence[:6],
                risk_flags=direction.risk_flags[:6],
            )
        )
    for item in pool.items[:10]:
        rows.append(
            QuantFeatureRow(
                asset_type="etf",
                code=item.code,
                name=item.name,
                direction_key=item.direction_key,
                direction_label=item.direction_label,
                feature_set="etf_carrier_v1",
                features={
                    "pool_score": item.score,
                    "mainline_probability": item.mainline_probability,
                    "low_buy_readiness_score": item.low_buy_readiness_score,
                    "carrier_score": item.carrier_score,
                    "amount": item.amount,
                    "premium_pct": item.premium_pct,
                    "entry_bias": item.entry_bias,
                    "recommended_role": item.recommended_role,
                    "pool_action": item.action,
                },
                score=item.score,
                evidence=item.reasons[:6],
                risk_flags=item.risk_flags[:6],
            )
        )
    for item in actions.items:
        rows.append(
            QuantFeatureRow(
                asset_type="etf_action",
                code=item.code,
                name=item.name,
                feature_set="position_action_v1",
                features={
                    "action_score": item.action_score,
                    "side": item.side,
                    "signal": item.signal,
                    "direction_score": item.direction_score,
                    "low_buy_score": item.low_buy_score,
                    "hold_score": item.hold_score,
                    "take_profit_score": item.take_profit_score,
                    "risk_score": item.risk_score,
                    "floating_profit_pct": item.floating_profit_pct,
                    "has_position": item.has_position,
                },
                score=item.action_score,
                evidence=item.reasons[:6],
                risk_flags=item.risk_flags[:6],
            )
        )
    return rows


def _build_insights(
    market_flow: MarketFlowResponse,
    pool: PoolRecommendationResponse,
    actions: ActionDecisionResponse,
) -> list[QuantInsight]:
    insights: list[QuantInsight] = []
    for direction in market_flow.directions[:5]:
        confidence = _direction_confidence(direction)
        insights.append(
            QuantInsight(
                asset_type="direction",
                name=direction.direction_label,
                direction=_insight_direction(direction.state),
                magnitude_score=direction.mainline_probability,
                confidence_score=confidence,
                confidence_label=_confidence_label(confidence),
                horizon=_direction_horizon(direction.state),
                insight_type="mainline_regime",
                generated_from="market_flow_factor_model_v1",
                evidence=direction.evidence[:6],
                risk_flags=direction.risk_flags[:6],
            )
        )
    action_by_code = {item.code: item for item in actions.items}
    seen_codes: set[str] = set()
    for item in pool.items[:8]:
        action = action_by_code.get(item.code)
        confidence = _etf_confidence(item, action)
        insights.append(
            QuantInsight(
                asset_type="etf",
                code=item.code,
                name=item.name,
                direction=_etf_insight_direction(item, action),
                magnitude_score=max(item.score, action.action_score if action else 0),
                confidence_score=confidence,
                confidence_label=_confidence_label(confidence),
                horizon=_etf_horizon(item, action),
                insight_type="carrier_alpha",
                generated_from="pool_recommendation_plus_action_model_v1",
                evidence=_dedupe([*item.reasons[:4], *((action.reasons[:4]) if action else [])])[:6],
                risk_flags=_dedupe([*item.risk_flags[:4], *((action.risk_flags[:4]) if action else [])])[:6],
            )
        )
        seen_codes.add(item.code)
    for action in actions.items:
        if action.code in seen_codes and not action.has_position:
            continue
        confidence = _action_confidence(action)
        insights.append(
            QuantInsight(
                asset_type="etf",
                code=action.code,
                name=action.name,
                direction=_action_direction(action),
                magnitude_score=action.action_score,
                confidence_score=confidence,
                confidence_label=_confidence_label(confidence),
                horizon="now" if action.side == "SELL" else "T+1 to T+5",
                insight_type="position_management",
                generated_from="action_decision_model_v1",
                evidence=action.reasons[:6],
                risk_flags=action.risk_flags[:6],
            )
        )
    return insights


def _build_portfolio_targets(
    pool: PoolRecommendationResponse,
    actions: ActionDecisionResponse,
    insights: list[QuantInsight],
    positions: dict[str, Position],
) -> list[QuantPortfolioTarget]:
    insight_by_code = {item.code: item for item in insights if item.code}
    pool_by_code = {item.code: item for item in pool.items}
    targets: list[QuantPortfolioTarget] = []
    used: set[str] = set()
    for action in actions.items:
        target = _target_from_action(action, insight_by_code.get(action.code))
        targets.append(target)
        used.add(action.code)
    for item in pool.items:
        if item.code in used:
            continue
        if item.recommended_role not in {"main", "backup"} and item.action != "promote":
            continue
        insight = insight_by_code.get(item.code)
        target = _target_from_pool_item(item, insight, has_position=item.code in positions)
        targets.append(target)
        used.add(item.code)
    return _cap_total_targets(targets, pool_by_code)


def _apply_risk_management(targets: list[QuantPortfolioTarget], actions: ActionDecisionResponse) -> list[QuantRiskAdjustment]:
    action_by_code = {item.code: item for item in actions.items}
    adjustments: list[QuantRiskAdjustment] = []
    allocated = 0.0
    for target in targets:
        action = action_by_code.get(target.code)
        adjusted = target.target_weight_pct
        reasons: list[str] = []
        risk_flags = list(target.risk_flags)
        blocked = False
        risk_level = "low"

        if target.target_weight_pct is not None and target.target_weight_pct > MAX_SINGLE_ETF_WEIGHT:
            adjusted = MAX_SINGLE_ETF_WEIGHT
            reasons.append("single ETF research cap applied")
        if action and action.risk_score >= 75:
            adjusted = 0.0
            blocked = True
            risk_level = "high"
            reasons.append("action risk score blocks new or increased exposure")
        elif action and action.risk_score >= 55:
            risk_level = "medium"
            reasons.append("risk score elevated; keep exposure conservative")
        if action and not action.has_position and action.action not in {"BUY_FIRST_BATCH"} and (adjusted or 0) > 0:
            adjusted = 0.0
            blocked = True
            risk_level = "medium"
            reasons.append("alpha may be valid, but execution trigger is not in buy zone")
        if action and action.side == "SELL":
            adjusted = 0.0 if action.action == "SELL_ALL" else adjusted
            reasons.append("sell-side action has priority over target construction")
        if adjusted is not None and adjusted > 0:
            remaining = max(0.0, MAX_RESEARCH_TOTAL_WEIGHT - allocated)
            if adjusted > remaining:
                adjusted = remaining
                reasons.append("total research exposure cap applied")
            allocated += adjusted
        if not reasons:
            reasons.append("risk module passed target without adjustment")
        adjustments.append(
            QuantRiskAdjustment(
                code=target.code,
                name=target.name,
                original_target_weight_pct=target.target_weight_pct,
                adjusted_target_weight_pct=adjusted,
                position_delta_pct=target.position_delta_pct,
                risk_level=risk_level,
                blocked=blocked,
                reasons=reasons[:6],
                risk_flags=_dedupe(risk_flags)[:8],
            )
        )
    return adjustments


def _build_execution_plan(
    adjustments: list[QuantRiskAdjustment],
    actions: ActionDecisionResponse,
    pool: PoolRecommendationResponse,
) -> list[QuantExecutionAdvice]:
    action_by_code = {item.code: item for item in actions.items}
    pool_by_code = {item.code: item for item in pool.items}
    plan: list[QuantExecutionAdvice] = []
    for item in adjustments:
        action = action_by_code.get(item.code)
        pool_item = pool_by_code.get(item.code)
        side = _execution_side(item, action)
        blockers = [] if not item.blocked else item.reasons
        notes = _execution_notes(item, action, pool_item)
        plan.append(
            QuantExecutionAdvice(
                code=item.code,
                name=item.name,
                side=side,
                action=action.action if action else ("WATCH" if side == "WAIT" else side),
                urgency=action.urgency if action else "normal",
                target_weight_pct=item.adjusted_target_weight_pct,
                position_delta_pct=item.position_delta_pct,
                order_style=_order_style(side, action),
                trigger_price_low=action.buy_zone_low if action else None,
                trigger_price_high=action.buy_zone_high if action else None,
                avoid_above=action.avoid_above if action else None,
                stop_price=action.effective_exit_price if action else None,
                take_profit_price=action.first_take_profit_price if action else None,
                notes=notes[:6],
                blockers=blockers[:6],
            )
        )
    return plan


def _validation(
    market_flow: MarketFlowResponse,
    pool: PoolRecommendationResponse,
    actions: ActionDecisionResponse,
    positions: dict[str, Position],
) -> QuantFrameworkValidation:
    passed: list[str] = []
    blockers: list[str] = []
    if market_flow.directions:
        passed.append("market-flow universe is available")
    else:
        blockers.append("no market-flow universe")
    if pool.items:
        passed.append("ETF carrier pool is available")
    else:
        blockers.append("no ETF carrier candidates")
    if actions.items:
        passed.append("action model returned fixed-pool/position decisions")
    else:
        blockers.append("no action decisions")
    if positions:
        passed.append("registered positions are included in risk management")
    else:
        passed.append("no registered positions; system runs in empty-book mode")
    blockers.extend(
        [
            "no paid Level-2/order-book data, so fund identity and true order pressure are unverified",
            "no statistically validated multi-day factor performance report yet",
            "no broker execution adapter; output must remain manual advice",
        ]
    )
    return QuantFrameworkValidation(
        research_grade=True,
        live_trading_ready=False,
        evidence_strength="medium-low" if market_flow.directions and pool.items else "low",
        passed=passed,
        blockers=blockers,
        required_upgrades=[
            "persist multi-day board/ETF factor snapshots and compute hit-rate/IC/turnover by factor",
            "add backtest endpoint for the full framework, not only single-ETF rules",
            "add paid Level-2/order-book or vendor-grade ETF flow data before considering automation",
            "add portfolio NAV/cash input before exact target weights can be enforced",
        ],
    )


def _warnings(
    market_flow: MarketFlowResponse, pool: PoolRecommendationResponse, actions: ActionDecisionResponse, validation: QuantFrameworkValidation) -> list[str]:
    warnings = [*market_flow.warnings[:3], *pool.warnings[:3], *actions.warnings[:3]]
    if not validation.live_trading_ready:
        warnings.insert(0, "当前是研究级量化框架，不是自动交易系统；禁止无人工复核下单。")
    if market_flow.directions and market_flow.directions[0].state not in {"confirmed_mainline", "candidate"}:
        warnings.insert(0, "前排方向未通过主线/候选状态过滤，组合模块会压低或阻断开仓。")
    return _dedupe(warnings)[:10]


def _target_from_action(action: ActionDecisionItem, insight: QuantInsight | None) -> QuantPortfolioTarget:
    target_weight: float | None = None
    delta_pct: int | None = None
    rebalance = "watch"
    reason = action.execution_note or action.action
    if action.action == "BUY_FIRST_BATCH":
        target_weight = 20.0
        rebalance = "open_first_batch"
    elif action.action in {"WAIT_BUY_ZONE", "WATCH_LOW_BUY", "WAIT_PULLBACK", "WAIT"}:
        target_weight = 0.0
        rebalance = "wait_for_trigger"
    elif action.action == "SELL_ALL":
        target_weight = 0.0
        delta_pct = -100
        rebalance = "exit"
    elif action.action == "SELL_PARTIAL_50":
        delta_pct = -50
        rebalance = "take_profit_reduce"
    elif action.action == "SELL_PARTIAL_20_30":
        delta_pct = -30
        rebalance = "take_profit_trim"
    elif action.action == "REDUCE_OR_HOLD_TIGHT":
        delta_pct = -20
        rebalance = "risk_trim"
    elif action.action in {"HOLD", "HOLD_WATCH"}:
        rebalance = "keep_existing_position"
    elif action.action == "AVOID":
        target_weight = 0.0
        rebalance = "avoid"
    elif action.action == "WAIT_DATA":
        rebalance = "wait_data"
    return QuantPortfolioTarget(
        code=action.code,
        name=action.name,
        target_role="held" if action.has_position else action.role,
        rebalance_action=rebalance,
        target_weight_pct=target_weight,
        position_delta_pct=delta_pct,
        source_insight=insight.insight_type if insight else "action_decision_model_v1",
        target_reason=reason,
        evidence=action.reasons[:6],
        risk_flags=action.risk_flags[:6],
    )


def _target_from_pool_item(item: PoolRecommendationItem, insight: QuantInsight | None, has_position: bool) -> QuantPortfolioTarget:
    allow_watch_weight = (
        item.recommended_role == "main"
        and item.direction_state in {"confirmed_mainline", "candidate"}
        and (item.low_buy_readiness_score or 0) >= 65
        and item.score >= 72
    )
    target_weight = 20.0 if allow_watch_weight and has_position else 0.0
    return QuantPortfolioTarget(
        code=item.code,
        name=item.name,
        target_role=item.recommended_role or "watch",
        rebalance_action="watch_for_entry" if target_weight == 0 else "hold_or_add_under_cap",
        target_weight_pct=target_weight,
        source_insight=insight.insight_type if insight else "pool_recommendation_model_v1",
        target_reason="selected ETF carrier; wait for execution trigger before opening" if target_weight == 0 else "held selected carrier remains within target model",
        evidence=item.reasons[:6],
        risk_flags=item.risk_flags[:6],
    )


def _cap_total_targets(targets: list[QuantPortfolioTarget], pool_by_code: dict[str, PoolRecommendationItem]) -> list[QuantPortfolioTarget]:
    total = 0.0
    capped: list[QuantPortfolioTarget] = []
    for target in targets:
        target_copy = target.model_copy(deep=True)
        if target_copy.target_weight_pct is not None and target_copy.target_weight_pct > 0:
            target_copy.target_weight_pct = min(target_copy.target_weight_pct, MAX_SINGLE_ETF_WEIGHT)
            remaining = max(0.0, MAX_RESEARCH_TOTAL_WEIGHT - total)
            if target_copy.target_weight_pct > remaining:
                target_copy.target_weight_pct = remaining
                target_copy.risk_flags = [*target_copy.risk_flags, "portfolio research exposure cap reached"]
            total += target_copy.target_weight_pct
        if target_copy.code in pool_by_code:
            item = pool_by_code[target_copy.code]
            if item.premium_pct is not None and abs(item.premium_pct) >= 2:
                target_copy.risk_flags = [*target_copy.risk_flags, "ETF premium/discount too wide for target sizing"]
        capped.append(target_copy)
    return capped


def _direction_reason(direction: MarketDirection) -> str:
    if direction.state == "confirmed_mainline":
        return "mainline confirmed by current factor model"
    if direction.state == "candidate":
        return "candidate mainline; needs retention"
    if direction.state == "hot_today":
        return "hot today but not persistent enough"
    if direction.state == "overheated":
        return "strong but extended; wait for pullback"
    if direction.state == "weakening":
        return "flow/retention weakening"
    return "monitor only"


def _pool_reason(item: PoolRecommendationItem) -> str:
    if item.recommended_role == "main":
        return "top ETF carrier selected by pool model"
    if item.recommended_role == "backup":
        return "backup ETF carrier selected by pool model"
    if item.current_role:
        return "current monitored ETF retained for comparison"
    return "watch candidate"


def _direction_confidence(direction: MarketDirection) -> int:
    values = [direction.residency_score, direction.retention_score, direction.etf_confirmation_score, direction.low_buy_readiness_score]
    return _clamp(mean(values))


def _etf_confidence(item: PoolRecommendationItem, action: ActionDecisionItem | None) -> int:
    values = [item.score]
    for value in [item.mainline_probability, item.low_buy_readiness_score, item.carrier_score]:
        if value is not None:
            values.append(value)
    if action:
        values.extend([action.action_score, max(0, 100 - action.risk_score)])
    return _clamp(mean(values))


def _action_confidence(action: ActionDecisionItem) -> int:
    base = action.action_score * 0.60 + max(0, 100 - action.risk_score) * 0.20 + action.hold_score * 0.20
    if action.confidence == "high":
        base += 6
    elif action.confidence == "low":
        base -= 12
    return _clamp(base)


def _confidence_label(score: int) -> str:
    if score >= 75:
        return "high"
    if score >= 62:
        return "medium"
    if score >= 48:
        return "medium-low"
    return "low"


def _insight_direction(state: str) -> str:
    if state in {"confirmed_mainline", "candidate"}:
        return "UP"
    if state in {"weakening", "weak_direction"}:
        return "DOWN"
    return "FLAT"


def _direction_horizon(state: str) -> str:
    if state == "confirmed_mainline":
        return "T+5 to T+20"
    if state == "candidate":
        return "T+1 to T+5"
    if state == "hot_today":
        return "next-session validation"
    return "intraday monitor"


def _etf_insight_direction(item: PoolRecommendationItem, action: ActionDecisionItem | None) -> str:
    if action:
        return _action_direction(action)
    if item.action in {"promote", "keep"} and item.direction_state in {"confirmed_mainline", "candidate"}:
        return "UP"
    if item.direction_state in {"weakening", "weak_direction"} or item.action == "avoid":
        return "DOWN"
    return "FLAT"


def _action_direction(action: ActionDecisionItem) -> str:
    if action.side in {"BUY", "HOLD"}:
        return "UP"
    if action.side == "SELL" or action.action == "AVOID":
        return "DOWN"
    return "FLAT"


def _etf_horizon(item: PoolRecommendationItem, action: ActionDecisionItem | None) -> str:
    if action and action.side in {"BUY", "SELL"}:
        return "now to T+1"
    if item.direction_state == "confirmed_mainline":
        return "T+5 to T+20"
    if item.direction_state == "candidate":
        return "T+1 to T+5"
    return "watch"


def _execution_side(item: QuantRiskAdjustment, action: ActionDecisionItem | None) -> str:
    if action and action.side == "SELL":
        return "SELL"
    if action and action.side == "BUY" and not item.blocked and (item.adjusted_target_weight_pct or 0) > 0:
        return "BUY"
    if action and action.side == "HOLD":
        return "HOLD"
    return "WAIT"


def _order_style(side: str, action: ActionDecisionItem | None) -> str:
    if side == "BUY":
        return "manual limit order inside low-buy zone; split into 2-3 batches"
    if side == "SELL":
        return "manual limit/marketable limit after price and liquidity check"
    if side == "HOLD":
        return "no order; track stop and take-profit levels"
    if action and action.action == "WAIT_DATA":
        return "blocked until market data refreshes"
    return "no order; wait for trigger"


def _execution_notes(item: QuantRiskAdjustment, action: ActionDecisionItem | None, pool_item: PoolRecommendationItem | None) -> list[str]:
    notes: list[str] = []
    if action:
        notes.append(action.execution_note)
    if pool_item and pool_item.direction_label:
        notes.append(f"direction carrier: {pool_item.direction_label}")
    if item.adjusted_target_weight_pct is not None:
        notes.append(f"risk-adjusted target weight: {item.adjusted_target_weight_pct:.1f}%")
    if item.position_delta_pct is not None:
        notes.append(f"position delta: {item.position_delta_pct}%")
    notes.extend(item.reasons[:3])
    return _dedupe([note for note in notes if note])


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not value or value in seen:
            continue
        result.append(value)
        seen.add(value)
    return result


def _clamp(value: float) -> int:
    return max(0, min(100, round(value)))
