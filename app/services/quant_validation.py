from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from statistics import mean, median
from typing import Iterable

from app.adapters.store import Store
from app.domain.models import DailyBar, QuantCodeValidationItem, QuantForwardMetric, QuantSignalRecord, QuantValidationReport

IMMEDIATE_SIDES = {"BUY", "SELL", "HOLD", "AVOID"}
LOW_BUY_ACTIONS = {"WAIT_BUY_ZONE", "WATCH_LOW_BUY", "WAIT_PULLBACK", "WAIT"}
DEFAULT_HORIZONS = (1, 3, 5)


def build_quant_validation_report(store: Store, horizons: Iterable[int] = DEFAULT_HORIZONS, limit: int = 5000) -> QuantValidationReport:
    records = store.quant_signal_history(limit=limit)
    testable = [item for item in records if _is_testable_signal(item)]
    daily_cache: dict[str, list[DailyBar]] = {}
    normalized_horizons = tuple(sorted({max(1, int(item)) for item in horizons}))
    horizon_returns: dict[int, list[float]] = {item: [] for item in normalized_horizons}
    code_returns_3d: dict[str, list[float]] = defaultdict(list)
    by_code_records: dict[str, list[QuantSignalRecord]] = defaultdict(list)

    for record in testable:
        by_code_records[record.code].append(record)
        bars = daily_cache.setdefault(record.code, store.get_daily_bars(record.code))
        for horizon in normalized_horizons:
            signed_return = _forward_return(record, bars, horizon)
            if signed_return is None:
                continue
            horizon_returns[horizon].append(signed_return)
            if horizon == 3:
                code_returns_3d[record.code].append(signed_return)

    metrics = [_metric(horizon, len(testable), horizon_returns[horizon]) for horizon in normalized_horizons]
    by_code = _code_items(by_code_records, code_returns_3d)
    warnings = _warnings(records, testable, metrics)
    return QuantValidationReport(
        generated_at=datetime.now(timezone.utc),
        total_records=len(records),
        actionable_records=len(testable),
        evidence_strength=_evidence_strength(metrics),
        live_trading_ready=False,
        horizon_metrics=metrics,
        by_code=by_code,
        recent_records=records[:20],
        warnings=warnings,
        assumptions=[
            "framework signals are deduplicated into a local signal ledger before validation",
            "BUY/HOLD success uses positive forward return; SELL/AVOID success uses negative forward return",
            "WAIT_* low-buy setups are evaluated only after a later daily bar touches the trigger range",
            "low-buy setup entry uses trigger_price_high as a conservative fill and then measures T+N trading-day closes",
            "forward returns use cached daily closes and do not include commission, spread, premium drift, or intraday slippage",
            "T+1/T+3/T+5 samples remain pending until the trigger occurs and enough later daily bars exist",
            "this report validates signal behavior; it is not a live-trading permission switch",
        ],
    )


def _is_testable_signal(record: QuantSignalRecord) -> bool:
    if record.side in IMMEDIATE_SIDES or record.action == "AVOID":
        return bool(record.current_price and record.current_price > 0)
    if record.side == "WAIT" and record.action in LOW_BUY_ACTIONS:
        return _has_trigger_range(record)
    return False


def _forward_return(record: QuantSignalRecord, bars: list[DailyBar], horizon: int) -> float | None:
    if not bars:
        return None
    if record.action == "AVOID":
        return _immediate_decision_return(record, bars, horizon)
    if record.side == "WAIT" and record.action in LOW_BUY_ACTIONS:
        return _low_buy_setup_return(record, bars, horizon)
    return _immediate_decision_return(record, bars, horizon)


def _immediate_decision_return(record: QuantSignalRecord, bars: list[DailyBar], horizon: int) -> float | None:
    base_index = _base_index(record, bars)
    if base_index is None or base_index + horizon >= len(bars):
        return None
    entry_price = record.current_price or bars[base_index].close
    if entry_price <= 0:
        return None
    exit_price = bars[base_index + horizon].close
    raw_return = (exit_price / entry_price - 1) * 100
    if record.side in {"SELL", "AVOID"} or record.action == "AVOID":
        return -raw_return
    return raw_return


def _low_buy_setup_return(record: QuantSignalRecord, bars: list[DailyBar], horizon: int) -> float | None:
    base_index = _base_index(record, bars)
    if base_index is None:
        return None
    trigger_index = _trigger_index(record, bars, base_index + 1)
    if trigger_index is None or trigger_index + horizon >= len(bars):
        return None
    entry_price = record.trigger_price_high or record.trigger_price_low
    if entry_price is None or entry_price <= 0:
        return None
    exit_price = bars[trigger_index + horizon].close
    return (exit_price / entry_price - 1) * 100


def _trigger_index(record: QuantSignalRecord, bars: list[DailyBar], start_index: int) -> int | None:
    if not _has_trigger_range(record):
        return None
    low = record.trigger_price_low or record.trigger_price_high
    high = record.trigger_price_high or record.trigger_price_low
    if low is None or high is None:
        return None
    low, high = min(low, high), max(low, high)
    for index in range(max(0, start_index), len(bars)):
        bar = bars[index]
        if bar.low <= high and bar.high >= low:
            return index
    return None


def _has_trigger_range(record: QuantSignalRecord) -> bool:
    low = record.trigger_price_low
    high = record.trigger_price_high
    return low is not None and high is not None and low > 0 and high > 0


def _base_index(record: QuantSignalRecord, bars: list[DailyBar]) -> int | None:
    signal_date = record.signal_at.date().isoformat()
    candidate = None
    for index, bar in enumerate(bars):
        if bar.date <= signal_date:
            candidate = index
        if bar.date >= signal_date:
            return index
    return candidate


def _metric(horizon: int, sample_count: int, returns: list[float]) -> QuantForwardMetric:
    resolved = len(returns)
    wins = [value for value in returns if value > 0]
    return QuantForwardMetric(
        horizon_days=horizon,
        sample_count=sample_count,
        resolved_count=resolved,
        pending_count=max(0, sample_count - resolved),
        win_rate_pct=round(len(wins) / resolved * 100, 2) if resolved else None,
        avg_forward_return_pct=round(mean(returns), 2) if returns else None,
        median_forward_return_pct=round(median(returns), 2) if returns else None,
    )


def _code_items(records_by_code: dict[str, list[QuantSignalRecord]], returns_3d: dict[str, list[float]]) -> list[QuantCodeValidationItem]:
    items: list[QuantCodeValidationItem] = []
    for code, records in records_by_code.items():
        latest = max(records, key=lambda item: item.signal_at)
        returns = returns_3d.get(code, [])
        wins = [value for value in returns if value > 0]
        items.append(
            QuantCodeValidationItem(
                code=code,
                name=latest.name,
                last_signal_at=latest.signal_at,
                last_side=latest.side,
                last_action=latest.action,
                actionable_count=len(records),
                resolved_3d=len(returns),
                win_rate_3d_pct=round(len(wins) / len(returns) * 100, 2) if returns else None,
                avg_return_3d_pct=round(mean(returns), 2) if returns else None,
            )
        )
    return sorted(items, key=lambda item: (item.resolved_3d, item.avg_return_3d_pct or -999), reverse=True)[:20]


def _warnings(records: list[QuantSignalRecord], testable: list[QuantSignalRecord], metrics: list[QuantForwardMetric]) -> list[str]:
    warnings: list[str] = []
    if not records:
        warnings.append("尚无框架级信号账本；请让系统运行一段时间后再看验证结果。")
    if len(testable) < 20:
        warnings.append("可验证交易假设少于20个，只能看作日志记录，不能看作统计结论。")
    h3 = next((item for item in metrics if item.horizon_days == 3), None)
    if h3 and h3.resolved_count < 20:
        warnings.append("T+3 已完成样本少于20个，胜率和均值暂不具备交易意义。")
    return warnings


def _evidence_strength(metrics: list[QuantForwardMetric]) -> str:
    h3 = next((item for item in metrics if item.horizon_days == 3), None)
    if not h3 or h3.resolved_count < 20:
        return "low"
    if h3.resolved_count >= 60 and (h3.win_rate_pct or 0) >= 55 and (h3.avg_forward_return_pct or 0) > 0:
        return "high"
    if h3.resolved_count >= 30 and h3.avg_forward_return_pct is not None:
        return "medium"
    return "medium-low"
