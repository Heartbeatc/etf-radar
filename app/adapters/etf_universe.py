from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.domain.models import EtfSnapshot

EASTMONEY_UT = "bd1d9ddb04089700cf9c27f6f7426281"
ETF_UNIVERSE_ENDPOINTS = (
    "https://push2.eastmoney.com/api/qt/clist/get",
    "https://push2delay.eastmoney.com/api/qt/clist/get",
)
ETF_UNIVERSE_FS = "b:MK0021,b:MK0022,b:MK0023,b:MK0024"
ETF_UNIVERSE_FIELDS = (
    "f12,f13,f14,f2,f3,f4,f5,f6,f7,f8,f10,f15,f16,f17,f18,"
    "f21,f62,f124,f184,f441"
)


class EastmoneyEtfUniverseClient:
    def __init__(self, timeout_seconds: float = 15.0) -> None:
        self.timeout_seconds = timeout_seconds
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
            ),
            "Referer": "https://quote.eastmoney.com/center/gridlist.html",
            "Accept": "application/json,text/plain,*/*",
            "Connection": "close",
        }

    async def close(self) -> None:
        return None

    async def fetch_universe(self, page_size: int = 100, max_pages: int = 25) -> list[EtfSnapshot]:
        fetched_at = datetime.now(timezone.utc)
        rows: list[dict[str, Any]] = []
        seen_codes: set[str] = set()
        for page in range(1, max_pages + 1):
            payload = await self._fetch_page(page, page_size)
            data = payload.get("data") or {}
            page_rows = data.get("diff") or []
            if not page_rows:
                break
            new_rows: list[dict[str, Any]] = []
            for row in page_rows:
                code = str(row.get("f12") or "")
                if not code or code in seen_codes:
                    continue
                seen_codes.add(code)
                new_rows.append(row)
            if not new_rows:
                break
            rows.extend(new_rows)
            if len(page_rows) < page_size:
                break
            await asyncio.sleep(0.12)
        snapshots = [self._snapshot_from_row(row, fetched_at) for row in rows]
        return [item for item in snapshots if item.code and item.name]

    async def _fetch_page(self, page: int, page_size: int) -> dict[str, Any]:
        params = {
            "pn": str(page),
            "pz": str(page_size),
            "po": "1",
            "np": "1",
            "ut": EASTMONEY_UT,
            "fltt": "2",
            "invt": "2",
            "fid": "f3",
            "fs": ETF_UNIVERSE_FS,
            "fields": ETF_UNIVERSE_FIELDS,
        }
        last_exc: Exception | None = None
        for attempt in range(4):
            for endpoint in ETF_UNIVERSE_ENDPOINTS:
                try:
                    return await asyncio.to_thread(self._fetch_page_sync, endpoint, params)
                except Exception as exc:
                    last_exc = exc
            await asyncio.sleep(0.35 * (attempt + 1))
        raise RuntimeError(f"Eastmoney ETF universe request failed: {last_exc}") from last_exc

    def _fetch_page_sync(self, endpoint: str, params: dict[str, str]) -> dict[str, Any]:
        url = endpoint + "?" + urlencode(params)
        request = Request(url, headers=self.headers)
        with urlopen(request, timeout=self.timeout_seconds) as response:
            raw = response.read()
        return json.loads(raw.decode("utf-8"))

    def _snapshot_from_row(self, row: dict[str, Any], fetched_at: datetime) -> EtfSnapshot:
        code = str(row.get("f12") or "")
        price = _num(row.get("f2"))
        iopv = _num(row.get("f441"))
        premium_pct = None
        if price and iopv and iopv > 0:
            premium_pct = (price / iopv - 1.0) * 100.0
        return EtfSnapshot(
            code=code,
            name=str(row.get("f14") or code),
            market_id=int(row.get("f13") or _market_id_for(code)),
            role="universe",
            source="eastmoney_universe",
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
            float_market_value=_num(row.get("f21")),
            main_net_inflow=_num(row.get("f62")),
            main_net_inflow_pct=_num(row.get("f184")),
            iopv=iopv,
            premium_pct=premium_pct,
            source_time=_from_epoch(row.get("f124")),
            fetched_at=fetched_at,
        )


def _market_id_for(code: str) -> int:
    return 1 if code.startswith(("5", "6")) else 0


def _int(value: Any) -> int | None:
    try:
        return int(value)
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
