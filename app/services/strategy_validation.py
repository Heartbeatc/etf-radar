from __future__ import annotations

from datetime import datetime, timezone

from app.adapters.store import Store
from app.domain.models import (
    BacktestResult,
    QuantDecisionResponse,
    QuantStockDecision,
    StrategySpec,
    StrategySpecRule,
    StrategyValidationItem,
    StrategyValidationReport,
)
from app.services.backtest import run_backtest

MIN_BARS_FOR_VALIDATION = 60
MIN_TRADES_FOR_PASS = 3
PASS_MIN_WIN_RATE = 50.0
PASS_MIN_TOTAL_RETURN = 0.0
PASS_MAX_DRAWDOWN = -15.0


def build_strategy_validation_report(store: Store, decision: QuantDecisionResponse, days: int = 120) -> StrategyValidationReport:
    normalized_days = max(60, min(days, 500))
    strategy = build_current_strategy_spec(decision)
    items = [_validate_item(store, item, normalized_days) for item in _validation_universe(decision)]
    pass_count = sum(1 for item in items if item.validation_state == "passed")
    fail_count = sum(1 for item in items if item.validation_state == "failed")
    warning_count = len(items) - pass_count - fail_count
    return StrategyValidationReport(
        generated_at=datetime.now(timezone.utc),
        days=normalized_days,
        strategy=strategy,
        items=items,
        pass_count=pass_count,
        warning_count=warning_count,
        fail_count=fail_count,
        assumptions=[
            "当前验证使用系统内置日线回放，目的是给交易建议加闸门，不是收益承诺。",
            "通过条件要求样本数量、胜率、总收益和最大回撤同时达标；不达标的候选只能观察。",
            "LEAN integration status 为 adapter_pending：下一阶段会把 StrategySpec 导出到 LEAN 做事件驱动回测。",
            "PandoraTrader 更偏 CTP/期货高频交易执行网关；当前 A股人工执行系统暂不接实盘柜台。",
            "免费数据缺少 Level-2、完整盘口、真实滑点和手续费，验证结论必须保守使用。",
        ],
    )


def validation_universe_codes(decision: QuantDecisionResponse) -> list[str]:
    return [item["code"] for item in _validation_universe(decision)]


def build_current_strategy_spec(decision: QuantDecisionResponse) -> StrategySpec:
    direction = decision.direction
    return StrategySpec(
        id="a_share_direction_pullback_v1",
        name="A股主线方向内低吸策略",
        version="1.0.0",
        generated_at=datetime.now(timezone.utc),
        engine="internal_daily_replay",
        direction_key=direction.direction_key,
        direction_label=direction.direction_label,
        universe=_strategy_universe(decision),
        entry_rules=[
            _rule("direction_phase", "方向阶段", "in", "confirmed_or_candidate", "只在主线确认或候选阶段内寻找交易机会。"),
            _rule("mainline_probability", "主线概率", ">=", 55, "主线概率低于阈值时不主动开仓。"),
            _rule("residency_retention", "资金驻留/承接", ">=", "45/45", "资金不能只有单日脉冲，至少要有驻留或承接证据。"),
            _rule("stock_rank", "龙头/二龙/扩散排序", ">=", "top_candidates", "优先选择方向内强度、成交额和资金流代理更靠前的个股。"),
            _rule("pullback_zone", "低吸区", "touch", "buy_zone", "价格进入低吸区只是必要条件，还要等承接条件同时满足。"),
        ],
        exit_rules=[
            _rule("hard_stop", "硬止损", "<=", "stop_price", "跌破策略止损价先控制亏损，不等待AI反向确认。"),
            _rule("weak_exit", "弱势退出", "<=", "weak_exit_price", "趋势弱化或主力撤退时减仓或离场。"),
            _rule("take_profit", "止盈", ">=", "take_profit_price", "达到止盈参考后按仓位和主线状态分批处理。"),
            _rule("thesis_break", "交易假设失效", "trigger", "capital_exit_signal", "方向资金撤退、个股不再前排或放量跌破时退出。"),
        ],
        risk_rules=[
            _rule("validation_gate", "验证闸门", "required", "passed_or_watch", "未通过或数据不足时，动作降级为观察，不作为直接买入依据。"),
            _rule("risk_budget", "账户风控", "<=", "risk_budget", "单票金额不得超过账户风险预算。"),
            _rule("no_blind_average_down", "禁止盲目补仓", "required", "thesis_valid", "只有交易假设仍成立才允许加仓。"),
            _rule("data_state", "数据状态", "required", "fresh_or_snapshot", "盘后和节假日只能看快照，不产生新买点。"),
        ],
        position_rules=[
            _rule("first_probe", "首次试仓", "<=", "1/3 planned", "首次买入只做试仓，避免一次性押注。"),
            _rule("single_name_cap", "单票上限", "<=", "15% assets", "单票暴露过高时只允许减仓，不允许继续加。"),
            _rule("cash_buffer", "现金缓冲", ">=", "10% assets", "保留现金应对失败样本和二次确认。"),
        ],
        assumptions=[
            "策略定义来自当前量化规则，不由 AI 即兴生成。",
            "AI只负责风险解释和复核，不直接生成买卖价格。",
            "当前系统先做人工执行建议，暂不自动下单。",
        ],
    )


def _validate_item(store: Store, item: dict[str, str], days: int) -> StrategyValidationItem:
    bars = store.get_daily_bars(item["code"])
    if len(bars) < MIN_BARS_FOR_VALIDATION:
        return StrategyValidationItem(
            code=item["code"],
            name=item["name"],
            role=item["role"],
            action=item["action"],
            backtest=None,
            validation_state="insufficient_data",
            validation_label="数据不足",
            validation_score=max(0, min(35, len(bars) // 2)),
            blockers=[f"历史日线仅 {len(bars)} 根，少于 {MIN_BARS_FOR_VALIDATION} 根"],
            notes=["先补历史数据或继续观察，不把当前信号当作可验证交易机会。"],
        )

    backtest = run_backtest(item["code"], item["name"], item["role"], bars, days=days)
    state, label, score, blockers, notes = _classify_backtest(backtest)
    return StrategyValidationItem(
        code=item["code"],
        name=item["name"],
        role=item["role"],
        action=item["action"],
        backtest=backtest,
        validation_state=state,
        validation_label=label,
        validation_score=score,
        blockers=blockers,
        notes=notes,
    )


def _classify_backtest(result: BacktestResult) -> tuple[str, str, int, list[str], list[str]]:
    blockers: list[str] = []
    notes: list[str] = []
    score = 45

    if result.trade_count >= MIN_TRADES_FOR_PASS:
        score += 15
    else:
        blockers.append(f"有效交易 {result.trade_count} 笔，少于 {MIN_TRADES_FOR_PASS} 笔")
        score -= 15

    if result.win_rate_pct is not None and result.win_rate_pct >= PASS_MIN_WIN_RATE:
        score += 15
    elif result.win_rate_pct is None:
        blockers.append("没有已完成交易，无法计算胜率")
    else:
        blockers.append(f"胜率 {result.win_rate_pct:.2f}% 低于 {PASS_MIN_WIN_RATE:.0f}%")
        score -= 10

    if result.total_return_pct > PASS_MIN_TOTAL_RETURN:
        score += 15
    else:
        blockers.append(f"回测总收益 {result.total_return_pct:.2f}% 未转正")
        score -= 15

    if result.max_drawdown_pct >= PASS_MAX_DRAWDOWN:
        score += 10
    else:
        blockers.append(f"最大回撤 {result.max_drawdown_pct:.2f}% 超过 {abs(PASS_MAX_DRAWDOWN):.0f}% 容忍线")
        score -= 15

    if result.latest_signal:
        notes.append(f"最近策略信号 {result.latest_signal}")
    notes.append(f"回放 {result.bars_used} 根日线，暴露 {result.exposure_days} 天")
    score = max(0, min(100, score))

    if not blockers and score >= 75:
        return "passed", "通过", score, blockers, notes
    if result.trade_count >= MIN_TRADES_FOR_PASS and (result.total_return_pct < -3 or result.max_drawdown_pct < PASS_MAX_DRAWDOWN):
        return "failed", "失败", score, blockers, notes
    if result.trade_count == 0:
        return "insufficient_signal", "信号不足", score, blockers, notes
    return "watch", "观察", score, blockers, notes


def _validation_universe(decision: QuantDecisionResponse) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    seen: set[str] = set()
    for holding in decision.holdings:
        _append_item(items, seen, holding.code, holding.name, "holding", holding.action)
    for stock in decision.bottom_candidates[:5]:
        _append_stock(items, seen, stock)
    for stock in decision.stocks[:5]:
        _append_stock(items, seen, stock)
    return items[:8]


def _append_stock(items: list[dict[str, str]], seen: set[str], stock: QuantStockDecision) -> None:
    role = stock.verifier_role or stock.bottom_state or "candidate"
    _append_item(items, seen, stock.code, stock.name, role, stock.action)


def _append_item(items: list[dict[str, str]], seen: set[str], code: str, name: str, role: str, action: str) -> None:
    if not code or code in seen:
        return
    seen.add(code)
    items.append({"code": code, "name": name or code, "role": role, "action": action or "WATCH"})


def _strategy_universe(decision: QuantDecisionResponse) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for item in _validation_universe(decision):
        code = item["code"]
        if code not in seen:
            seen.add(code)
            values.append(code)
    return values


def _rule(key: str, label: str, operator: str, threshold: float | int | str | None, description: str) -> StrategySpecRule:
    return StrategySpecRule(key=key, label=label, operator=operator, threshold=threshold, description=description)
