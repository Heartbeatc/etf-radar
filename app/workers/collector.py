from __future__ import annotations

import asyncio
import logging
import signal
from contextlib import suppress

from app.adapters.clickhouse import ClickHouseWriter
from app.adapters.market_data import MarketDataClient
from app.adapters.event_bus import KafkaEventBus
from app.adapters.store import Store
from app.core.config import get_settings
from app.services.pipeline import TOPIC_SUFFIXES, model_payload, monitor_codes, roles_for, source_status_for

LOGGER = logging.getLogger("etf.collector")


class CollectorWorker:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.settings.ensure_data_dir()
        self.store = Store(self.settings.database_path)
        self.client = MarketDataClient(self.settings)
        self.event_bus = KafkaEventBus(self.settings)
        self.clickhouse = ClickHouseWriter(self.settings)
        self._stop = asyncio.Event()

    async def start(self) -> None:
        self.event_bus.ensure_topics(TOPIC_SUFFIXES)
        await self.clickhouse.ensure_schema()
        tick = 0
        while not self._stop.is_set():
            tick += 1
            refresh_history = tick % self.settings.history_refresh_every_ticks == 0
            if tick == 1 and self.settings.collector_refresh_history_on_start:
                refresh_history = True
            started = asyncio.get_running_loop().time()
            try:
                counts = await self.poll_once(refresh_history=refresh_history)
                LOGGER.info("collector poll ok snapshots=%s statuses=%s refresh_history=%s", counts[0], counts[1], refresh_history)
            except Exception:
                LOGGER.exception("collector poll failed")
            elapsed = asyncio.get_running_loop().time() - started
            delay = max(1.0, self.settings.poll_interval_seconds - elapsed)
            with suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=delay)

    async def stop(self) -> None:
        self._stop.set()
        self.event_bus.close()
        await self.clickhouse.close()
        await self.client.close()

    async def poll_once(self, refresh_history: bool = False) -> tuple[int, int]:
        codes = monitor_codes(self.settings, self.store)
        roles = roles_for(self.settings, self.store.positions().keys())
        snapshots = await self.client.fetch_spot(codes, roles)
        self.store.save_snapshots(snapshots)
        self.event_bus.publish_many("market.normalized.snapshot", [model_payload(item) for item in snapshots])
        await self.clickhouse.insert_snapshots(snapshots)

        statuses = source_status_for(self.settings, self.store.latest_snapshots(), codes=codes, roles=roles)
        self.store.save_source_status(statuses)
        self.event_bus.publish_many("source.status", [model_payload(item) for item in statuses])
        await self.clickhouse.insert_source_status(statuses)

        if refresh_history:
            for code in codes:
                try:
                    daily, minute = await asyncio.gather(self.client.fetch_daily(code), self.client.fetch_minute(code))
                except Exception as exc:
                    LOGGER.warning("history refresh failed code=%s error=%s", code, exc)
                    continue
                self.store.save_daily_bars(code, daily)
                self.store.save_minute_bars(code, minute)
        return len(snapshots), len(statuses)


async def _main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    worker = CollectorWorker()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, lambda: asyncio.create_task(worker.stop()))
    try:
        await worker.start()
    finally:
        await worker.stop()


if __name__ == "__main__":
    asyncio.run(_main())
