from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app.core.config import Settings

try:
    from confluent_kafka import Consumer, Producer
    from confluent_kafka.admin import AdminClient, NewTopic
except Exception:  # pragma: no cover - optional dependency guard
    Consumer = None
    Producer = None
    AdminClient = None
    NewTopic = None


class KafkaEventBus:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.enabled = settings.kafka_enabled
        self.last_error: str | None = None
        self._producer = None
        if self.enabled and Producer is not None:
            self._producer = Producer({"bootstrap.servers": settings.kafka_bootstrap_servers})
        elif self.enabled:
            self.last_error = "confluent-kafka is not installed"

    def topic(self, suffix: str) -> str:
        return f"{self.settings.kafka_topic_prefix}.{suffix}"

    def ensure_topics(self, suffixes: list[str]) -> None:
        if not self.enabled or AdminClient is None or NewTopic is None:
            return
        try:
            client = AdminClient({"bootstrap.servers": self.settings.kafka_bootstrap_servers})
            topics = [NewTopic(self.topic(suffix), num_partitions=3, replication_factor=1) for suffix in suffixes]
            futures = client.create_topics(topics, request_timeout=5)
            for future in futures.values():
                try:
                    future.result(timeout=5)
                except Exception as exc:
                    message = str(exc).lower()
                    if "already exists" not in message and "topic_already_exists" not in message:
                        self.last_error = str(exc)[:300]
        except Exception as exc:
            self.last_error = str(exc)[:300]

    def publish_many(self, suffix: str, events: list[dict[str, Any]], key_field: str = "code") -> int:
        if not self.enabled or self._producer is None or not events:
            return 0
        topic = self.topic(suffix)
        published = 0
        try:
            for event in events:
                envelope = {
                    "event_at": datetime.now(timezone.utc).isoformat(),
                    "event_type": suffix,
                    "payload": event,
                }
                key = str(event.get(key_field, ""))
                self._producer.produce(
                    topic,
                    key=key.encode("utf-8") if key else None,
                    value=json.dumps(envelope, ensure_ascii=False, default=str).encode("utf-8"),
                    on_delivery=self._delivery_report,
                )
                published += 1
            self._producer.poll(0)
            self._producer.flush(self.settings.kafka_flush_timeout_seconds)
            return published
        except Exception as exc:
            self.last_error = str(exc)[:300]
            return published

    def health(self) -> tuple[bool, str | None]:
        if not self.enabled:
            return False, "disabled"
        if self._producer is None:
            return False, self.last_error or "producer not initialized"
        try:
            metadata = self._producer.list_topics(timeout=2)
            return bool(metadata.brokers), self.last_error
        except Exception as exc:
            self.last_error = str(exc)[:300]
            return False, self.last_error

    def close(self) -> None:
        if self._producer is not None:
            self._producer.flush(2)

    def _delivery_report(self, error, _message) -> None:
        if error is not None:
            self.last_error = str(error)[:300]


class KafkaJsonConsumer:
    def __init__(self, settings: Settings, topic_suffix: str, group_id: str) -> None:
        self.settings = settings
        self.enabled = settings.kafka_enabled
        self.topic = f"{settings.kafka_topic_prefix}.{topic_suffix}"
        self.last_error: str | None = None
        self._consumer = None
        if self.enabled and Consumer is not None:
            self._consumer = Consumer(
                {
                    "bootstrap.servers": settings.kafka_bootstrap_servers,
                    "group.id": group_id,
                    "client.id": group_id,
                    "auto.offset.reset": "latest",
                    "enable.auto.commit": True,
                    "allow.auto.create.topics": False,
                }
            )
            self._consumer.subscribe([self.topic])
        elif self.enabled:
            self.last_error = "confluent-kafka is not installed"

    def poll(self, timeout: float = 1.0) -> dict[str, Any] | None:
        if not self.enabled or self._consumer is None:
            return None
        message = self._consumer.poll(timeout)
        if message is None:
            return None
        if message.error():
            self.last_error = str(message.error())[:300]
            return None
        try:
            value = message.value()
            if isinstance(value, bytes):
                value = value.decode("utf-8")
            return json.loads(value)
        except Exception as exc:
            self.last_error = str(exc)[:300]
            return None

    def close(self) -> None:
        if self._consumer is not None:
            self._consumer.close()
