from __future__ import annotations

import asyncio
import logging
import signal
from contextlib import suppress

from app.adapters.clickhouse import ClickHouseWriter
from app.adapters.event_bus import KafkaEventBus, KafkaJsonConsumer
from app.adapters.store import Store
from app.core.config import get_settings
from app.domain.models import EtfSnapshot
from app.services.alerts import AlertManager
from app.services.pipeline import TOPIC_SUFFIXES, build_rule_plan_for_code, model_payload

LOGGER = logging.getLogger("etf.signal_worker")


class SignalWorker:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.settings.ensure_data_dir()
        self.store = Store(self.settings.database_path)
        self.event_bus = KafkaEventBus(self.settings)
        self.clickhouse = ClickHouseWriter(self.settings)
        self.alerts = AlertManager(self.settings, self.store)
        self.consumer = KafkaJsonConsumer(
            self.settings,
            topic_suffix="market.normalized.snapshot",
            group_id=self.settings.signal_consumer_group,
        )
        self._stop = asyncio.Event()

    async def start(self) -> None:
        self.event_bus.ensure_topics(TOPIC_SUFFIXES)
        await self.clickhouse.ensure_schema()
        if not self.settings.kafka_enabled:
            raise RuntimeError("Kafka is disabled; signal-worker requires Kafka")
        LOGGER.info("signal-worker subscribed topic=%s group=%s", self.consumer.topic, self.settings.signal_consumer_group)
        while not self._stop.is_set():
            envelope = await asyncio.to_thread(self.consumer.poll, 1.0)
            if envelope is None:
                await asyncio.sleep(0)
                continue
            await self.handle_snapshot_event(envelope)

    async def stop(self) -> None:
        self._stop.set()
        self.consumer.close()
        self.event_bus.close()
        await self.clickhouse.close()

    async def handle_snapshot_event(self, envelope: dict) -> None:
        payload = envelope.get("payload") if isinstance(envelope, dict) else None
        if not isinstance(payload, dict):
            return
        try:
            snapshot = EtfSnapshot.model_validate(payload)
        except Exception:
            LOGGER.exception("invalid snapshot payload")
            return
        self.store.save_latest_snapshots([snapshot])
        if snapshot.code not in self.settings.exposed_codes:
            return
        previous = self.store.previous_signals([snapshot.code])
        plan = build_rule_plan_for_code(self.settings, self.store, snapshot.code)
        if plan is None:
            return
        self.store.save_signal_history([plan])
        self.event_bus.publish_many("signal.generated", [model_payload(plan)])
        await self.clickhouse.insert_signals([plan])
        await self.alerts.process([plan], previous)
        LOGGER.info(
            "signal generated code=%s signal=%s direction=%s low_buy=%s hold=%s take_profit=%s",
            plan.code,
            plan.signal,
            plan.direction_score,
            plan.low_buy_score,
            plan.hold_score,
            plan.take_profit_score,
        )


async def _main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    worker = SignalWorker()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, lambda: asyncio.create_task(worker.stop()))
    try:
        await worker.start()
    finally:
        with suppress(Exception):
            await worker.stop()


if __name__ == "__main__":
    asyncio.run(_main())
