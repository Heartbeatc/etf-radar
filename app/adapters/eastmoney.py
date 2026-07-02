from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import httpx

from app.domain.models import DailyBar, EtfSnapshot, MinuteBar

EASTMONEY_UT = "bd1d9ddb04089700cf9c27f6f7426281"
HISTORY_UT = "7eea3edcaed734bea9cbfc24409ed989"
SPOT_ENDPOINTS = (
    "https://push2.eastmoney.com/api/qt/ulist.np/get",
    "https://push2delay.eastmoney.com/api/qt/ulist.np/get",
)


def market_id_for(code: str) -> int:
    return 1 if code.startswith(("5", "6")) else 0


class EastmoneyClient:
    def __init__(self, timeout_seconds: float = 12.0) -> None:
        self._client = httpx.AsyncClient(
            timeout=timeout_seconds,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
                ),
                "Referer": "https://quote.eastmoney.com/center/gridlist.html",
            },
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def fetch_spot(self, codes: list[str], roles: dict[str, str]) -> list[EtfSnapshot]:
        errors: list[str] = []
        for endpoint in SPOT_ENDPOINTS:
            try:
                snapshots = await self._fetch_spot_from(endpoint, codes, roles)
                self._validate_spot(codes, snapshots)
                return snapshots
            except Exception as exc:
                errors.append(f"{endpoint}: {exc}")
        raise RuntimeError("Eastmoney spot failed on all endpoints: " + " | ".join(errors))

    async def _fetch_spot_from(self, endpoint: str, codes: list[str], roles: dict[str, str]) -> list[EtfSnapshot]:
        secids = ",".join(f"{market_id_for(code)}.{code}" for code in codes)
        fields = (
            "f12,f13,f14,f2,f3,f4,f5,f6,f7,f8,f10,f15,f16,f17,f18,"
            "f21,f31,f32,f33,f38,f62,f124,f184,f402,f441"
        )
        params = {"fltt": "2", "fields": fields, "secids": secids, "ut": EASTMONEY_UT}
        payload = await self._get_json(endpoint, params=params)
        rows = ((payload.get("data") or {}).get("diff") or [])
        fetched_at = datetime.now(timezone.utc)
        return [self._spot_from_row(row, roles, fetched_at) for row in rows]

    def _validate_spot(self, codes: list[str], snapshots: list[EtfSnapshot]) -> None:
        by_code = {item.code: item for item in snapshots}
        missing = [code for code in codes if code not in by_code]
        bad_price = [item.code for item in snapshots if item.price is None or item.price <= 0]
        if missing:
            raise RuntimeError(f"missing spot rows: {','.join(missing)}")
        if bad_price:
            raise RuntimeError(f"invalid spot price: {','.join(bad_price)}")

    async def fetch_daily(self, code: str, limit_days: int = 140) -> list[DailyBar]:
        params = {
            "secid": f"{market_id_for(code)}.{code}",
            "klt": "101",
            "fqt": "1",
            "beg": "20200101",
            "end": "20500101",
            "ut": HISTORY_UT,
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        }
        payload = await self._get_json(
            "https://push2his.eastmoney.com/api/qt/stock/kline/get", params=params
        )
        klines = ((payload.get("data") or {}).get("klines") or [])[-limit_days:]
        return [self._daily_from_kline(item) for item in klines if item]

    async def fetch_minute(self, code: str) -> list[MinuteBar]:
        params = {
            "fields1": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
            "ut": HISTORY_UT,
            "ndays": "5",
            "iscr": "0",
            "secid": f"{market_id_for(code)}.{code}",
        }
        payload = await self._get_json(
            "https://push2his.eastmoney.com/api/qt/stock/trends2/get", params=params
        )
        trends = ((payload.get("data") or {}).get("trends") or [])
        return [self._minute_from_trend(item) for item in trends if item]

    async def _get_json(self, url: str, params: dict[str, str], retries: int = 3) -> dict[str, Any]:
        last_exc: Exception | None = None
        for attempt in range(retries):
            try:
                response = await self._client.get(url, params=params)
                response.raise_for_status()
                return response.json()
            except Exception as exc:
                last_exc = exc
                await asyncio.sleep(0.35 * (attempt + 1))
        raise RuntimeError(f"Eastmoney request failed: {last_exc}") from last_exc

    def _spot_from_row(
        self, row: dict[str, Any], roles: dict[str, str], fetched_at: datetime
    ) -> EtfSnapshot:
        price = _num(row.get("f2"))
        iopv = _num(row.get("f441"))
        premium_pct = None
        if price and iopv and iopv > 0:
            premium_pct = (price / iopv - 1.0) * 100.0
        source_time = _from_epoch(row.get("f124"))
        code = str(row.get("f12"))
        return EtfSnapshot(
            code=code,
            name=str(row.get("f14") or code),
            market_id=int(row.get("f13") or market_id_for(code)),
            role=roles.get(code, "benchmark"),
            source="eastmoney",
            price=price,
            change_pct=_num(row.get("f3")),
            change_amount=_num(row.get("f4")),
            volume=_num(row.get("f5")),
            amount=_num(row.get("f6")),
            amplitude_pct=_num(row.get("f7")),
            turnover_pct=_num(row.get("f8")),
            volume_ratio=_num(row.get("f10")),
            high=_num(row.get("f15")),
            low=_num(row.get("f16")),
            open=_num(row.get("f17")),
            previous_close=_num(row.get("f18")),
            bid1=_num(row.get("f31")),
            ask1=_num(row.get("f32")),
            order_imbalance_pct=_num(row.get("f33")),
            shares=_num(row.get("f38")),
            float_market_value=_num(row.get("f21")),
            main_net_inflow=_num(row.get("f62")),
            main_net_inflow_pct=_num(row.get("f184")),
            iopv=iopv,
            premium_pct=premium_pct,
            source_time=source_time,
            fetched_at=fetched_at,
        )

    def _daily_from_kline(self, item: str) -> DailyBar:
        parts = item.split(",")
        return DailyBar(
            date=parts[0],
            open=float(parts[1]),
            close=float(parts[2]),
            high=float(parts[3]),
            low=float(parts[4]),
            volume=float(parts[5]),
            amount=float(parts[6]),
            amplitude_pct=_safe_float(parts[7]),
            change_pct=_safe_float(parts[8]),
            change_amount=_safe_float(parts[9]),
            turnover_pct=_safe_float(parts[10]),
        )

    def _minute_from_trend(self, item: str) -> MinuteBar:
        parts = item.split(",")
        return MinuteBar(
            time=parts[0],
            open=float(parts[1]),
            close=float(parts[2]),
            high=float(parts[3]),
            low=float(parts[4]),
            volume=float(parts[5]),
            amount=float(parts[6]),
            vwap=_safe_float(parts[7]),
        )


def _safe_float(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _num(value: Any) -> float | None:
    if value in (None, "-", ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _from_epoch(value: Any) -> datetime | None:
    try:
        raw = int(value)
    except (TypeError, ValueError):
        return None
    if raw <= 0:
        return None
    return datetime.fromtimestamp(raw, tz=timezone.utc)
