from __future__ import annotations

from datetime import datetime, timezone

from app.domain.models import (
    MarketFlowResponse,
    QuantAlgorithmReport,
    QuantAuditFinding,
    QuantCapitalVerdict,
    QuantFrameworkResponse,
    QuantMaturityReport,
    QuantSelfAuditReport,
    QuantValidationReport,
)


def build_quant_self_audit_report(
    market_flow: MarketFlowResponse,
    framework: QuantFrameworkResponse,
    validation: QuantValidationReport,
    maturity: QuantMaturityReport,
    algorithms: QuantAlgorithmReport,
) -> QuantSelfAuditReport:
    findings = [
        _data_governance_check(market_flow, maturity),
        _signal_persistence_check(market_flow),
        _strategy_validation_check(validation, algorithms),
        _portfolio_risk_check(framework, maturity),
        _execution_check(framework, maturity),
        _model_risk_check(validation, algorithms),
        _ops_monitoring_check(maturity),
    ]
    verdict = _capital_verdict(findings, maturity)
    return QuantSelfAuditReport(
        generated_at=datetime.now(timezone.utc),
        verdict=verdict,
        proof_summary=_proof_summary(market_flow, framework, validation, maturity),
        disproof_summary=_disproof_summary(findings),
        findings=findings,
        source_refs=[
            "Federal Reserve/OCC/FDIC Model Risk Management guidance: https://www.federalreserve.gov/supervisionreg/srletters/SR2602.pdf",
            "Bailey and Lopez de Prado - Deflated Sharpe Ratio: https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf",
            "Harvey, Liu, Zhu - Multiple Testing in Expected Returns: https://www.nber.org/system/files/working_papers/w20592/w20592.pdf",
            "QuantConnect Algorithm Framework: https://www.quantconnect.com/docs/v2/writing-algorithms/algorithm-framework/overview",
        ],
        warnings=[
            "This audit intentionally treats missing evidence as failure, not as neutral.",
            "A research-grade signal is not a capital-allocation mandate.",
            "If any critical finding fails, automatic trading and large position recommendations remain disabled.",
        ],
        assumptions=[
            "Maturity is judged by evidence quality, validation, execution integrity, portfolio risk controls, and model-risk governance.",
            "Free quote and board-flow data can identify hypotheses, but cannot prove fund identity or persistent institutional accumulation.",
            "The report is an internal model-risk control layer, not investment advice.",
        ],
    )


def _data_governance_check(market_flow: MarketFlowResponse, maturity: QuantMaturityReport) -> QuantAuditFinding:
    data_gate = _gate_score(maturity, "data_governance")
    source_is_free = "free" in market_flow.source.lower() or "eastmoney" in market_flow.source.lower()
    passed = data_gate >= 82 and not source_is_free
    blockers = []
    if source_is_free:
        blockers.append("行情与资金流仍来自免费源，不能证明真实主力身份和逐笔订单行为")
    if data_gate < 82:
        blockers.append("数据治理闸门未达到生产级")
    return _finding(
        key="data_governance",
        label="数据治理是否足以承载资金级判断",
        severity="critical",
        passed=passed,
        score=min(data_gate, 68 if source_is_free else data_gate),
        claim="系统已经有行情采集、源状态、快照和数据质量检查。",
        counterargument="免费源只能形成研究假设，不能证明资金身份、盘口队列、真实成交冲击和数据完整性。",
        evidence=[f"数据源 {market_flow.source}", f"数据闸门 {data_gate}"],
        blockers=blockers,
        required_evidence=["付费或可审计行情源", "分钟/逐笔/盘口队列延迟记录", "ETF申赎、份额、IOPV和异常校验", "数据版本与缺失审计"],
    )


def _signal_persistence_check(market_flow: MarketFlowResponse) -> QuantAuditFinding:
    top = market_flow.directions[0] if market_flow.directions else None
    history_days = top.factor_scores.get("history_days", 0) if top else 0
    persistence = top.factor_scores.get("persistence", 0) if top else 0
    impulse = top.factor_scores.get("impulse_risk", 100) if top else 100
    passed = bool(top) and history_days >= 3 and persistence >= 68 and impulse <= 45 and top.state == "confirmed_mainline"
    blockers = []
    if not top:
        blockers.append("没有可用方向数据")
    if history_days < 3:
        blockers.append("前排方向缺少至少3个交易日的驻留样本")
    if persistence < 68:
        blockers.append("历史驻留持续性不足")
    if impulse > 45:
        blockers.append("一日脉冲/热点噪声风险过高")
    return _finding(
        key="signal_persistence",
        label="方向信号是否已经从热点升级为主线",
        severity="critical",
        passed=passed,
        score=_bounded((persistence * 0.45) + max(0, 100 - impulse) * 0.25 + min(30, history_days * 10)),
        claim="系统已经用市场流向、方向内扩散、代表股和ETF载体构建主线概率。",
        counterargument="没有跨交易日驻留和反证过滤，单日放量/涨幅仍可能只是热点噪声。",
        evidence=[
            f"方向 {top.direction_label if top else '-'}",
            f"状态 {top.state if top else '-'}",
            f"历史天数 {history_days}",
            f"驻留持续 {persistence}",
            f"脉冲风险 {impulse}",
        ],
        blockers=blockers,
        required_evidence=["至少3个交易日方向前排驻留", "方向内广度稳定", "代表股不断裂", "ETF载体不过度溢价且承接同步"],
    )


def _strategy_validation_check(validation: QuantValidationReport, algorithms: QuantAlgorithmReport) -> QuantAuditFinding:
    t3 = next((item for item in validation.horizon_metrics if item.horizon_days == 3), None)
    resolved = t3.resolved_count if t3 else 0
    has_overfit_layer = any(item.key == "overfit_control_pbo" and item.status == "required_validation" for item in algorithms.candidates)
    passed = validation.live_trading_ready and resolved >= 30 and not has_overfit_layer
    blockers = []
    if resolved < 30:
        blockers.append("T+3前向验证样本少于30条")
    if not validation.live_trading_ready:
        blockers.append("验证层未达到live trading ready")
    if has_overfit_layer:
        blockers.append("PBO/Deflated Sharpe仍是待建设验证层")
    return _finding(
        key="strategy_validation",
        label="策略是否经过足够回测和样本外验证",
        severity="critical",
        passed=passed,
        score=min(100, 20 + resolved * 2 + (20 if validation.live_trading_ready else 0)),
        claim="系统已经记录信号账本，并对部分信号做前向验证。",
        counterargument="样本不足、没有事件驱动回测、没有滑点手续费、没有PBO/DSR，不能排除过拟合。",
        evidence=[f"信号账本 {validation.total_records}", f"可行动信号 {validation.actionable_records}", f"T+3已验证 {resolved}"],
        blockers=blockers,
        required_evidence=["事件驱动回测", "样本外/滚动窗口验证", "手续费滑点冲击成本", "PBO或Deflated Sharpe", "参数搜索审计"],
    )


def _portfolio_risk_check(framework: QuantFrameworkResponse, maturity: QuantMaturityReport) -> QuantAuditFinding:
    gate = _gate_score(maturity, "portfolio_risk")
    passed = gate >= 82 and maturity.production_ready
    blockers = []
    if gate < 82:
        blockers.append("组合风控闸门未达生产级")
    if not maturity.production_ready:
        blockers.append("系统整体生产闸门未通过")
    return _finding(
        key="portfolio_risk",
        label="组合层风控是否足以保护真实账户",
        severity="high",
        passed=passed,
        score=gate,
        claim="系统已有单ETF研究仓位上限、风险调整和止盈防守线。",
        counterargument="没有账户NAV、现金、组合回撤、方向集中度和相关性约束，不能做资金级仓位分配。",
        evidence=[f"组合目标 {len(framework.portfolio_targets)}", f"风控调整 {len(framework.risk_adjustments)}", f"组合闸门 {gate}"],
        blockers=blockers,
        required_evidence=["账户NAV/现金", "组合最大回撤", "单方向暴露上限", "相关性/行业集中度", "日内亏损熔断"],
    )


def _execution_check(framework: QuantFrameworkResponse, maturity: QuantMaturityReport) -> QuantAuditFinding:
    gate = _gate_score(maturity, "broker_execution")
    passed = gate >= 82 and maturity.auto_trade_allowed
    contracts = sum(1 for item in framework.execution_plan if item.conditions)
    blockers = []
    if gate < 82:
        blockers.append("券商执行闸门未通过")
    if not maturity.auto_trade_allowed:
        blockers.append("自动交易总开关关闭")
    return _finding(
        key="execution_integrity",
        label="执行链路是否能真实下单并可追责",
        severity="critical",
        passed=passed,
        score=gate,
        claim="系统已有低吸/止盈/风控执行契约，可以辅助人工执行。",
        counterargument="没有券商API、订单生命周期、成交回填、撤单和持仓对账，就不能称为成熟交易系统。",
        evidence=[f"执行契约 {contracts}", f"券商执行闸门 {gate}"],
        blockers=blockers,
        required_evidence=["券商模拟账户", "订单状态机", "成交/撤单/失败回填", "持仓对账", "人工确认与审计日志"],
    )


def _model_risk_check(validation: QuantValidationReport, algorithms: QuantAlgorithmReport) -> QuantAuditFinding:
    pbo = next((item for item in algorithms.candidates if item.key == "overfit_control_pbo"), None)
    passed = validation.live_trading_ready and pbo is not None and pbo.implementation_state.startswith("已实现")
    blockers = []
    if pbo is None or not pbo.implementation_state.startswith("已实现"):
        blockers.append("过拟合控制仍未实现")
    if not validation.live_trading_ready:
        blockers.append("模型尚无足够前向验证支撑")
    return _finding(
        key="model_risk_governance",
        label="模型风险治理是否达到成熟标准",
        severity="high",
        passed=passed,
        score=35 + (20 if validation.live_trading_ready else 0),
        claim="系统已经把算法候选、适配度和生产闸门显式化。",
        counterargument="没有独立验证、参数试验记录、PBO/DSR和模型变更审批，仍可能被数据挖掘误导。",
        evidence=[f"算法候选 {len(algorithms.candidates)}", f"证据强度 {validation.evidence_strength}"],
        blockers=blockers,
        required_evidence=["独立验证报告", "参数试验审计", "模型版本与变更记录", "PBO/DSR", "上线前后表现监控"],
    )


def _ops_monitoring_check(maturity: QuantMaturityReport) -> QuantAuditFinding:
    gate = _gate_score(maturity, "ops_monitoring")
    passed = gate >= 82
    blockers = [] if passed else ["运营监控闸门未达生产级"]
    return _finding(
        key="ops_monitoring",
        label="运行监控和事故处理是否成熟",
        severity="medium",
        passed=passed,
        score=gate,
        claim="系统已有健康检查、容器化部署、信号账本和基础告警。",
        counterargument="没有关键告警确认、实盘熔断演练、事故复盘和权限分离，不能无人值守。",
        evidence=[f"运营闸门 {gate}"],
        blockers=blockers,
        required_evidence=["关键告警确认", "数据中断熔断", "交易异常熔断", "事故复盘", "权限与密钥轮换"],
    )


def _capital_verdict(findings: list[QuantAuditFinding], maturity: QuantMaturityReport) -> QuantCapitalVerdict:
    critical_failures = [item for item in findings if item.severity == "critical" and not item.passed]
    high_failures = [item for item in findings if item.severity == "high" and not item.passed]
    mature = not critical_failures and not high_failures and maturity.production_ready
    if mature:
        label = "production_candidate"
        mode = "paper_or_small_capital_with_human_review"
        action = "人工确认后小仓位执行，自动交易仍需单独审批"
        summary = "系统接近生产候选，但仍应以人工复核和资金上限运行。"
    else:
        label = "research_only"
        mode = "research_and_manual_review_only"
        action = "只允许观察、研究和人工复核后的极小仓位试验；禁止自动交易和重仓建议"
        summary = "反方审计未通过：系统不是成熟资金级量化系统，只能作为研究级辅助。"
    return QuantCapitalVerdict(
        mature=mature,
        maturity_label=label,
        capital_mode=mode,
        max_allowed_action=action,
        auto_trade_allowed=mature and maturity.auto_trade_allowed,
        summary=summary,
        hard_no=[item.label for item in [*critical_failures, *high_failures]][:8],
        conditional_yes=[
            "用于观察市场方向和形成待验证假设",
            "用于登记持仓后的人工风控提醒",
            "用于纸面交易和前向验证样本积累",
        ],
    )


def _proof_summary(
    market_flow: MarketFlowResponse,
    framework: QuantFrameworkResponse,
    validation: QuantValidationReport,
    maturity: QuantMaturityReport,
) -> list[str]:
    top = market_flow.directions[0] if market_flow.directions else None
    return [
        f"已有Universe/Alpha/Portfolio/Risk/Execution链路，执行契约 {len(framework.execution_plan)} 个。",
        f"已有生产闸门 {len(maturity.gates)} 个，当前总分 {maturity.score}。",
        f"已有信号账本 {validation.total_records} 条，可行动信号 {validation.actionable_records} 条。",
        f"当前前排方向 {top.direction_label if top else '-'} 状态 {top.state if top else '-'}，已加入历史驻留和脉冲反证。",
    ]


def _disproof_summary(findings: list[QuantAuditFinding]) -> list[str]:
    summary: list[str] = []
    for item in findings:
        if item.passed:
            continue
        blocker = item.blockers[0] if item.blockers else item.counterargument
        summary.append(f"{item.label}: {blocker}")
    return summary[:10]


def _finding(
    *,
    key: str,
    label: str,
    severity: str,
    passed: bool,
    score: int,
    claim: str,
    counterargument: str,
    evidence: list[str],
    blockers: list[str],
    required_evidence: list[str],
) -> QuantAuditFinding:
    return QuantAuditFinding(
        key=key,
        label=label,
        severity=severity,
        passed=passed,
        score=_bounded(score),
        claim=claim,
        counterargument=counterargument,
        evidence=evidence[:8],
        blockers=blockers[:8],
        required_evidence=required_evidence[:8],
    )


def _gate_score(maturity: QuantMaturityReport, key: str) -> int:
    gate = next((item for item in maturity.gates if item.key == key), None)
    return gate.score if gate else 0


def _bounded(value: float | int) -> int:
    return max(0, min(100, round(value)))
