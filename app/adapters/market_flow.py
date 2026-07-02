from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

EASTMONEY_UT = "bd1d9ddb04089700cf9c27f6f7426281"
MARKET_FLOW_ENDPOINTS = (
    "https://push2delay.eastmoney.com/api/qt/clist/get",
    "https://push2.eastmoney.com/api/qt/clist/get",
)
BOARD_FIELDS = (
    "f12,f13,f14,f2,f3,f4,f5,f6,f7,f8,f10,f20,f21,f62,"
    "f104,f105,f128,f136,f140,f141,f124"
)
STOCK_FIELDS = (
    "f12,f13,f14,f2,f3,f4,f5,f6,f7,f8,f10,f15,f16,f17,f18,"
    "f21,f62,f124,f184"
)
BOARD_SOURCES: tuple[tuple[str, str], ...] = (
    ("industry", "m:90+t:2"),
    ("concept", "m:90+t:3"),
)


class EastmoneyMarketFlowClient:
    def __init__(self, timeout_seconds: float = 15.0) -> None:
        self.timeout_seconds = timeout_seconds
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
            ),
            "Referer": "https://quote.eastmoney.com/center/boardlist.html",
            "Accept": "application/json,text/plain,*/*",
            "Connection": "close",
        }

    async def close(self) -> None:
        return None

    async def fetch_boards(self, page_size: int = 100) -> list[dict[str, Any]]:
        rows_by_code: dict[str, dict[str, Any]] = {}
        for board_type, fs in BOARD_SOURCES:
            for fid in ("f3", "f62", "f6"):
                payload = await self._fetch_page(fs=fs, fid=fid, page=1, page_size=page_size, fields=BOARD_FIELDS)
                for row in ((payload.get("data") or {}).get("diff") or []):
                    code = str(row.get("f12") or "")
                    if not code:
                        continue
                    item = dict(row)
                    item["_board_type"] = board_type
                    rows_by_code[code] = item
                await asyncio.sleep(0.08)
        return list(rows_by_code.values())

    async def fetch_board_members(self, board_code: str, page_size: int = 30) -> list[dict[str, Any]]:
        payload = await self._fetch_page(
            fs=f"b:{board_code}",
            fid="f3",
            page=1,
            page_size=page_size,
            fields=STOCK_FIELDS,
        )
        return list(((payload.get("data") or {}).get("diff") or []))

    async def _fetch_page(self, *, fs: str, fid: str, page: int, page_size: int, fields: str) -> dict[str, Any]:
        params = {
            "pn": str(page),
            "pz": str(page_size),
            "po": "1",
            "np": "1",
            "ut": EASTMONEY_UT,
            "fltt": "2",
            "invt": "2",
            "fid": fid,
            "fs": fs,
            "fields": fields,
        }
        last_exc: Exception | None = None
        for attempt in range(4):
            for endpoint in MARKET_FLOW_ENDPOINTS:
                try:
                    return await asyncio.to_thread(self._fetch_page_sync, endpoint, params)
                except Exception as exc:
                    last_exc = exc
            await asyncio.sleep(0.35 * (attempt + 1))
        raise RuntimeError(f"Eastmoney market-flow request failed: {last_exc}") from last_exc

    def _fetch_page_sync(self, endpoint: str, params: dict[str, str]) -> dict[str, Any]:
        request = Request(endpoint + "?" + urlencode(params), headers=self.headers)
        with urlopen(request, timeout=self.timeout_seconds) as response:
            raw = response.read()
        return json.loads(raw.decode("utf-8"))


def num(value: Any) -> float | None:
    if value in (None, "-", ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def integer(value: Any) -> int | None:
    if value in (None, "-", ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def from_epoch(value: Any) -> datetime | None:
    try:
        raw = int(value)
    except (TypeError, ValueError):
        return None
    if raw <= 0:
        return None
    return datetime.fromtimestamp(raw, tz=timezone.utc)
