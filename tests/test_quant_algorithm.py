from datetime import datetime, timedelta, timezone

from app.core.config import Settings
from app.domain.models import DiscoveryEtfCandidate, MarketDirection, MarketFlowResponse, MarketStockCandidate, PoolRecommendationResponse
from app.services.market_flow import _apply_probability_evidence_cap, _history_by_direction, _seven_day_direction_score
from app.services.pool_recommendation import build_pool_recommendation_report
from app.services.quant_decision import _etf_decisions, build_quant_decision_report


def etf(code: str, name: str, *, score: int = 76, mapping_score: int = 76, premium_pct: float = 0.2, amount: float = 300_000_000) -> DiscoveryEtfCandidate:
    return DiscoveryEtfCandidate(
        code=code,
        name=name,
        direction_key="robotics_highend",
        direction_label="机器人/高端制造",
        score=score,
        price=1.0,
        amount=amount,
        volume_ratio=1.2,
        main_net_inflow_pct=3.0,
        premium_pct=premium_pct,
        entry_bias="watch_low_buy",
        mapping_score=mapping_score,
        evidence=["test"],
        risk_flags=[],
    )


def stock(code: str, name: str, *, role: str, score: int = 80, change_pct: float = 3.0) -> MarketStockCandidate:
    return MarketStockCandidate(
        code=code,
        name=name,
        board_code="BK-test",
        board_name="机器人",
        price=20.0,
        change_pct=change_pct,
        amount=600_000_000,
        volume_ratio=1.5,
        main_net_inflow_pct=4.0,
        score=score,
        verifier_role=role,
        evidence=["test"],
        risk_flags=[],
    )


def direction(
    state: str,
    linked_etfs: list[DiscoveryEtfCandidate],
    *,
    probability: int = 82,
    low_buy: int = 68,
    linked_stocks: list[MarketStockCandidate] | None = None,
    direction_key: str = "robotics_highend",
    direction_label: str = "机器人/高端制造",
    factor_scores: dict[str, int] | None = None,
) -> MarketDirection:
    linked_stocks = linked_stocks or []
    return MarketDirection(
        direction_key=direction_key,
        direction_label=direction_label,
        score=probability,
        state=state,
        board_count=3,
        positive_board_count=3,
        total_amount=8_000_000_000,
        main_net_inflow=1_200_000_000,
        avg_change_pct=3.2,
        breadth_pct=66,
        representative_stock=linked_stocks[0] if linked_stocks else None,
        linked_stocks=linked_stocks,
        linked_etfs=linked_etfs,
        main_etfs=linked_etfs[:2],
        backup_etf=linked_etfs[2] if len(linked_etfs) > 2 else None,
        top_boards=[],
        factor_scores=factor_scores or {"history_days": 3, "persistence": 70, "impulse_risk": 35, "seven_day_score": 66},
        mainline_probability=probability,
        residency_score=72,
        retention_score=70,
        etf_confirmation_score=72,
        low_buy_readiness_score=low_buy,
        capital_status="资金驻留已确认" if state == "confirmed_mainline" else "今日资金集中，等待次日承接",
        trade_action="low_buy_allowed" if state == "confirmed_mainline" else "observe_next_day_retention",
        evidence=["test"],
        risk_flags=[],
    )


def flow_report(directions: list[MarketDirection], generated_at: datetime | None = None) -> MarketFlowResponse:
    return MarketFlowResponse(
        generated_at=generated_at or datetime.now(timezone.utc),
        source="test",
        board_count=3,
        stock_sample_count=0,
        directions=directions,
        warnings=[],
        assumptions=[],
    )


def empty_pool(items) -> PoolRecommendationResponse:
    return PoolRecommendationResponse(
        generated_at=datetime.now(timezone.utc),
        source="test",
        status="no_recommendation",
        current_main_codes=[],
        current_backup_codes=[],
        recommended_main_codes=[],
        recommended_backup_codes=[],
        items=items,
        warnings=[],
        assumptions=[],
    )


def test_mainline_probability_is_capped_without_multi_day_evidence():
    capped, cap = _apply_probability_evidence_cap(
        probability=92,
        history_days=1,
        residency=82,
        retention=80,
        flow_proxy=70,
        breadth_score=70,
        evidence_quality=80,
        linked_etfs=[etf("159770", "机器人ETF")],
        linked_stocks=[],
        impulse_risk=35,
        intraday_strength=84,
        low_buy_readiness=70,
    )

    assert cap == 52
    assert capped == 52


def test_hot_today_etf_stays_watch_only_not_promoted():
    hot = direction("hot_today", [etf("159770", "机器人ETF"), etf("562500", "机器人ETF")], probability=76, low_buy=62)
    report = build_pool_recommendation_report(Settings(main_etf_codes="", backup_etf_codes=""), flow_report([hot]), {})

    assert report.recommended_main_codes == []
    assert report.recommended_backup_codes == []
    assert report.items
    assert all(item.recommended_role is None for item in report.items)
    assert any("不会晋级" in warning for warning in report.warnings)


def test_decision_keeps_strong_related_etfs_as_observation_when_not_promoted():
    hot = direction("hot_today", [etf("159770", "机器人ETF")], probability=76, low_buy=62)
    report = build_pool_recommendation_report(Settings(main_etf_codes="", backup_etf_codes=""), flow_report([hot]), {})
    decisions = _etf_decisions(empty_pool(report.items), actions=type("Actions", (), {"items": []})())

    assert decisions
    assert decisions[0].role is None
    assert "ETF路径已降为兼容输出" in decisions[0].operation


def test_a_share_direction_penalizes_cross_border_carrier():
    domestic = etf("159770", "机器人ETF", score=70, mapping_score=70)
    cross_border = etf("513000", "港股机器人ETF", score=90, mapping_score=90)
    confirmed = direction("confirmed_mainline", [cross_border, domestic], probability=84, low_buy=70)
    report = build_pool_recommendation_report(Settings(main_etf_codes="", backup_etf_codes=""), flow_report([confirmed]), {})
    by_code = {item.code: item for item in report.items}

    assert by_code["513000"].score < by_code["159770"].score
    assert "159770" in report.recommended_main_codes


def test_quant_decision_outputs_leader_and_second_leader_not_etfs():
    leaders = [
        stock("688017", "绿的谐波", role="leader", score=90, change_pct=4.2),
        stock("002747", "埃斯顿", role="second_leader", score=84, change_pct=2.8),
        stock("002050", "三花智控", role="expansion", score=77, change_pct=1.8),
    ]
    report = build_quant_decision_report(flow_report([direction("candidate", [], probability=66, low_buy=58, linked_stocks=leaders)]))

    assert report.etfs == []
    assert [item.verifier_role for item in report.stocks[:2]] == ["leader", "second_leader"]
    assert report.stocks[0].code == "688017"
    assert any("龙头" in item and "二龙头" in item for item in report.assumptions)


def test_recent_direction_score_prefers_multi_day_residency_over_one_day_spike():
    now = datetime.now(timezone.utc)
    gold = direction("candidate", [], probability=60, direction_key="gold_resources", direction_label="黄金/资源")
    filler_a = direction("candidate", [], probability=48, direction_key="innovative_drug", direction_label="创新药/医药")
    filler_b = direction("candidate", [], probability=47, direction_key="dividend_value", direction_label="红利/央企价值")
    robot_spike = direction("hot_today", [], probability=85, direction_key="robotics_highend", direction_label="机器人/高端制造")
    history = [
        flow_report([gold, filler_a, filler_b, robot_spike], generated_at=now - timedelta(days=offset))
        for offset in range(3)
    ]
    history.append(flow_report([robot_spike], generated_at=now - timedelta(days=9)))

    stats = _history_by_direction(history)

    assert stats["robotics_highend"].days_count == 3
    assert _seven_day_direction_score(stats["gold_resources"]) > _seven_day_direction_score(stats["robotics_highend"])


def test_stock_execution_outputs_probe_only_when_price_and_acceptance_pass():
    leaders = [stock("002747", "埃斯顿", role="leader", score=86, change_pct=2.5)]
    report = build_quant_decision_report(flow_report([direction("confirmed_mainline", [], probability=78, low_buy=70, linked_stocks=leaders)]))
    item = report.stocks[0]

    assert item.action == "BUY_PROBE"
    assert item.execution is not None
    assert item.execution.decision_state == "buy_probe"
    assert item.execution.buy_zone_low is not None
    assert item.execution.buy_zone_low <= item.price <= item.execution.buy_zone_high
    assert "小仓" in item.execution.decision_reason


def test_stock_execution_waits_when_price_hits_but_direction_not_confirmed():
    leaders = [stock("002747", "埃斯顿", role="leader", score=86, change_pct=2.5)]
    candidate = direction(
        "candidate",
        [],
        probability=66,
        low_buy=58,
        linked_stocks=leaders,
        factor_scores={"history_days": 2, "persistence": 55, "impulse_risk": 35, "seven_day_score": 58},
    )
    report = build_quant_decision_report(flow_report([candidate]))
    item = report.stocks[0]

    assert item.action == "WAIT_CONFIRMATION"
    assert item.execution is not None
    assert item.execution.decision_state == "wait_confirmation"
    assert any(condition.key == "direction_phase" and condition.status == "pending" for condition in item.execution.conditions)
    assert "价格到了" in item.execution.decision_reason



def test_stock_execution_does_not_upgrade_weak_verifier_to_buy():
    weak = [stock("002050", "三花智控", role="expansion", score=68, change_pct=2.5)]
    report = build_quant_decision_report(flow_report([direction("confirmed_mainline", [], probability=78, low_buy=70, linked_stocks=weak)]))
    item = report.stocks[0]

    assert item.action == "WAIT_CONFIRMATION"
    assert item.execution is not None
    assert any(condition.key == "stock_quality" and condition.status == "pending" for condition in item.execution.conditions)
    assert "验证方向" in item.execution.conditions[-1].reason



def test_stock_execution_contains_after_buy_exit_rules():
    leaders = [stock("002747", "埃斯顿", role="leader", score=86, change_pct=2.5)]
    report = build_quant_decision_report(flow_report([direction("confirmed_mainline", [], probability=78, low_buy=70, linked_stocks=leaders)]))
    execution = report.stocks[0].execution

    assert execution is not None
    assert "净流入" in execution.reduce_signal
    assert "防守价" in execution.hard_exit_signal
    assert "资金" in execution.after_buy_plan
    assert "主力" in execution.capital_exit_signal
