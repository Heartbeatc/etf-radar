from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import mean

from app.domain.models import DailyBar, EtfSnapshot, MinuteBar, Position, TradePlan


@dataclass(frozen=True)
class AnalysisInputs:
    snapshot: EtfSnapshot
    daily: list[DailyBar]
    minute: list[MinuteBar]
    position: Position | None = None
    stale_seconds: int = 90


def build_plan(inputs: AnalysisInputs) -> TradePlan:
    s = inputs.snapshot
    metrics = _metrics(s, inputs.daily, inputs.minute)
    warnings: list[str] = []
    evidence: list[str] = []
    data_state = _data_state(s, inputs.stale_seconds, warnings)

    direction_score = _direction_score(s, metrics, evidence)
    low_buy_score = _low_buy_score(s, metrics, direction_score, evidence, warnings)
    hold_score = _hold_score(s, metrics, direction_score, inputs.position, evidence)
    take_profit_score = _take_profit_score(s, metrics, inputs.position, evidence)
    risk_score = _risk_score(s, metrics, warnings)

    buy_zone = _buy_zone(s, metrics)
    signal = _signal(low_buy_score, hold_score, take_profit_score, risk_score, inputs.position)
    confidence = _confidence(data_state, direction_score, low_buy_score, hold_score, risk_score)

    return TradePlan(
        code=s.code,
        name=s.name,
        role=s.role,
        data_state=data_state,
        signal=signal,
        confidence=confidence,
        direction_score=direction_score,
        low_buy_score=low_buy_score,
        hold_score=hold_score,
        take_profit_score=take_profit_score,
        risk_score=risk_score,
        current_price=s.price,
        source_time=s.source_time,
        fetched_at=s.fetched_at,
        buy_zone=buy_zone,
        hold_plan=_hold_plan(s, metrics, hold_score, inputs.position),
        take_profit_plan=_take_profit_plan(s, metrics, take_profit_score, inputs.position, buy_zone),
        exit_plan=_exit_plan(s, metrics, inputs.position, buy_zone),
        evidence=evidence[:12],
        warnings=warnings[:8],
    )


def _metrics(snapshot: EtfSnapshot, daily: list[DailyBar], minute: list[MinuteBar]) -> dict[str, float | None]:
    closes = [bar.close for bar in daily]
    highs = [bar.high for bar in daily]
    lows = [bar.low for bar in daily]
    amounts = [bar.amount for bar in daily]
    today_minutes = _today_minutes(minute)
    return {
        "ma5": _avg(closes[-5:]),
        "ma10": _avg(closes[-10:]),
        "ma20": _avg(closes[-20:]),
        "amount_ma5": _avg(amounts[-5:]),
        "amount_ma20": _avg(amounts[-20:]),
        "ret3": _ret(closes, 3, snapshot.price),
        "ret5": _ret(closes, 5, snapshot.price),
        "ret20": _ret(closes, 20, snapshot.price),
        "atr14": _atr(highs, lows, closes, 14),
        "high20": max(highs[-20:]) if len(highs) >= 20 else None,
        "low20": min(lows[-20:]) if len(lows) >= 20 else None,
        "vwap": _today_vwap(today_minutes),
        "intraday_high": max([bar.high for bar in today_minutes], default=None),
        "intraday_low": min([bar.low for bar in today_minutes], default=None),
    }


def _direction_score(s: EtfSnapshot, m: dict[str, float | None], evidence: list[str]) -> int:
    score = 50
    price = s.price
    ma5, ma10, ma20 = m["ma5"], m["ma10"], m["ma20"]
    ret5, ret20 = m["ret5"], m["ret20"]
    if price and ma20:
        if price >= ma20:
            score += 12
            evidence.append("price above MA20; trend not broken")
        elif price >= ma20 * 0.97:
            score += 4
            evidence.append("price near MA20; trend is borderline")
        else:
            score -= 16
            evidence.append("price below MA20; direction weakened")
    if price and ma5 and ma10:
        if price >= ma5 >= ma10:
            score += 10
            evidence.append("MA5 above MA10; short trend is strong")
        elif price < ma10:
            score -= 8
    if ret5 is not None:
        if ret5 > 6:
            score += 8
            evidence.append("5-day return is strong")
        elif ret5 < -6:
            score -= 10
    if ret20 is not None:
        if ret20 > 10:
            score += 8
        elif ret20 < -10:
            score -= 8
    if s.volume_ratio is not None:
        if s.volume_ratio >= 1.3:
            score += 8
            evidence.append("volume ratio above 1.3")
        elif s.volume_ratio < 0.7:
            score -= 5
    if s.main_net_inflow_pct is not None:
        if s.main_net_inflow_pct > 3:
            score += 7
            evidence.append("estimated big-order flow is positive")
        elif s.main_net_inflow_pct < -6:
            score -= 8
            evidence.append("estimated big-order flow is negative")
    return _clamp(score)


def _low_buy_score(
    s: EtfSnapshot,
    m: dict[str, float | None],
    direction_score: int,
    evidence: list[str],
    warnings: list[str],
) -> int:
    score = 30 + round(direction_score * 0.35)
    price, vwap, ma5, ma10 = s.price, m["vwap"], m["ma5"], m["ma10"]
    premium, ret3, atr = s.premium_pct, m["ret3"], m["atr14"]
    if price and vwap:
        dist = (price / vwap - 1) * 100
        if -1.2 <= dist <= 0.3:
            score += 16
            evidence.append("price near or below intraday VWAP")
        elif dist > 1.2:
            score -= 15
            warnings.append("price is too far above VWAP for low-buy")
        elif dist < -2.5:
            score -= 8
            warnings.append("price far below VWAP; confirm it is not breakdown")
    if price and ma5:
        dist = (price / ma5 - 1) * 100
        if -2.0 <= dist <= 0.8:
            score += 12
            evidence.append("price is near MA5 pullback zone")
        elif dist > 2.5:
            score -= 14
            warnings.append("price is extended above MA5")
    if price and ma10:
        dist = (price / ma10 - 1) * 100
        if -1.5 <= dist <= 2.0:
            score += 8
        elif dist < -3:
            score -= 10
    if premium is not None:
        cap = _premium_cap(s.code)
        if premium <= cap:
            score += 10
            evidence.append("IOPV premium is acceptable")
        else:
            score -= 18
            warnings.append(f"IOPV premium {premium:.2f}% is above low-buy threshold")
    if ret3 is not None:
        if ret3 > 8:
            score -= 14
            warnings.append("3-day gain is too fast; wait for pullback")
        elif -5 <= ret3 <= 1.5:
            score += 10
            evidence.append("short pullback fits low-buy style")
    if atr and price and s.amplitude_pct and s.amplitude_pct > max(6, atr / price * 100 * 1.5):
        score -= 6
        warnings.append("intraday volatility is high; split orders only")
    return _clamp(score)


def _hold_score(
    s: EtfSnapshot,
    m: dict[str, float | None],
    direction_score: int,
    position: Position | None,
    evidence: list[str],
) -> int:
    score = round(direction_score * 0.65) + 20
    price, ma10, ma20 = s.price, m["ma10"], m["ma20"]
    if price and ma10 and price >= ma10:
        score += 10
        evidence.append("price still above MA10; holding condition intact")
    elif price and ma10 and price < ma10:
        score -= 12
    if price and ma20 and price < ma20:
        score -= 18
    if position and price:
        profit = (price / position.entry_price - 1) * 100
        if profit > 0:
            score += min(8, profit / 2)
        if profit < -4:
            score -= 10
    return _clamp(score)


def _take_profit_score(
    s: EtfSnapshot,
    m: dict[str, float | None],
    position: Position | None,
    evidence: list[str],
) -> int:
    score = 35
    price, ma5, vwap = s.price, m["ma5"], m["vwap"]
    ret3, ret5, premium = m["ret3"], m["ret5"], s.premium_pct
    if position and price:
        profit = (price / position.entry_price - 1) * 100
        if profit >= 12:
            score += 24
            evidence.append("position profit above 12%; strong take-profit watch")
        elif profit >= 7:
            score += 16
            evidence.append("position profit above 7%; protect part of profit")
        elif profit >= 4:
            score += 8
    if ret3 is not None and ret3 >= 9:
        score += 16
        evidence.append("3-day gain is overheated")
    if ret5 is not None and ret5 >= 14:
        score += 18
    if price and ma5:
        dist = (price / ma5 - 1) * 100
        if dist >= 4:
            score += 16
            evidence.append("price extended above MA5")
    if price and vwap:
        dist = (price / vwap - 1) * 100
        if dist >= 1.8:
            score += 10
    if premium is not None and premium > _premium_cap(s.code) + 0.4:
        score += 12
        evidence.append("IOPV premium is elevated")
    if s.volume_ratio and s.volume_ratio >= 1.8 and s.change_pct is not None and s.change_pct < 1.0:
        score += 14
        evidence.append("volume expands but price does not rise much")
    return _clamp(score)


def _risk_score(s: EtfSnapshot, m: dict[str, float | None], warnings: list[str]) -> int:
    score = 25
    price, ma20 = s.price, m["ma20"]
    if price and ma20 and price < ma20:
        score += 22
        warnings.append("price below MA20; trend risk high")
    if s.change_pct is not None and s.change_pct <= -7:
        score += 14
        warnings.append("same-day drawdown is severe; avoid catching a falling market")
    if s.premium_pct is not None and s.premium_pct > _premium_cap(s.code) + 0.5:
        score += 18
    if s.main_net_inflow_pct is not None and s.main_net_inflow_pct < -8:
        score += 16
    if s.amplitude_pct is not None and s.amplitude_pct > 6:
        score += 8
    return _clamp(score)


def _buy_zone(s: EtfSnapshot, m: dict[str, float | None]) -> dict:
    price = s.price
    atr = m["atr14"] or (price * 0.025 if price else None)
    refs = [value for value in [m["vwap"], m["ma5"], m["ma10"]] if value]
    fair_iopv = None
    if s.iopv:
        fair_iopv = s.iopv * (1 + _premium_cap(s.code) / 100)
        refs.append(fair_iopv)
    if price:
        refs.append(price)
    anchor = min(refs) if refs else price
    if anchor and atr:
        low = max(anchor - 0.35 * atr, 0.01)
        high = anchor + 0.15 * atr
    else:
        low = high = None
    avoid = None
    if price and atr:
        avoid_candidates = [price + 0.55 * atr]
        if fair_iopv:
            avoid_candidates.append(fair_iopv)
        avoid = min(avoid_candidates)
    return {
        "zone_low": _round_price(low),
        "zone_high": _round_price(high),
        "avoid_above": _round_price(avoid),
        "reference": {
            "vwap": _round_price(m["vwap"]),
            "ma5": _round_price(m["ma5"]),
            "ma10": _round_price(m["ma10"]),
            "ma20": _round_price(m["ma20"]),
            "iopv": _round_price(s.iopv),
            "premium_pct": _round_pct(s.premium_pct),
            "atr14": _round_price(atr),
        },
        "batching": "split into 2-3 orders; do not chase above avoid_above",
    }


def _hold_plan(s: EtfSnapshot, m: dict[str, float | None], hold_score: int, position: Position | None) -> dict:
    price = s.price
    floating_profit = None
    if position and price:
        floating_profit = (price / position.entry_price - 1) * 100
    if hold_score >= 75:
        mode = "trend-hold"
    elif hold_score >= 60:
        mode = "hold-watch"
    else:
        mode = "weak-hold"
    return {
        "mode": mode,
        "floating_profit_pct": _round_pct(floating_profit),
        "expected_window": _expected_window(hold_score),
        "watch": ["MA10", "MA20", "direction_score", "IOPV premium", "volume-without-price"],
    }


def _take_profit_plan(s: EtfSnapshot, m: dict[str, float | None], score: int, position: Position | None, buy_zone: dict) -> dict:
    price = s.price
    atr = m["atr14"] or (price * 0.025 if price else None)
    entry = position.entry_price if position else buy_zone.get("zone_high")
    first = second = None
    if entry:
        first = entry * 1.06
        second = entry * 1.10
        if atr:
            first = min(first, entry + 2.0 * atr)
            second = min(second, entry + 3.2 * atr)
    if score >= 80:
        action = "strong_take_profit_sell_50pct_plus"
    elif score >= 65:
        action = "partial_take_profit_sell_20_to_30pct"
    elif score >= 50:
        action = "protect_profit_no_add"
    else:
        action = "no_active_take_profit"
    return {
        "score": score,
        "action": action,
        "first_take_profit_price": _round_price(first),
        "second_take_profit_price": _round_price(second),
        "conditions": ["profit expands and volume stalls", "price far above MA5", "premium rises", "direction_score below 60"],
    }


def _exit_plan(s: EtfSnapshot, m: dict[str, float | None], position: Position | None, buy_zone: dict) -> dict:
    price = s.price
    atr = m["atr14"] or (price * 0.025 if price else None)
    ma10, ma20 = m["ma10"], m["ma20"]
    entry = position.entry_price if position else buy_zone.get("zone_high")
    hard_stop = entry - 1.15 * atr if entry and atr else None
    trend_stop = None
    if ma10 and ma20:
        trend_stop = min(ma10 * 0.99, ma20 * 1.005)
    elif ma10:
        trend_stop = ma10 * 0.99
    stop = max([value for value in [hard_stop, trend_stop] if value], default=None)
    return {
        "hard_stop_price": _round_price(hard_stop),
        "trend_exit_price": _round_price(trend_stop),
        "effective_exit_price": _round_price(stop),
        "conditions": ["reduce on heavy-volume MA10 break", "exit on MA20 break or direction_score below 50", "if no VWAP recovery in 3 trading days after low-buy, trade thesis failed"],
    }


def _signal(low_buy_score: int, hold_score: int, take_profit_score: int, risk_score: int, position: Position | None) -> str:
    if position:
        if risk_score >= 75 or hold_score < 45:
            return "exit_first"
        if take_profit_score >= 80:
            return "strong_take_profit"
        if take_profit_score >= 65:
            return "partial_take_profit"
        if hold_score >= 65:
            return "keep_holding"
        return "hold_watch"
    if risk_score >= 75:
        return "no_trade"
    if low_buy_score >= 80:
        return "low_buy_zone"
    if low_buy_score >= 65:
        return "watch_low_buy"
    return "wait"


def _confidence(data_state: str, direction_score: int, low_buy_score: int, hold_score: int, risk_score: int) -> str:
    if data_state != "fresh":
        return "low"
    spread = max(direction_score, low_buy_score, hold_score, risk_score) - min(direction_score, low_buy_score, hold_score, risk_score)
    if spread >= 35:
        return "high"
    if spread >= 20:
        return "medium"
    return "medium-low"


def _data_state(s: EtfSnapshot, stale_seconds: int, warnings: list[str]) -> str:
    age = (datetime.now(timezone.utc) - s.fetched_at).total_seconds()
    if age > stale_seconds:
        warnings.append(f"data stale over {stale_seconds} seconds")
        return "stale"
    return "fresh"


def _expected_window(hold_score: int) -> str:
    if hold_score >= 78:
        return "T+10 to T+30, or until trend breaks"
    if hold_score >= 62:
        return "T+5 to T+15, verify while holding"
    return "T+1 to T+5, rebound only"


def _today_minutes(minute: list[MinuteBar]) -> list[MinuteBar]:
    if not minute:
        return []
    today = minute[-1].time[:10]
    return [bar for bar in minute if bar.time.startswith(today)]


def _today_vwap(minute: list[MinuteBar]) -> float | None:
    if not minute:
        return None
    amount = sum(bar.amount for bar in minute)
    volume = sum(bar.volume for bar in minute)
    if amount > 0 and volume > 0:
        return amount / (volume * 100)
    values = [bar.vwap for bar in minute if bar.vwap]
    return _avg(values)


def _avg(values: list[float]) -> float | None:
    return mean(values) if values else None


def _ret(closes: list[float], days: int, current: float | None) -> float | None:
    if len(closes) < days or not current:
        return None
    base = closes[-days]
    if base <= 0:
        return None
    return (current / base - 1) * 100


def _atr(highs: list[float], lows: list[float], closes: list[float], days: int) -> float | None:
    if len(highs) < days + 1 or len(lows) < days + 1 or len(closes) < days + 1:
        return None
    trs: list[float] = []
    for idx in range(-days, 0):
        prev_close = closes[idx - 1]
        trs.append(max(highs[idx] - lows[idx], abs(highs[idx] - prev_close), abs(lows[idx] - prev_close)))
    return mean(trs)


def _premium_cap(code: str) -> float:
    return 0.8 if code.startswith("513") else 0.45


def _clamp(value: float) -> int:
    return max(0, min(100, round(value)))


def _round_price(value: float | None) -> float | None:
    return round(value, 4) if value is not None else None


def _round_pct(value: float | None) -> float | None:
    return round(value, 2) if value is not None else None
