from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

MARKET_TZ = ZoneInfo("Asia/Shanghai")

_A_SHARE_2026_HOLIDAY_RANGES = (
    ("2026-01-01", "2026-01-03"),
    ("2026-02-15", "2026-02-23"),
    ("2026-04-04", "2026-04-06"),
    ("2026-05-01", "2026-05-05"),
    ("2026-06-19", "2026-06-21"),
    ("2026-09-25", "2026-09-27"),
    ("2026-10-01", "2026-10-07"),
)

def _date_range(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)

_A_SHARE_2026_HOLIDAYS = frozenset(
    day
    for start, end in _A_SHARE_2026_HOLIDAY_RANGES
    for day in _date_range(date.fromisoformat(start), date.fromisoformat(end))
)


@dataclass(frozen=True)
class MarketClock:
    market_time: datetime
    status: str
    status_label: str
    is_trading_day: bool
    should_poll_realtime: bool
    last_trading_day: str | None
    next_trading_day: str | None
    note: str


def market_status() -> str:
    return market_clock().status


def market_clock(now: datetime | None = None, extra_closed_dates: list[str] | None = None) -> MarketClock:
    current = _normalize_now(now)
    today = current.date()
    closed_dates = _closed_dates(extra_closed_dates)
    is_open_day = is_trading_day(today, closed_dates=closed_dates)
    hhmm = current.hour * 100 + current.minute

    if not is_open_day:
        weekend = today.weekday() >= 5
        status = "closed_weekend" if weekend else "closed_holiday"
        label = "周末休市" if weekend else "节假日休市"
        note = "非交易日，保留最后交易日快照，不请求实时行情源。"
        return MarketClock(
            market_time=current,
            status=status,
            status_label=label,
            is_trading_day=False,
            should_poll_realtime=False,
            last_trading_day=previous_trading_day(today, closed_dates=closed_dates).isoformat(),
            next_trading_day=next_trading_day(today, closed_dates=closed_dates).isoformat(),
            note=note,
        )

    if 900 <= hhmm < 930:
        status, label, should_poll = "pre_open", "开盘前/集合竞价", True
    elif 930 <= hhmm <= 1130 or 1300 <= hhmm <= 1500:
        status, label, should_poll = "trading", "交易中", True
    elif 1130 < hhmm < 1300:
        status, label, should_poll = "midday_break", "午间休市", False
    elif hhmm > 1500:
        status, label, should_poll = "post_close", "已收盘", False
    else:
        status, label, should_poll = "closed", "非交易时段", False

    if should_poll:
        note = "交易窗口内，允许实时行情源轮询。"
    elif status == "midday_break":
        note = "午间休市，保留上午最后快照，下午开盘后恢复实时轮询。"
    else:
        note = "非交易时段，保留最后快照，不做30秒行情源轮询。"

    last_day = today if hhmm >= 930 else previous_trading_day(today, closed_dates=closed_dates)
    next_day = today if hhmm < 1500 else next_trading_day(today, closed_dates=closed_dates)
    return MarketClock(
        market_time=current,
        status=status,
        status_label=label,
        is_trading_day=True,
        should_poll_realtime=should_poll,
        last_trading_day=last_day.isoformat(),
        next_trading_day=next_day.isoformat(),
        note=note,
    )


def should_poll_realtime(now: datetime | None = None, extra_closed_dates: list[str] | None = None) -> bool:
    return market_clock(now=now, extra_closed_dates=extra_closed_dates).should_poll_realtime


def is_trading_day(value: date, closed_dates: set[date] | None = None) -> bool:
    if value.weekday() >= 5:
        return False
    return value not in (closed_dates or _A_SHARE_2026_HOLIDAYS)


def previous_trading_day(value: date, closed_dates: set[date] | None = None) -> date:
    cursor = value - timedelta(days=1)
    while not is_trading_day(cursor, closed_dates=closed_dates):
        cursor -= timedelta(days=1)
    return cursor


def next_trading_day(value: date, closed_dates: set[date] | None = None) -> date:
    cursor = value + timedelta(days=1)
    while not is_trading_day(cursor, closed_dates=closed_dates):
        cursor += timedelta(days=1)
    return cursor


def _normalize_now(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(MARKET_TZ)
    if now.tzinfo is None:
        return now.replace(tzinfo=MARKET_TZ)
    return now.astimezone(MARKET_TZ)


def _closed_dates(extra_closed_dates: list[str] | None) -> set[date]:
    result = set(_A_SHARE_2026_HOLIDAYS)
    for item in extra_closed_dates or []:
        try:
            result.add(date.fromisoformat(item))
        except ValueError:
            continue
    return result
