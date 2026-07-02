from __future__ import annotations

from datetime import datetime, timezone

from app.domain.models import (
    QuantAlgorithmCandidate,
    QuantAlgorithmReport,
    QuantFrameworkResponse,
    QuantMaturityReport,
    QuantValidationReport,
)


def build_quant_algorithm_report(
    framework: QuantFrameworkResponse,
    validation: QuantValidationReport,
    maturity: QuantMaturityReport,
) -> QuantAlgorithmReport:
    candidates = _catalog(framework, validation, maturity)
    candidates.sort(key=lambda item: (_status_rank(item.status), item.fit_score), reverse=True)
    return QuantAlgorithmReport(
        generated_at=datetime.now(timezone.utc),
        current_stack=_current_stack(framework, validation, maturity),
        recommended_next=_recommended_next(candidates, validation, maturity),
        candidates=candidates,
        warnings=_warnings(validation, maturity),
        assumptions=[
            "算法选择参考经典量化文献与开源量化框架分层，先做可验证策略族，再考虑更复杂模型。",
            "当前免费行情源适合研究级方向轮动和人工执行，不适合无人值守自动交易。",
            "候选算法的fit_score表示与当前系统和数据条件的适配度，不表示未来收益率。",
            "没有事件驱动回测、滑点、手续费、延迟和前向验证前，任何Alpha都不能视为可实盘自动化策略。",
        ],
    )


def _catalog(
    framework: QuantFrameworkResponse,
    validation: QuantValidationReport,
    maturity: QuantMaturityReport,
) -> list[QuantAlgorithmCandidate]:
    research_score = _module_score(maturity, "research")
    execution_score = _module_score(maturity, "execution")
    portfolio_score = _module_score(maturity, "portfolio_risk")
    validation_score = _module_score(maturity, "backtest")
    data_score = _module_score(maturity, "data")
    resolved_t3 = _resolved(validation, 3)
    insight_count = len(framework.insights)
    target_count = len(framework.portfolio_targets)
    contract_count = sum(1 for item in framework.execution_plan if item.conditions)
    actionable_count = validation.actionable_records

    candidates = [
        _candidate(
            key="regime_time_series_momentum",
            label="市场状态过滤的ETF趋势/动量",
            family="趋势跟随/时间序列动量",
            status="recommended",
            fit_score=58 + min(18, insight_count * 3) + (8 if research_score >= 65 else 0) + (6 if contract_count else 0),
            implementation_state="部分已实现：已有主线阶段、方向强度、ETF载体和执行契约；缺少多周期历史、波动率目标仓位和严格回测。",
            why_it_matters="它回答的不是今天一笔钱去了哪里，而是某个方向是否已形成可持续趋势，并用市场状态过滤减少追高。",
            required_data=["行业/概念方向强度序列", "ETF日线与分钟线", "成交额与换手", "波动率", "前向收益验证"],
            current_support=[f"Alpha insight {insight_count} 条", f"执行契约 {contract_count} 个", f"研究模块 {research_score} 分"],
            evidence=framework.validation.passed + [f"T+3已验证 {resolved_t3} 条"],
            gaps=["缺少1到12个月多窗口动量统计", "缺少波动率目标仓位", "缺少跨市场状态的样本外验证"],
            next_actions=["实现20/60/120日趋势与动量特征", "加入波动率缩放仓位", "按牛/震荡/弱势市场分别验证胜率和回撤"],
            source_refs=[
                "Moskowitz, Ooi, Pedersen - Time Series Momentum: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2089463",
                "QuantConnect Algorithm Framework: https://www.quantconnect.com/docs/v2/writing-algorithms/algorithm-framework/overview",
            ],
        ),
        _candidate(
            key="cross_sectional_momentum_rotation",
            label="横截面方向轮动",
            family="横截面动量/相对强弱",
            status="recommended",
            fit_score=54 + min(18, len(framework.universe) * 2) + min(10, target_count * 3) + (6 if data_score >= 65 else 0),
            implementation_state="部分已实现：全市场方向发现、ETF候选映射和2主1备池已存在；缺少形成期/持有期参数验证。",
            why_it_matters="它把资金从弱方向切到强方向，适合ETF轮动，但必须处理拥挤、反转和换手成本。",
            required_data=["全市场方向排名历史", "ETF映射表", "成交额容量", "换手成本", "多周期收益排名"],
            current_support=[f"Universe {len(framework.universe)} 个资产", f"组合目标 {target_count} 个", f"数据模块 {data_score} 分"],
            evidence=[item.source_insight for item in framework.portfolio_targets[:3]],
            gaps=["缺少3/6/12个月形成期与1/3/5日执行窗口验证", "缺少调仓频率和交易成本约束", "缺少方向拥挤度惩罚"],
            next_actions=["沉淀每日方向排名快照", "实现相对强弱分层回测", "加入成交额容量和换手惩罚"],
            source_refs=[
                "Jegadeesh and Titman - Returns to Buying Winners and Selling Losers: https://www.bauer.uh.edu/rsusmel/phd/jegadeesh-titman93.pdf",
                "Qlib AI-oriented Quantitative Investment Platform: https://arxiv.org/abs/2009.11189",
            ],
        ),
        _candidate(
            key="trend_pullback_mean_reversion",
            label="趋势内低吸均值回归",
            family="均值回归/执行时机",
            status="recommended",
            fit_score=50 + min(22, contract_count * 5) + (8 if execution_score >= 55 else 0) + min(8, actionable_count),
            implementation_state="部分已实现：低吸区间、风险分、价格条件和阻断条件已机器化；缺少趋势过滤后的事件回测。",
            why_it_matters="它适合你的低吸高抛风格：只在强方向回撤到合理价格且承接质量够时出手，而不是价格到了就买。",
            required_data=["ETF分钟线", "VWAP/均线/ATR", "溢价率", "成交额承接", "失败样本回放"],
            current_support=[f"执行契约 {contract_count} 个", f"执行模块 {execution_score} 分", f"可行动信号 {actionable_count} 条"],
            evidence=[item.decision_reason for item in framework.execution_plan[:3]],
            gaps=["缺少回撤深度与反弹质量的历史分布", "缺少低吸失败后的退出统计", "缺少日内滑点模型"],
            next_actions=["把价格到位与趋势承接拆成独立闸门", "记录每次等待/触发/失败样本", "回测不同低吸分阈值的盈亏比"],
            source_refs=[
                "Lo and MacKinlay - Stock Market Prices Do Not Follow Random Walks: https://rodneywhitecenter.wharton.upenn.edu/wp-content/uploads/2014/04/8705.pdf",
                "Zipline event-driven backtesting: https://zipline.ml4trading.io/",
            ],
        ),
        _candidate(
            key="overfit_control_pbo",
            label="过拟合控制与样本外验证",
            family="研究验证/模型风险",
            status="required_validation",
            fit_score=44 + min(22, validation_score // 2) + min(18, resolved_t3 * 2),
            implementation_state="待建设：已有前向信号账本，但没有CSCV/PBO、Deflated Sharpe和样本外切分。",
            why_it_matters="它不直接产生买卖点，但决定一个看起来很准的策略是不是回测过拟合。没有它，收益曲线越漂亮反而越危险。",
            required_data=["完整历史信号", "参数搜索记录", "样本内/样本外切分", "交易成本", "收益分布"],
            current_support=[f"信号账本 {validation.total_records} 条", f"T+3已验证 {resolved_t3} 条", f"验证模块 {validation_score} 分"],
            evidence=validation.warnings[:3],
            gaps=["没有参数搜索审计", "没有组合对称交叉验证", "没有过拟合概率和显著性输出"],
            next_actions=["建设事件驱动回测", "记录每次参数试验", "输出PBO/样本外收益/最大回撤/换手"],
            source_refs=[
                "Bailey and Lopez de Prado - The Probability of Backtest Overfitting: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253",
            ],
        ),
        _candidate(
            key="mean_variance_portfolio",
            label="均值方差组合优化",
            family="组合优化",
            status="later",
            fit_score=34 + min(18, portfolio_score // 4) + (8 if target_count >= 3 else 0),
            implementation_state="暂不适合优先做：系统有目标仓位雏形，但没有账户NAV、现金、协方差矩阵和稳定预期收益估计。",
            why_it_matters="它用于解决多个资产之间如何分配权重，而不是发现主线本身。ETF数量少且数据短时，容易估计误差很大。",
            required_data=["账户净值和现金", "ETF收益协方差", "预期收益", "约束条件", "再平衡成本"],
            current_support=[f"组合目标 {target_count} 个", f"组合风控模块 {portfolio_score} 分"],
            evidence=[item.target_reason for item in framework.portfolio_targets[:3]],
            gaps=["缺少协方差矩阵", "缺少账户层仓位和现金", "预期收益估计不稳定"],
            next_actions=["先录入账户NAV/现金", "用波动率等权作为过渡", "等历史样本足够后再做约束优化"],
            source_refs=[
                "Markowitz - Portfolio Selection: https://finance.martinsewell.com/capm/Markowitz1952.pdf",
            ],
        ),
        _candidate(
            key="factor_risk_model",
            label="因子风险模型",
            family="风险归因/多因子",
            status="later",
            fit_score=32 + min(18, research_score // 4) + (6 if data_score >= 70 else 0),
            implementation_state="暂不适合优先做：当前主要是ETF和板块层数据，缺少个股暴露、财务因子和稳定风险因子收益。",
            why_it_matters="它能解释收益来自市场、风格还是行业暴露，但不是短线ETF买卖信号的第一优先级。",
            required_data=["个股级日频/财务/行业数据", "因子暴露", "因子收益", "ETF成分权重", "风险归因"],
            current_support=[f"特征行 {len(framework.features)} 条", f"研究模块 {research_score} 分"],
            evidence=[item.generated_from for item in framework.insights[:3]],
            gaps=["缺少成分股穿透", "缺少稳定因子库", "缺少因子收益和残差风险估计"],
            next_actions=["先完成ETF成分和方向映射", "再做行业/主题暴露归因", "最后接多因子风险模型"],
            source_refs=[
                "Fama and French - Common risk factors in stock and bond returns: https://www.sciencedirect.com/science/article/pii/0304405X93900235",
            ],
        ),
        _candidate(
            key="pairs_stat_arb",
            label="配对/价差统计套利",
            family="统计套利",
            status="not_now",
            fit_score=24 + min(12, len(framework.universe)) + (6 if validation.live_trading_ready else 0),
            implementation_state="不建议现在做：当前目标是2主ETF+1备选，不是大量可交易对的中性组合。",
            why_it_matters="配对交易依赖稳定价差关系和大量候选对，与当前主线方向低吸系统目标不同。",
            required_data=["大量同类ETF或个股", "长期价差历史", "协整/距离检验", "双腿成交", "融资融券或对冲工具"],
            current_support=[f"Universe {len(framework.universe)} 个资产"],
            evidence=[],
            gaps=["ETF池太小", "没有双腿执行", "没有价差稳定性检验"],
            next_actions=["暂不投入", "等数据和交易工具支持后再评估"],
            source_refs=[
                "Gatev, Goetzmann, Rouwenhorst - Pairs Trading: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=141615",
            ],
        ),
        _candidate(
            key="optimal_execution",
            label="最优执行/冲击成本控制",
            family="交易执行",
            status="blocked",
            fit_score=22 + min(18, execution_score // 3) + (8 if maturity.auto_trade_allowed else 0),
            implementation_state="被数据和券商链路阻断：没有订单簿、真实成交回报、撤单和冲击成本估计。",
            why_it_matters="资金量变大后，买卖价格本身会影响收益；但在人工小额ETF交易阶段，它不是最先要做的Alpha。",
            required_data=["盘口队列", "订单簿深度", "真实成交回报", "撤单延迟", "冲击成本"],
            current_support=[f"执行模块 {execution_score} 分"],
            evidence=maturity.production_blockers[:3],
            gaps=["没有券商API", "没有订单生命周期", "没有冲击成本模型"],
            next_actions=["先做纸面交易", "接券商模拟/实盘API前增加人工确认", "有订单数据后再建执行模型"],
            source_refs=[
                "Almgren and Chriss - Optimal Execution of Portfolio Transactions: https://www.smallake.kr/wp-content/uploads/2016/03/optliq.pdf",
            ],
        ),
    ]
    return _apply_research_caps(candidates, validation, maturity)


def _apply_research_caps(
    candidates: list[QuantAlgorithmCandidate],
    validation: QuantValidationReport,
    maturity: QuantMaturityReport,
) -> list[QuantAlgorithmCandidate]:
    score_cap = 100
    if not validation.live_trading_ready:
        score_cap = min(score_cap, 78)
    if validation.actionable_records < 30:
        score_cap = min(score_cap, 72)
    if not maturity.production_ready:
        score_cap = min(score_cap, 82)

    capped: list[QuantAlgorithmCandidate] = []
    for item in candidates:
        if item.status in {"recommended", "required_validation"}:
            capped.append(item.model_copy(update={"fit_score": min(item.fit_score, score_cap)}))
        else:
            capped.append(item)
    return capped


def _candidate(
    *,
    key: str,
    label: str,
    family: str,
    status: str,
    fit_score: int,
    implementation_state: str,
    why_it_matters: str,
    required_data: list[str],
    current_support: list[str],
    evidence: list[str],
    gaps: list[str],
    next_actions: list[str],
    source_refs: list[str],
) -> QuantAlgorithmCandidate:
    return QuantAlgorithmCandidate(
        key=key,
        label=label,
        family=family,
        status=status,
        fit_score=_bounded(fit_score),
        implementation_state=implementation_state,
        why_it_matters=why_it_matters,
        required_data=required_data[:8],
        current_support=[item for item in current_support if item][:8],
        evidence=[item for item in evidence if item][:8],
        gaps=gaps[:8],
        next_actions=next_actions[:8],
        source_refs=source_refs[:6],
    )


def _current_stack(framework: QuantFrameworkResponse, validation: QuantValidationReport, maturity: QuantMaturityReport) -> list[str]:
    return [
        f"Universe: {len(framework.universe)}个方向/ETF/持仓进入统一资产池",
        f"Alpha: {len(framework.insights)}条方向与载体信号，仍是规则化研究因子",
        f"Portfolio: {len(framework.portfolio_targets)}个目标仓位，研究总仓位受限",
        f"Risk: {len(framework.risk_adjustments)}个风控调整，自动交易={ '允许' if maturity.auto_trade_allowed else '关闭' }",
        f"Execution: {len(framework.execution_plan)}个低吸/持仓执行契约，仅人工执行",
        f"Validation: {validation.total_records}条信号账本，证据强度={validation.evidence_strength}",
    ]


def _recommended_next(
    candidates: list[QuantAlgorithmCandidate],
    validation: QuantValidationReport,
    maturity: QuantMaturityReport,
) -> list[str]:
    recommended = [item.label for item in candidates if item.status == "recommended"][:3]
    steps = [
        "优先策略族: " + " / ".join(recommended),
        "先把方向轮动和趋势内低吸做成事件驱动回测，不先上复杂机器学习。",
        "每个参数变更都要落库，输出样本外收益、最大回撤、换手、滑点后收益。",
        "在PBO/样本外验证通过前，系统只能给人工执行建议，不能自动下单。",
    ]
    if validation.actionable_records < 30:
        steps.append("当前可行动样本不足30条，下一步先积累前向验证样本。")
    if not maturity.production_ready:
        steps.append("生产闸门未通过，券商执行、账户NAV和监控熔断仍需补齐。")
    return steps


def _warnings(validation: QuantValidationReport, maturity: QuantMaturityReport) -> list[str]:
    warnings = [
        "算法适配度不是收益预测，不能单独作为买卖依据。",
        "当前最适合做ETF方向轮动和趋势内低吸，不适合直接做高频、配对套利或无人自动交易。",
    ]
    if validation.actionable_records < 30:
        warnings.append("前向验证样本不足，所有信号仍属研究假设。")
    if not maturity.production_ready:
        warnings.append("生产闸门未通过，必须人工复核后交易。")
    return warnings


def _module_score(maturity: QuantMaturityReport, key: str) -> int:
    module = next((item for item in maturity.modules if item.key == key), None)
    return module.score if module else 0


def _resolved(validation: QuantValidationReport, horizon_days: int) -> int:
    metric = next((item for item in validation.horizon_metrics if item.horizon_days == horizon_days), None)
    return metric.resolved_count if metric else 0


def _status_rank(status: str) -> int:
    ranks = {
        "recommended": 5,
        "required_validation": 4,
        "later": 3,
        "not_now": 2,
        "blocked": 1,
    }
    return ranks.get(status, 0)


def _bounded(value: int) -> int:
    return max(0, min(100, value))
