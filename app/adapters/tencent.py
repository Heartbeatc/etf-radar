from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any

import httpx

from app.adapters.eastmoney import market_id_for
from app.domain.models import EtfSnapshot

TENCENT_QUOTE_URL = "https://qt.gtimg.cn/q="
CN_TZ = timezone(timedelta(hours=8))


class TencentQuoteClient:
    def __init__(self, timeout_seconds: float = 8.0) -> None:
        self._client = httpx.AsyncClient(
            timeout=timeout_seconds,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
                ),
                "Referer": "https://stockapp.finance.qq.com/",
            },
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def fetch_spot(self, codes: list[str], roles: dict[str, str]) -> list[EtfSnapshot]:
        symbols = ",".join(_symbol_for(code) for code in codes)
        response = await self._client.get(TENCENT_QUOTE_URL + symbols)
        response.raise_for_status()
        text = response.content.decode("gbk", errors="replace")
        snapshots = self._parse_response(text, roles)
        self._validate(codes, snapshots)
        return snapshots

    def _parse_response(self, text: str, roles: dict[str, str]) -> list[EtfSnapshot]:
        fetched_at = datetime.now(timezone.utc)
        snapshots: list[EtfSnapshot] = []
        for raw_line in text.split(";"):
            line = raw_line.strip()
            if not line or "=" not in line:
                continue
            payload = line.split("=", 1)[1].strip()
            if payload.startswith('"'):
                payload = payload[1:]
            if payload.endswith('"'):
                payload = payload[:-1]
            parts = payload.split("~")
            if len(parts) < 36:
                continue
            code = _part(parts, 2)
            if not code:
                continue
            snapshots.append(self._snapshot_from_parts(code, parts, roles, fetched_at))
        return snapshots

    def _validate(self, codes: list[str], snapshots: list[EtfSnapshot]) -> None:
        by_code = {item.code: item for item in snapshots}
        missing = [code for code in codes if code not in by_code]
        bad_price = [item.code for item in snapshots if item.price is None or item.price <= 0]
        if missing:
            raise RuntimeError(f"missing tencent spot rows: {','.join(missing)}")
        if bad_price:
            raise RuntimeError(f"invalid tencent spot price: {','.join(bad_price)}")

    def _snapshot_from_parts(
        self,
        code: str,
        parts: list[str],
        roles: dict[str, str],
        fetched_at: datetime,
    ) -> EtfSnapshot:
        price = _num(_part(parts, 3))
        iopv = _num(_part(parts, 78))
        premium_pct = _num(_part(parts, 77))
        if premium_pct is None and price and iopv and iopv > 0:
            premium_pct = (price / iopv - 1.0) * 100.0
        return EtfSnapshot(
            code=code,
            name=_part(parts, 1) or code,
            market_id=market_id_for(code),
            role=roles.get(code, "benchmark"),
            source="tencent",
            price=price,
            change_pct=_num(_part(parts, 32)),
            change_amount=_num(_part(parts, 31)),
            volume=_num(_part(parts, 36)) or _num(_part(parts, 6)),
            amount=_amount(parts),
            amplitude_pct=_num(_part(parts, 43)),
            turnover_pct=_num(_part(parts, 38)),
            volume_ratio=_num(_part(parts, 49)),
            high=_num(_part(parts, 33)) or _num(_part(parts, 41)),
            low=_num(_part(parts, 34)) or _num(_part(parts, 42)),
            open=_num(_part(parts, 5)),
            previous_close=_num(_part(parts, 4)),
            bid1=_positive(_part(parts, 9)),
            ask1=_positive(_part(parts, 19)),
            shares=_num(_part(parts, 72)),
            float_market_value=_num(_part(parts, 73)),
            iopv=iopv,
            premium_pct=premium_pct,
            source_time=_source_time(_part(parts, 30)),
            fetched_at=fetched_at,
        )


def _symbol_for(code: str) -> str:
    return ("sh" if market_id_for(code) == 1 else "sz") + code


def _part(parts: list[str], index: int) -> str | None:
    if index >= len(parts):
        return None
    value = parts[index].strip()
    return value or None


def _num(value: Any) -> float | None:
    if value in (None, "", "-", "~"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _positive(value: Any) -> float | None:
    number = _num(value)
    if number is None or number <= 0:
        return None
    return number


def _amount(parts: list[str]) -> float | None:
    packed = _part(parts, 35)
    if packed:
        pieces = packed.split("/")
        if len(pieces) >= 3:
            amount = _num(pieces[2])
            if amount is not None:
                return amount
    amount_wan = _num(_part(parts, 57)) or _num(_part(parts, 37))
    return amount_wan * 10000 if amount_wan is not None else None


def _source_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.strptime(value, "%Y%m%d%H%M%S")
    except ValueError:
        return None
    return dt.replace(tzinfo=CN_TZ).astimezone(timezone.utc)
