from __future__ import annotations

from datetime import datetime, timezone
from statistics import mean

from app.adapters.eastmoney import market_id_for
from app.domain.models import BacktestResult, BacktestTrade, DailyBar, EtfSnapshot, Position
from app.services.scoring import AnalysisInputs, build_plan

ENTRY_SIGNALS = {"low_buy_zone", "watch_low_buy"}
EXIT_SIGNALS = {"exit_first", "partial_take_profit", "strong_take_profit"}


def run_backtest(code: str, name: str, role: str, daily: list[DailyBar], days: int = 120) -> BacktestResult:
    days = max(45, min(days, 500))
    bars = daily[-days:]
    if len(bars) < 35:
        return BacktestResult(
            code=code,
            name=name,
            days=days,
            bars_used=len(bars),
            trades=[],
            trade_count=0,
            win_rate_pct=None,
            total_return_pct=0.0,
            max_drawdown_pct=0.0,
            exposure_days=0,
            latest_signal=None,
            assumptions=_assumptions(),
        )

    trades: list[BacktestTrade] = []
    position: dict | None = None
    equity = 1.0
    peak_equity = 1.0
    max_drawdown = 0.0
    exposure_days = 0
    latest_signal: str | None = None

    for idx in range(25, len(bars) - 1):
        current = bars[idx]
        prev = bars[idx - 1]
        prefix = bars[: idx + 1]
        position_model = None
        if position:
            position_model = Position(
                code=code,
                entry_price=position["entry_price"],
                shares=None,
                note="backtest",
                updated_at=datetime.now(timezone.utc),
            )
        snapshot = _snapshot_from_daily(code, name, role, current, prev, prefix)
        plan = build_plan(
            AnalysisInputs(
                snapshot=snapshot,
                daily=prefix,
                minute=[],
                position=position_model,
                stale_seconds=10**9,
            )
        )
        latest_signal = plan.signal
        next_bar = bars[idx + 1]

        if position:
            exposure_days += 1
            mark_equity = equity * (current.close / position["last_mark_price"])
            position["last_mark_price"] = current.close
            peak_equity = max(peak_equity, mark_equity)
            if peak_equity > 0:
                max_drawdown = min(max_drawdown, (mark_equity / peak_equity - 1) * 100)
            exit_reason = _exit_reason(plan, current)
            if exit_reason or idx == len(bars) - 2:
                reason = exit_reason or "period_end"
                exit_price = next_bar.open
                ret = (exit_price / position["entry_price"] - 1) * 100
                equity *= exit_price / position["entry_price"]
                trades[-1].exit_date = next_bar.date
                trades[-1].exit_price = round(exit_price, 4)
                trades[-1].return_pct = round(ret, 2)
                trades[-1].reason = reason
                position = None
            continue

        if plan.signal in ENTRY_SIGNALS and plan.risk_score < 75:
            entry_price = next_bar.open
            position = {
                "entry_date": next_bar.date,
                "entry_price": entry_price,
                "last_mark_price": entry_price,
            }
            trades.append(BacktestTrade(entry_date=next_bar.date, entry_price=round(entry_price, 4)))

    closed = [trade for trade in trades if trade.return_pct is not None]
    wins = [trade for trade in closed if (trade.return_pct or 0) > 0]
    win_rate = round(len(wins) / len(closed) * 100, 2) if closed else None
    return BacktestResult(
        code=code,
        name=name,
        days=days,
        bars_used=len(bars),
        trades=trades[-30:],
        trade_count=len(closed),
        win_rate_pct=win_rate,
        total_return_pct=round((equity - 1) * 100, 2),
        max_drawdown_pct=round(max_drawdown, 2),
        exposure_days=exposure_days,
        latest_signal=latest_signal,
        assumptions=_assumptions(),
    )


def _snapshot_from_daily(code: str, name: str, role: str, bar: DailyBar, prev: DailyBar, prefix: list[DailyBar]) -> EtfSnapshot:
    amount_values = [item.amount for item in prefix[-6:-1] if item.amount > 0]
    amount_ma5 = mean(amount_values) if amount_values else None
    volume_ratio = bar.amount / amount_ma5 if amount_ma5 else None
    change_pct = (bar.close / prev.close - 1) * 100 if prev.close > 0 else bar.change_pct
    return EtfSnapshot(
        code=code,
        name=name,
        market_id=market_id_for(code),
        role=role,
        price=bar.close,
        change_pct=change_pct,
        change_amount=bar.close - prev.close,
        volume=bar.volume,
        amount=bar.amount,
        amplitude_pct=bar.amplitude_pct,
        turnover_pct=bar.turnover_pct,
        volume_ratio=volume_ratio,
        high=bar.high,
        low=bar.low,
        open=bar.open,
        previous_close=prev.close,
        fetched_at=datetime.now(timezone.utc),
    )


def _exit_reason(plan, bar: DailyBar) -> str | None:
    stop = plan.exit_plan.get("effective_exit_price")
    if stop and bar.close <= stop:
        return "stop_or_trend_exit"
    if plan.signal in EXIT_SIGNALS:
        return plan.signal
    if plan.risk_score >= 80:
        return "risk_score_exit"
    return None


def _assumptions() -> list[str]:
    return [
        "daily-bar replay, not tick-level backtest",
        "entry/exit use next trading day's open",
        "no slippage, no commission, no liquidity constraint",
        "IOPV premium and intraday VWAP are unavailable in historical daily replay",
        "use this to validate signal direction, not to forecast guaranteed returns",
    ]
