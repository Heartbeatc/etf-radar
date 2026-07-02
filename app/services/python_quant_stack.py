from __future__ import annotations

from datetime import datetime, timezone
from statistics import mean

from app.domain.models import (
    PythonQuantCapability,
    PythonQuantReference,
    PythonQuantStackReport,
    QuantAlgorithmReport,
    QuantFrameworkResponse,
    QuantMaturityReport,
    QuantValidationReport,
)


SOURCE_REFS = [
    "Backtrader official docs: https://www.backtrader.com/",
    "Zipline/Quantopian event-driven backtesting: https://github.com/quantopian/zipline",
    "vectorbt official docs: https://vectorbt.dev/",
    "Alphalens official repository: https://github.com/quantopian/alphalens",
    "pyfolio-reloaded official repository: https://github.com/stefan-jansen/pyfolio-reloaded",
    "PyPortfolioOpt official docs: https://pyportfolioopt.readthedocs.io/",
    "Microsoft Qlib official docs: https://qlib.readthedocs.io/",
    "Deflated Sharpe Ratio paper: https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf",
]


def build_python_quant_stack_report(
    framework: QuantFrameworkResponse,
    validation: QuantValidationReport,
    maturity: QuantMaturityReport,
    algorithms: QuantAlgorithmReport,
) -> PythonQuantStackReport:
    references = _references()
    capabilities = _capabilities(framework, validation, maturity, algorithms)
    readiness_score = round(mean([item.score for item in capabilities])) if capabilities else 0
    current_level = _current_level(readiness_score, maturity.production_ready, validation.live_trading_ready)
    return PythonQuantStackReport(
        generated_at=datetime.now(timezone.utc),
        current_level=current_level,
        readiness_score=readiness_score,
        verdict=_verdict(current_level, readiness_score),
        references=references,
        capabilities=capabilities,
        adoption_sequence=_adoption_sequence(capabilities),
        source_refs=SOURCE_REFS,
        warnings=_warnings(capabilities, maturity, validation),
        assumptions=[
            "成熟Python量化体系不是单个库，而是数据、研究、回测、组合、执行、风控、验证和审计的闭环。",
            "本报告把Backtrader/Zipline/vectorbt/Alphalens/pyfolio/PyPortfolioOpt/Qlib等框架的成熟抽象映射到当前系统。",
            "当前系统先采用这些框架的分层思想和验证标准；是否引入具体库，要以数据质量、部署复杂度和可审计性为准。",
            "没有样本外验证、交易成本、滑点、订单生命周期和组合风险约束前，任何信号都只能是研究假设。",
        ],
    )


def _references() -> list[PythonQuantReference]:
    return [
        _ref(
            "backtrader",
            "Backtrader",
            "事件驱动回测/交易框架",
            "https://www.backtrader.com/",
            ["Strategy", "Data Feed", "Broker", "Analyzer", "Sizer"],
            "借鉴事件驱动、Broker、Analyzer抽象；短期不直接依赖库。",
        ),
        _ref(
            "zipline",
            "Zipline",
            "事件流回测与防未来函数",
            "https://github.com/quantopian/zipline",
            ["event-driven", "order delay", "slippage", "transaction cost", "pipeline"],
            "借鉴事件驱动回放、滑点/手续费和延迟建模。",
        ),
        _ref(
            "vectorbt",
            "vectorbt",
            "向量化研究与参数扫描",
            "https://vectorbt.dev/",
            ["pandas/NumPy arrays", "parameter sweep", "portfolio records", "fast research"],
            "适合作为后续批量参数扫描和研究回测方向。",
        ),
        _ref(
            "alphalens",
            "Alphalens",
            "因子有效性分析",
            "https://github.com/quantopian/alphalens",
            ["factor quantiles", "forward returns", "information coefficient", "turnover"],
            "当前方向因子必须补IC/RankIC/分层收益后，才接近因子研究标准。",
        ),
        _ref(
            "pyfolio",
            "pyfolio",
            "组合绩效与风险分析",
            "https://github.com/stefan-jansen/pyfolio-reloaded",
            ["tear sheet", "drawdown", "risk metrics", "returns analysis"],
            "用于定义未来回测报告形态：收益、回撤、胜率、换手、暴露。",
        ),
        _ref(
            "pyportfolioopt",
            "PyPortfolioOpt",
            "组合优化",
            "https://pyportfolioopt.readthedocs.io/",
            ["efficient frontier", "Black-Litterman", "HRP", "risk models"],
            "等账户NAV、协方差、约束和足够历史数据后再引入。",
        ),
        _ref(
            "qlib",
            "Microsoft Qlib",
            "研究到生产的AI量化工作流",
            "https://qlib.readthedocs.io/",
            ["dataset", "model", "backtest", "workflow", "recorder"],
            "借鉴实验记录、工作流和模型评估，不急于引入复杂ML。",
        ),
    ]


def _capabilities(
    framework: QuantFrameworkResponse,
    validation: QuantValidationReport,
    maturity: QuantMaturityReport,
    algorithms: QuantAlgorithmReport,
) -> list[PythonQuantCapability]:
    data_gate = _gate_score(maturity, "data_governance")
    alpha_gate = _gate_score(maturity, "alpha_research")
    validation_gate = _gate_score(maturity, "strategy_validation")
    portfolio_gate = _gate_score(maturity, "portfolio_risk")
    execution_gate = _gate_score(maturity, "broker_execution")
    ops_gate = _gate_score(maturity, "ops_monitoring")
    t3 = next((item for item in validation.horizon_metrics if item.horizon_days == 3), None)
    resolved_t3 = t3.resolved_count if t3 else 0
    has_pbo_candidate = any(item.key == "overfit_control_pbo" for item in algorithms.candidates)

    return [
        _cap(
            key="data_portal",
            label="Data Portal / 数据入口",
            reference_stack=["Qlib Dataset", "Zipline Data Portal", "Backtrader Data Feed"],
            current_state="已有实时快照、日线缓存、源状态和Kafka/ClickHouse基础设施，但仍是免费行情源。",
            score=min(data_gate, 68),
            adoption_state="research_only",
            implemented_evidence=[f"Universe {len(framework.universe)}", f"数据闸门 {data_gate}", "已有source-status与快照落库"],
            blockers=["缺少可审计付费行情源", "缺少分钟/逐笔/盘口队列延迟记录", "缺少点位时间数据版本管理"],
            next_actions=["定义统一DataPortal接口", "记录每条行情的source、timestamp、latency、quality", "接入更稳定ETF份额/IOPV/申赎数据"],
        ),
        _cap(
            key="vectorized_research",
            label="Vectorized Research / 向量化研究",
            reference_stack=["vectorbt", "pandas", "NumPy", "Numba"],
            current_state="当前是规则引擎实时打分，尚未形成大规模参数扫描和矩阵化研究。",
            score=35 + min(18, len(framework.features) * 2),
            adoption_state="missing_core",
            implemented_evidence=[f"特征行 {len(framework.features)}", f"算法候选 {len(algorithms.candidates)}"],
            blockers=["缺少参数网格", "缺少批量回测矩阵", "缺少参数搜索记录和过拟合审计"],
            next_actions=["把方向轮动/趋势低吸参数化", "实现多参数批量回放", "每次参数试验落库并关联验证结果"],
        ),
        _cap(
            key="event_backtest",
            label="Event-driven Backtest / 事件驱动回测",
            reference_stack=["Backtrader Cerebro", "Zipline event stream", "LEAN Algorithm Framework"],
            current_state="已有简化日线回测和前向信号账本，但不是完整事件驱动交易模拟。",
            score=min(72, validation_gate + (8 if resolved_t3 >= 10 else 0)),
            adoption_state="prototype",
            implemented_evidence=[f"信号账本 {validation.total_records}", f"T+3已验证 {resolved_t3}", "已有next-open简化回测"],
            blockers=["没有手续费/滑点/冲击成本", "没有订单延迟和成交状态", "没有分钟级事件回放", "没有持仓/现金/NAV路径"],
            next_actions=["定义Order/Fill/PortfolioState事件模型", "回测使用bar-by-bar事件循环", "输出交易、权益曲线、回撤、换手和成本后收益"],
        ),
        _cap(
            key="factor_analysis",
            label="Factor Analysis / 因子检验",
            reference_stack=["Alphalens", "Qlib Analyzer", "RankIC/IC"],
            current_state="已有方向与ETF特征，但还没有因子分层收益、IC、RankIC、换手和衰减。",
            score=min(72, alpha_gate),
            adoption_state="partial",
            implemented_evidence=[f"Insights {len(framework.insights)}", f"Features {len(framework.features)}", f"Alpha闸门 {alpha_gate}"],
            blockers=["因子没有按日期沉淀成矩阵", "没有分层收益", "没有IC/RankIC", "没有换手和衰减"],
            next_actions=["沉淀每日方向因子矩阵", "计算未来1/3/5日分层收益", "输出IC、RankIC、换手和衰减曲线"],
        ),
        _cap(
            key="portfolio_analytics",
            label="Portfolio Analytics / 绩效风险报告",
            reference_stack=["pyfolio tear sheet", "Backtrader analyzers", "vectorbt Portfolio"],
            current_state="已有胜率、前向收益、风险分，但没有完整权益曲线和组合绩效报告。",
            score=35 + min(20, validation.actionable_records) + (12 if framework.risk_adjustments else 0),
            adoption_state="partial",
            implemented_evidence=[f"风控调整 {len(framework.risk_adjustments)}", f"可行动信号 {validation.actionable_records}"],
            blockers=["没有账户权益曲线", "没有最大回撤路径", "没有暴露/换手/风险贡献", "没有基准相对收益"],
            next_actions=["保存每次回测每日NAV", "输出收益/回撤/换手/暴露/风险贡献", "加入基准ETF对比"],
        ),
        _cap(
            key="portfolio_construction",
            label="Portfolio Construction / 组合构建",
            reference_stack=["PyPortfolioOpt", "HRP", "volatility targeting"],
            current_state="已有研究仓位上限和2主1备目标，但还没有账户级优化。",
            score=min(72, portfolio_gate),
            adoption_state="guarded_partial",
            implemented_evidence=[f"组合目标 {len(framework.portfolio_targets)}", f"组合闸门 {portfolio_gate}"],
            blockers=["缺少账户NAV/现金", "缺少协方差矩阵", "缺少单方向暴露和相关性约束", "预期收益估计样本不足"],
            next_actions=["先做波动率目标仓位", "录入账户NAV/现金", "样本足够后再比较等权/波动率等权/HRP"],
        ),
        _cap(
            key="model_risk_validation",
            label="Model Risk / 过拟合与模型风险",
            reference_stack=["Deflated Sharpe", "PBO/CSCV", "SR 26-2 model risk"],
            current_state="已有反方审计和过拟合候选，但PBO/DSR仍未实现。",
            score=30 + (12 if has_pbo_candidate else 0) + min(20, resolved_t3 * 2),
            adoption_state="required_before_capital",
            implemented_evidence=["已有反方审计", f"PBO候选 {'存在' if has_pbo_candidate else '缺失'}", f"T+3样本 {resolved_t3}"],
            blockers=["缺少样本外切分", "缺少PBO/DSR", "缺少参数搜索审计", "缺少模型版本审批"],
            next_actions=["记录每次参数搜索", "实现样本内/样本外切分", "输出DSR/PBO/显著性和模型变更记录"],
        ),
        _cap(
            key="execution_broker",
            label="Execution / 纸面交易与券商执行",
            reference_stack=["Backtrader Broker", "LEAN Execution", "Zipline order model"],
            current_state="已有人工执行建议和低吸契约，但没有订单生命周期。",
            score=min(55, execution_gate),
            adoption_state="blocked",
            implemented_evidence=[f"执行计划 {len(framework.execution_plan)}", f"券商闸门 {execution_gate}"],
            blockers=["没有券商API", "没有订单状态机", "没有成交/撤单回填", "没有持仓对账"],
            next_actions=["先实现PaperBroker", "定义OrderSubmitted/PartiallyFilled/Filled/Cancelled/Rejected", "实盘前加入人工确认和风控熔断"],
        ),
        _cap(
            key="workflow_governance",
            label="Workflow / 实验与生产治理",
            reference_stack=["Qlib Recorder", "model registry", "audit trail"],
            current_state="已有容器化、信号账本和反方审计，但实验、模型、数据版本未闭环。",
            score=min(75, ops_gate + 5),
            adoption_state="partial",
            implemented_evidence=[f"运营闸门 {ops_gate}", "Docker部署", "信号账本"],
            blockers=["缺少实验ID", "缺少数据版本", "缺少模型版本和变更审批", "缺少事故复盘记录"],
            next_actions=["为每次信号生成experiment_id", "记录代码版本/参数/数据窗口", "把上线条件和回滚条件写入审计日志"],
        ),
    ]


def _ref(
    key: str,
    label: str,
    role: str,
    source_url: str,
    patterns: list[str],
    adoption_decision: str,
) -> PythonQuantReference:
    return PythonQuantReference(
        key=key,
        label=label,
        role=role,
        source_url=source_url,
        patterns=patterns,
        adoption_decision=adoption_decision,
    )


def _cap(
    *,
    key: str,
    label: str,
    reference_stack: list[str],
    current_state: str,
    score: int,
    adoption_state: str,
    implemented_evidence: list[str],
    blockers: list[str],
    next_actions: list[str],
) -> PythonQuantCapability:
    return PythonQuantCapability(
        key=key,
        label=label,
        reference_stack=reference_stack[:6],
        current_state=current_state,
        score=_bounded(score),
        adoption_state=adoption_state,
        implemented_evidence=[item for item in implemented_evidence if item][:8],
        blockers=blockers[:8],
        next_actions=next_actions[:8],
    )


def _adoption_sequence(capabilities: list[PythonQuantCapability]) -> list[str]:
    by_key = {item.key: item for item in capabilities}
    ordered = [
        "1. DataPortal: 先把行情、ETF份额、IOPV、延迟、质量和版本统一成可审计数据入口。",
        "2. Event-driven Backtest: 把当前简化日线回测升级为Order/Fill/PortfolioState事件模型。",
        "3. Factor Analysis: 对主线/方向/ETF载体因子做IC、RankIC、分层收益、换手和衰减。",
        "4. Vectorized Research: 对趋势轮动和趋势内低吸做参数扫描，但所有参数试验必须落库。",
        "5. Portfolio Analytics: 输出类似pyfolio的收益、回撤、暴露、换手、基准对比和风险贡献。",
        "6. Model Risk: 上PBO/Deflated Sharpe/样本外验证，过不了就不能升级资金级。",
        "7. PaperBroker: 先纸面交易和成交回填，再考虑券商API。",
    ]
    if by_key.get("data_portal") and by_key["data_portal"].score < 70:
        ordered.insert(1, "当前优先级修正：数据源不够硬，所有回测和AI分析必须打研究级标签。")
    return ordered


def _current_level(score: int, production_ready: bool, live_ready: bool) -> str:
    if production_ready and live_ready and score >= 85:
        return "production_candidate"
    if score >= 70 and live_ready:
        return "paper_trading_candidate"
    if score >= 55:
        return "research_framework"
    return "research_prototype"


def _verdict(level: str, score: int) -> str:
    labels = {
        "production_candidate": "接近生产候选，但仍需人工复核、资金上限和独立验证。",
        "paper_trading_candidate": "可进入纸面交易候选，但仍不能自动实盘。",
        "research_framework": "已经有量化框架雏形，但核心回测、因子验证和执行链路不足。",
        "research_prototype": "仍是研究原型，距离成熟Python量化体系有明显差距。",
    }
    return f"{labels[level]} 当前Python量化成熟度 {score}/100。"


def _warnings(
    capabilities: list[PythonQuantCapability],
    maturity: QuantMaturityReport,
    validation: QuantValidationReport,
) -> list[str]:
    warnings = [
        "不能因为使用Python或借鉴成熟框架，就默认策略具备收益能力。",
        "库解决的是研究和工程流程，不能替代数据质量、策略有效性和风控验证。",
    ]
    failed_core = [item.label for item in capabilities if item.score < 60 and item.key in {"data_portal", "event_backtest", "model_risk_validation", "execution_broker"}]
    if failed_core:
        warnings.append("核心能力不足: " + " / ".join(failed_core[:4]))
    if validation.actionable_records < 30:
        warnings.append("前向验证样本不足30条，暂不具备统计显著性。")
    if not maturity.production_ready:
        warnings.append("生产闸门未通过，系统只能服务研究和人工复核。")
    return warnings


def _gate_score(maturity: QuantMaturityReport, key: str) -> int:
    gate = next((item for item in maturity.gates if item.key == key), None)
    return gate.score if gate else 0


def _bounded(value: int) -> int:
    return max(0, min(100, round(value)))
