from __future__ import annotations

from datetime import datetime, timezone
from statistics import mean

from app.domain.models import (
    MarketFlowResponse,
    PoolRecommendationResponse,
    QuantFrameworkResponse,
    QuantMaturityModule,
    QuantMaturityReport,
    QuantProductionGate,
    QuantValidationReport,
)


def build_quant_maturity_report(
    market_flow: MarketFlowResponse,
    pool: PoolRecommendationResponse,
    framework: QuantFrameworkResponse,
    validation: QuantValidationReport,
) -> QuantMaturityReport:
    modules = [
        _data_module(market_flow, pool),
        _research_module(framework),
        _portfolio_risk_module(framework),
        _execution_module(framework),
        _backtest_module(validation),
        _monitoring_module(framework, validation),
    ]
    gates = _production_gates(modules, framework, validation)
    production_ready = all(gate.status == "pass" for gate in gates)
    score = round(mean([item.score for item in modules])) if modules else 0
    gate_score = round(mean([item.score for item in gates])) if gates else score
    combined_score = round(score * 0.65 + gate_score * 0.35)
    grade = _grade(combined_score, framework.validation.live_trading_ready, validation.live_trading_ready, production_ready)
    production_blockers = _production_blockers(gates)
    next_upgrades = _next_upgrades(gates)
    return QuantMaturityReport(
        generated_at=datetime.now(timezone.utc),
        grade=grade,
        score=combined_score,
        verdict=_verdict(grade, production_ready),
        modules=modules,
        production_ready=production_ready,
        auto_trade_allowed=production_ready and grade == "production_quant",
        gates=gates,
        production_blockers=production_blockers,
        next_upgrades=next_upgrades,
        warnings=_warnings(grade, modules, production_blockers),
        assumptions=[
            "量化系统成熟度按数据、研究、组合风控、执行、回测验证、监控六项评估。",
            "生产级闸门对照真实量化系统的Universe、Alpha、Portfolio、Risk、Execution、Validation闭环。",
            "没有券商交易适配器、成交回报和撤单链路时，系统只能输出人工执行建议。",
            "免费行情源可用于研究级信号，不足以证明真实主力资金身份。",
            "回测样本不足时，任何 BUY 信号都应视为研究假设，而不是统计显著结论。",
        ],
    )


def _data_module(market_flow: MarketFlowResponse, pool: PoolRecommendationResponse) -> QuantMaturityModule:
    score = 55
    evidence = []
    gaps = ["缺少付费Level-2、盘口队列和更稳定的ETF申赎/份额数据"]
    if market_flow.directions:
        score += 10
        evidence.append(f"方向样本 {len(market_flow.directions)} 个")
    if pool.items:
        score += 8
        evidence.append(f"ETF载体候选 {len(pool.items)} 个")
    if market_flow.source:
        evidence.append(f"行情来源 {market_flow.source}")
    return _module("data", "数据层", score, evidence, gaps)


def _research_module(framework: QuantFrameworkResponse) -> QuantMaturityModule:
    has_contracts = all(item.conditions for item in framework.execution_plan)
    score = 45 + min(20, len(framework.features) * 2) + (15 if has_contracts else 0)
    evidence = [
        f"Universe {len(framework.universe)}",
        f"Features {len(framework.features)}",
        f"Insights {len(framework.insights)}",
    ]
    if has_contracts:
        evidence.append("执行候选已输出条件契约")
    gaps = ["因子权重仍需多日样本验证", "缺少因子IC、换手、衰减和分层收益统计"]
    return _module("research", "研究与Alpha", score, evidence, gaps)


def _portfolio_risk_module(framework: QuantFrameworkResponse) -> QuantMaturityModule:
    score = 50 + (12 if framework.portfolio_targets else 0) + (18 if framework.risk_adjustments else 0)
    evidence = [
        f"组合目标 {len(framework.portfolio_targets)} 个",
        f"风控调整 {len(framework.risk_adjustments)} 个",
        "单ETF与总研究仓位已设上限",
    ]
    gaps = ["缺少账户现金/NAV输入", "缺少组合层回撤、相关性和行业暴露约束"]
    return _module("portfolio_risk", "组合与风控", score, evidence, gaps)


def _execution_module(framework: QuantFrameworkResponse) -> QuantMaturityModule:
    buy_ready = [item for item in framework.execution_plan if item.decision_state in {"ready", "buy_ready"}]
    contracts = [item for item in framework.execution_plan if item.conditions]
    score = 35 + min(20, len(contracts) * 5)
    evidence = [f"执行计划 {len(framework.execution_plan)} 个", f"买入就绪 {len(buy_ready)} 个"]
    if contracts:
        evidence.append("价格/分数/风险/数据条件已机器化")
    gaps = ["没有券商API/订单回报/撤单/成交回填", "当前只能人工复核后执行"]
    return _module("execution", "执行层", score, evidence, gaps)


def _backtest_module(validation: QuantValidationReport) -> QuantMaturityModule:
    t3 = next((item for item in validation.horizon_metrics if item.horizon_days == 3), None)
    resolved = t3.resolved_count if t3 else 0
    score = 20 + min(35, resolved * 3)
    evidence = [f"信号账本 {validation.total_records} 条", f"可行动信号 {validation.actionable_records} 条"]
    if t3:
        evidence.append(f"T+3已验证 {t3.resolved_count}/{t3.sample_count}")
        if t3.win_rate_pct is not None:
            evidence.append(f"T+3胜率 {t3.win_rate_pct:.1f}%")
    gaps = ["样本量不足，不能证明统计显著", "缺少完整策略级历史回放、滑点和手续费模型"]
    return _module("backtest", "回测与验证", score, evidence, gaps)


def _monitoring_module(framework: QuantFrameworkResponse, validation: QuantValidationReport) -> QuantMaturityModule:
    score = 45
    if framework.warnings is not None:
        score += 10
    if validation.recent_records:
        score += 10
    evidence = ["已有信号落库与前向验证账本", f"近期信号 {len(validation.recent_records)} 条"]
    gaps = ["缺少实盘订单监控、异常熔断、通知确认和人工复核闭环"]
    return _module("monitoring", "监控与审计", score, evidence, gaps)


def _production_gates(
    modules: list[QuantMaturityModule],
    framework: QuantFrameworkResponse,
    validation: QuantValidationReport,
) -> list[QuantProductionGate]:
    by_key = {item.key: item for item in modules}
    t3 = next((item for item in validation.horizon_metrics if item.horizon_days == 3), None)
    resolved_t3 = t3.resolved_count if t3 else 0
    validation_score = min(100, 25 + resolved_t3 * 3 + (15 if validation.live_trading_ready else 0))
    execution_contracts = sum(1 for item in framework.execution_plan if item.conditions)

    return [
        _gate_from_module(
            by_key["data"],
            key="data_governance",
            label="数据治理",
            pass_score=82,
            warn_score=65,
            fallback_blockers=["缺少可审计的数据供应商、分钟级稳定性和成交流校验"],
            next_actions=["接入更稳定行情源", "记录每次行情快照的数据版本、延迟和异常原因"],
        ),
        _gate_from_module(
            by_key["research"],
            key="alpha_research",
            label="Alpha研究",
            pass_score=82,
            warn_score=65,
            fallback_blockers=["缺少因子IC、分层收益、换手和衰减统计"],
            next_actions=["为方向因子增加IC/RankIC与分层收益报表", "沉淀多日样本后重新估计权重"],
        ),
        _gate(
            key="strategy_validation",
            label="策略验证",
            score=validation_score,
            status="pass" if validation.live_trading_ready and resolved_t3 >= 30 else "warn" if resolved_t3 >= 10 else "fail",
            evidence=[f"T+3已验证 {resolved_t3} 条", f"信号账本 {validation.total_records} 条"],
            blockers=[] if validation.live_trading_ready and resolved_t3 >= 30 else ["前向验证样本不足", "缺少事件驱动历史回放、滑点、手续费和订单延迟模型"],
            next_actions=["建设事件驱动回测", "加入手续费、冲击成本、滑点和延迟假设", "输出胜率、盈亏比、最大回撤和样本显著性"],
        ),
        _gate_from_module(
            by_key["portfolio_risk"],
            key="portfolio_risk",
            label="组合风控",
            pass_score=82,
            warn_score=65,
            fallback_blockers=["缺少账户NAV、现金、组合回撤、相关性和集中度约束"],
            next_actions=["录入账户净值和现金", "增加组合最大回撤、单方向暴露、相关性和日内亏损熔断"],
        ),
        _gate(
            key="broker_execution",
            label="券商执行",
            score=min(55, 25 + execution_contracts * 8),
            status="fail",
            evidence=[f"执行契约 {execution_contracts} 个", "当前只输出人工执行建议"],
            blockers=["没有券商API", "没有订单状态、撤单、成交回填和持仓对账"],
            next_actions=["先接模拟交易/纸面交易账户", "定义订单生命周期：提交、部分成交、撤单、失败、回填", "实盘前增加人工确认闸门"],
        ),
        _gate_from_module(
            by_key["monitoring"],
            key="ops_monitoring",
            label="运营监控",
            pass_score=82,
            warn_score=65,
            fallback_blockers=["缺少实盘告警确认、异常熔断和人工复核闭环"],
            next_actions=["增加关键告警确认", "记录每次建议、人工确认和执行结果", "增加数据中断/行情异常熔断"],
        ),
    ]


def _gate_from_module(
    module: QuantMaturityModule,
    *,
    key: str,
    label: str,
    pass_score: int,
    warn_score: int,
    fallback_blockers: list[str],
    next_actions: list[str],
) -> QuantProductionGate:
    status = "pass" if module.score >= pass_score else "warn" if module.score >= warn_score else "fail"
    blockers = [] if status == "pass" else (module.gaps or fallback_blockers)
    return _gate(key, label, module.score, status, module.evidence, blockers, next_actions)


def _gate(
    key: str,
    label: str,
    score: int,
    status: str,
    evidence: list[str],
    blockers: list[str],
    next_actions: list[str],
) -> QuantProductionGate:
    return QuantProductionGate(
        key=key,
        label=label,
        status=status,
        score=max(0, min(100, score)),
        evidence=evidence[:6],
        blockers=blockers[:6],
        next_actions=next_actions[:6],
    )


def _module(key: str, label: str, score: int, evidence: list[str], gaps: list[str]) -> QuantMaturityModule:
    bounded = max(0, min(100, score))
    if bounded >= 80:
        status = "strong"
    elif bounded >= 65:
        status = "usable"
    elif bounded >= 45:
        status = "research_grade"
    else:
        status = "prototype"
    return QuantMaturityModule(key=key, label=label, status=status, score=bounded, evidence=evidence[:6], gaps=gaps[:6])


def _grade(score: int, framework_live: bool, validation_live: bool, production_ready: bool) -> str:
    if production_ready and score >= 82 and framework_live and validation_live:
        return "production_quant"
    if score >= 68 and validation_live:
        return "paper_trading_quant"
    if score >= 50:
        return "research_quant"
    return "quant_prototype"


def _verdict(grade: str, production_ready: bool) -> str:
    if not production_ready:
        return "达到研究级/半自动决策标准，但生产闸门未全部通过，不能自动实盘。"
    return {
        "production_quant": "已接近可自动交易量化系统，但仍需实盘风控复核。",
        "paper_trading_quant": "达到模拟交易/半自动研究系统标准，不适合无人值守实盘。",
        "research_quant": "达到研究级量化系统标准，可输出可审计信号，但不能直接自动实盘。",
        "quant_prototype": "仍是原型级，信号只能作为观察参考。",
    }[grade]


def _production_blockers(gates: list[QuantProductionGate]) -> list[str]:
    blockers: list[str] = []
    for gate in gates:
        if gate.status == "pass":
            continue
        for blocker in gate.blockers:
            blockers.append(f"{gate.label}: {blocker}")
    return blockers[:10]


def _next_upgrades(gates: list[QuantProductionGate]) -> list[str]:
    upgrades: list[str] = []
    for gate in gates:
        if gate.status == "pass":
            continue
        for action in gate.next_actions:
            if action not in upgrades:
                upgrades.append(action)
    return upgrades[:10]


def _warnings(grade: str, modules: list[QuantMaturityModule], production_blockers: list[str]) -> list[str]:
    warnings: list[str] = []
    if grade != "production_quant":
        warnings.append("当前不是可自动下单的生产级量化系统。")
    if production_blockers:
        warnings.append("生产闸门未通过：" + "；".join(production_blockers[:3]))
    weak = [item.label for item in modules if item.score < 60]
    if weak:
        warnings.append("薄弱模块：" + "、".join(weak))
    warnings.append("任何买入都必须同时满足执行契约条件，并由人工复核。")
    return warnings
