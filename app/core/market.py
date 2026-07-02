from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

MARKET_TZ = ZoneInfo("Asia/Shanghai")


def market_status() -> str:
    now = datetime.now(MARKET_TZ)
    hhmm = now.hour * 100 + now.minute
    if now.weekday() >= 5:
        return "closed"
    if 930 <= hhmm <= 1130 or 1300 <= hhmm <= 1500:
        return "trading"
    if 1130 < hhmm < 1300:
        return "midday_break"
    if 900 <= hhmm < 930:
        return "pre_open"
    return "closed"
