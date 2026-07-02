from __future__ import annotations

from datetime import datetime, timezone
from math import log10

from app.core.config import Settings
from app.domain.models import (
    DiscoveryEtfCandidate,
    EtfSnapshot,
    MarketDirection,
    MarketFlowResponse,
    PoolRecommendationItem,
    PoolRecommendationResponse,
)

MIN_PROMOTION_SCORE = 58
MAX_DIRECTION_SCAN = 6
MAX_WATCH_ITEMS = 9


def build_pool_recommendation_report(
    settings: Settings,
    market_flow: MarketFlowResponse,
    snapshots: dict[str, EtfSnapshot],
) -> PoolRecommendationResponse:
    current_roles = _current_roles(settings)
    scored = _score_market_candidates(market_flow)
    eligible = [item for item in scored if item.score >= MIN_PROMOTION_SCORE and item.action != "avoid"]
    recommended_main, recommended_backup = _select_recommendations(eligible)
    selected_codes = [*recommended_main, *recommended_backup]
    selected = set(selected_codes)
    selected_rank = {code: idx + 1 for idx, code in enumerate(selected_codes)}
    items: list[PoolRecommendationItem] = []

    for item in scored[:MAX_WATCH_ITEMS]:
        current_role = current_roles.get(item.code)
        recommended_role = _recommended_role(item.code, recommended_main, recommended_backup)
        action = _action(item.code, selected, current_roles, recommended_role)
        items.append(item.model_copy(update={"current_role": current_role, "recommended_role": recommended_role, "action": action, "rank": selected_rank.get(item.code)}))

    seen = {item.code for item in items}
    for code, role in current_roles.items():
        if code in seen or code in selected:
            continue
        snapshot = snapshots.get(code)
        items.append(_fixed_pool_gap_item(code, role, snapshot))

    status = _status(current_roles, recommended_main, recommended_backup)
    warnings = _warnings(market_flow, current_roles, recommended_main + recommended_backup)
    return PoolRecommendationResponse(
        generated_at=datetime.now(timezone.utc),
        source="market_flow_quant_pool_model_v1",
        status=status,
        current_main_codes=settings.main_codes,
        current_backup_codes=settings.backup_codes,
        recommended_main_codes=recommended_main,
        recommended_backup_codes=recommended_backup,
        items=items,
        warnings=warnings,
        assumptions=[
            "量化候选来自市场方向、ETF载体适配、低吸适配和风险惩罚的合成评分。",
            "该接口只输出 2 个主 ETF + 1 个备选 ETF，不自动修改配置，也不自动下单。",
            "量化入选的 ETF 会进入动作计算链路，生成低吸、止盈、防守和风控提示。",
            "免费数据源无法证明真实资金身份，资金驻留仍需多日验证或付费L2数据增强。",
        ],
    )


def _score_market_candidates(market_flow: MarketFlowResponse) -> list[PoolRecommendationItem]:
    best_by_code: dict[str, PoolRecommendationItem] = {}
    for direction in market_flow.directions[:MAX_DIRECTION_SCAN]:
        for candidate in _direction_etfs(direction):
            item = _score_candidate(direction, candidate)
            existing = best_by_code.get(item.code)
            if existing is None or item.score > existing.score:
                best_by_code[item.code] = item
    return sorted(best_by_code.values(), key=lambda item: (item.score, item.amount or 0), reverse=True)


def _direction_etfs(direction: MarketDirection) -> list[DiscoveryEtfCandidate]:
    if direction.main_etfs:
        items = [*direction.main_etfs, *([direction.backup_etf] if direction.backup_etf else [])]
    else:
        items = direction.linked_etfs[:3]
    return [item for item in items if item is not None][:3]


def _score_candidate(direction: MarketDirection, candidate: DiscoveryEtfCandidate) -> PoolRecommendationItem:
    carrier_score = candidate.mapping_score or candidate.score
    score = (
        direction.mainline_probability * 0.30
        + direction.retention_score * 0.18
        + direction.residency_score * 0.16
        + direction.low_buy_readiness_score * 0.16
        + carrier_score * 0.20
    )
    reasons = [
        f"方向主线概率 {direction.mainline_probability}",
        f"承接 {direction.retention_score}",
        f"低吸适配 {direction.low_buy_readiness_score}",
        f"ETF适配 {carrier_score}",
    ]
    risk_flags = list(direction.risk_flags[:2]) + list(candidate.risk_flags[:3])

    if direction.state == "confirmed_mainline":
        score += 5
        reasons.append("方向已确认主线")
    elif direction.state == "candidate":
        score += 2
        reasons.append("方向处于候选主线")
    elif direction.state == "hot_today":
        score -= 5
        risk_flags.append("今日强但还未验证次日承接")
    elif direction.state in {"weakening", "weak_direction"}:
        score -= 18
        risk_flags.append("方向弱化，不适合作为当前量化候选")

    if direction.trade_action == "low_buy_allowed":
        score += 6
        reasons.append("方向允许低吸")
    elif direction.trade_action == "wait_pullback_low_buy":
        score += 3
        reasons.append("方向适合等回踩低吸")
    elif direction.trade_action == "observe_next_day_retention":
        score -= 5
        risk_flags.append("需要次日承接确认")
    elif direction.trade_action == "do_not_chase_wait_pullback":
        score -= 10
        risk_flags.append("短线过热，不能追高")
    elif direction.trade_action == "avoid_or_reduce":
        score -= 18
        risk_flags.append("方向建议回避或降仓")

    if candidate.entry_bias == "pullback_watch":
        score += 6
        reasons.append("ETF处于回踩观察区")
    elif candidate.entry_bias == "watch_low_buy":
        score += 5
        reasons.append("ETF接近低吸观察区")
    elif candidate.entry_bias == "direction_hot_wait_pullback":
        score -= 8
        risk_flags.append("ETF偏热，先等回落")
    elif candidate.entry_bias == "avoid_premium":
        score -= 18
        risk_flags.append("ETF溢价风险较高")
    elif candidate.entry_bias == "wait":
        score -= 2

    amount = candidate.amount or 0
    if amount >= 300_000_000:
        score += 4
        reasons.append("成交额支持场内执行")
    elif amount < 100_000_000:
        score -= 8
        risk_flags.append("成交额偏低，执行滑点风险较高")
    else:
        score += min(3, max(0, log10(max(amount, 1) / 100_000_000) * 3))

    premium = abs(candidate.premium_pct or 0)
    if premium <= 0.6:
        score += 3
        reasons.append("溢折价可控")
    elif premium >= 2:
        score -= 15
        risk_flags.append("溢折价绝对值超过2%")
    elif premium >= 1.2:
        score -= 7
        risk_flags.append("溢折价偏高")

    inflow_pct = candidate.main_net_inflow_pct
    if inflow_pct is not None:
        if inflow_pct >= 3:
            score += 4
            reasons.append("ETF主力净流占比为正")
        elif inflow_pct <= -5:
            score -= 6
            risk_flags.append("ETF主力净流占比为负")

    final_score = _clamp(score)
    return PoolRecommendationItem(
        code=candidate.code,
        name=candidate.name,
        current_role=None,
        recommended_role=None,
        action="watch",
        score=final_score,
        rank=None,
        direction_key=direction.direction_key,
        direction_label=direction.direction_label,
        direction_state=direction.state,
        mainline_probability=direction.mainline_probability,
        low_buy_readiness_score=direction.low_buy_readiness_score,
        carrier_score=carrier_score,
        price=candidate.price,
        amount=candidate.amount,
        premium_pct=candidate.premium_pct,
        entry_bias=candidate.entry_bias,
        source_time=candidate.source_time,
        reasons=reasons[:8],
        risk_flags=_dedupe(risk_flags)[:8],
    )


def _fixed_pool_gap_item(code: str, role: str, snapshot: EtfSnapshot | None) -> PoolRecommendationItem:
    return PoolRecommendationItem(
        code=code,
        name=snapshot.name if snapshot else code,
        current_role=role,
        recommended_role=None,
        action="replace_candidate",
        score=0,
        rank=None,
        direction_key=None,
        direction_label=None,
        direction_state=None,
        mainline_probability=None,
        low_buy_readiness_score=None,
        carrier_score=None,
        price=snapshot.price if snapshot else None,
        amount=snapshot.amount if snapshot else None,
        premium_pct=snapshot.premium_pct if snapshot else None,
        entry_bias=None,
        source_time=snapshot.source_time if snapshot else None,
        reasons=["当前跟踪标的未进入量化推荐前三"],
        risk_flags=["不是当前市场流向模型优先选择的ETF载体"],
    )


def _current_roles(settings: Settings) -> dict[str, str]:
    roles: dict[str, str] = {}
    for code in settings.main_codes:
        roles[code] = "main"
    for code in settings.backup_codes:
        roles.setdefault(code, "backup")
    return roles


def _select_recommendations(eligible: list[PoolRecommendationItem]) -> tuple[list[str], list[str]]:
    main: list[PoolRecommendationItem] = []
    used_directions: set[str] = set()
    for item in eligible:
        direction = item.direction_key or item.code
        if direction in used_directions:
            continue
        main.append(item)
        used_directions.add(direction)
        if len(main) >= 2:
            break

    if len(main) < 2:
        for item in eligible:
            if any(selected.code == item.code for selected in main):
                continue
            main.append(item)
            if len(main) >= 2:
                break

    main_codes = [item.code for item in main[:2]]
    backup: list[str] = []
    for item in eligible:
        if item.code in main_codes:
            continue
        backup.append(item.code)
        break
    return main_codes, backup[:1]


def _recommended_role(code: str, main_codes: list[str], backup_codes: list[str]) -> str | None:
    if code in main_codes:
        return "main"
    if code in backup_codes:
        return "backup"
    return None


def _action(code: str, selected: set[str], current_roles: dict[str, str], recommended_role: str | None) -> str:
    if code in selected and code in current_roles:
        return "keep"
    if code in selected and code not in current_roles:
        return "promote"
    if code not in selected and code in current_roles:
        return "replace_candidate"
    if recommended_role:
        return "promote"
    return "watch"


def _status(current_roles: dict[str, str], recommended_main: list[str], recommended_backup: list[str]) -> str:
    current_codes = list(current_roles)
    recommended_codes = [*recommended_main, *recommended_backup]
    if not recommended_codes:
        return "no_recommendation"
    if not current_roles:
        return "dynamic_selection"
    if current_codes == recommended_codes:
        return "keep"
    overlap = len(set(current_codes) & set(recommended_codes))
    if overlap == 0:
        return "rotate"
    return "partial_rotate"


def _warnings(market_flow: MarketFlowResponse, current_roles: dict[str, str], recommended_codes: list[str]) -> list[str]:
    warnings: list[str] = []
    if market_flow.directions and all(item.state != "confirmed_mainline" for item in market_flow.directions[:3]):
        warnings.append("当前没有确认主线，量化候选只能视为观察清单，不宜自动执行。")
    missing = [code for code in recommended_codes if code not in current_roles]
    if missing:
        warnings.append(f"推荐ETF {', '.join(missing)} 来自动态量化筛选，不是配置硬编码。")
    warnings.append("量化候选不会自动写入配置或下单，需要人工确认。")
    return warnings


def _clamp(value: float) -> int:
    return max(0, min(100, round(value)))


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        result.append(value)
        seen.add(value)
    return result
