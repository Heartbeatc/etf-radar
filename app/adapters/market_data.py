from __future__ import annotations

import logging

from app.adapters.eastmoney import EastmoneyClient
from app.adapters.tencent import TencentQuoteClient
from app.core.config import Settings
from app.domain.models import DailyBar, EtfSnapshot, MinuteBar

LOGGER = logging.getLogger("etf.market_data")


class MarketDataClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.primary = EastmoneyClient()
        self.free_fallback = TencentQuoteClient()
        self.last_spot_source: str | None = None
        self.last_primary_error: str | None = None
        self.last_fallback_error: str | None = None

    async def close(self) -> None:
        await self.primary.close()
        await self.free_fallback.close()

    async def fetch_spot(self, codes: list[str], roles: dict[str, str]) -> list[EtfSnapshot]:
        try:
            snapshots = await self.primary.fetch_spot(codes, roles)
            self.last_spot_source = "eastmoney"
            self.last_primary_error = None
            return snapshots
        except Exception as exc:
            self.last_primary_error = str(exc)[:500]
            if not self.settings.free_quote_fallback_enabled:
                raise
            LOGGER.warning("primary quote source eastmoney failed; trying tencent fallback: %s", exc)
        try:
            snapshots = await self.free_fallback.fetch_spot(codes, roles)
            self.last_spot_source = "tencent"
            self.last_fallback_error = None
            return snapshots
        except Exception as exc:
            self.last_fallback_error = str(exc)[:500]
            raise RuntimeError(
                "all spot quote sources failed: "
                f"eastmoney={self.last_primary_error}; tencent={self.last_fallback_error}"
            ) from exc

    async def fetch_daily(self, code: str, limit_days: int = 140) -> list[DailyBar]:
        return await self.primary.fetch_daily(code, limit_days=limit_days)

    async def fetch_minute(self, code: str) -> list[MinuteBar]:
        return await self.primary.fetch_minute(code)
