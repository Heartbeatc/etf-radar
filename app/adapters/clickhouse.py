from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

import httpx

from app.core.config import Settings
from app.domain.models import EtfSnapshot, SourceStatus, TradePlan

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class ClickHouseWriter:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.enabled = settings.clickhouse_enabled
        self.last_error: str | None = None
        self._client = httpx.AsyncClient(
            base_url=settings.clickhouse_url.rstrip("/"),
            timeout=settings.clickhouse_timeout_seconds,
            auth=(settings.clickhouse_user, settings.clickhouse_password) if settings.clickhouse_user else None,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def ensure_schema(self) -> None:
        if not self.enabled:
            return
        db = _ident(self.settings.clickhouse_database)
        statements = [
            f"CREATE DATABASE IF NOT EXISTS {db}",
            f"""
            CREATE TABLE IF NOT EXISTS {db}.etf_snapshots (
                fetched_at DateTime64(3, 'UTC'),
                source_time Nullable(DateTime64(3, 'UTC')),
                code LowCardinality(String),
                name String,
                role LowCardinality(String),
                price Nullable(Float64),
                change_pct Nullable(Float64),
                volume Nullable(Float64),
                amount Nullable(Float64),
                main_net_inflow Nullable(Float64),
                main_net_inflow_pct Nullable(Float64),
                iopv Nullable(Float64),
                premium_pct Nullable(Float64),
                payload String
            ) ENGINE = MergeTree
            PARTITION BY toYYYYMM(fetched_at)
            ORDER BY (code, fetched_at)
            """,
            f"""
            CREATE TABLE IF NOT EXISTS {db}.signal_history (
                signal_at DateTime64(3, 'UTC'),
                code LowCardinality(String),
                name String,
                role LowCardinality(String),
                signal LowCardinality(String),
                confidence LowCardinality(String),
                direction_score UInt8,
                low_buy_score UInt8,
                hold_score UInt8,
                take_profit_score UInt8,
                risk_score UInt8,
                current_price Nullable(Float64),
                data_state LowCardinality(String),
                payload String
            ) ENGINE = MergeTree
            PARTITION BY toYYYYMM(signal_at)
            ORDER BY (code, signal_at)
            """,
            f"""
            CREATE TABLE IF NOT EXISTS {db}.source_status (
                checked_at DateTime64(3, 'UTC'),
                code LowCardinality(String),
                role LowCardinality(String),
                ok UInt8,
                issues Array(String),
                price Nullable(Float64),
                iopv Nullable(Float64),
                premium_pct Nullable(Float64),
                payload String
            ) ENGINE = MergeTree
            PARTITION BY toYYYYMM(checked_at)
            ORDER BY (code, checked_at)
            """,
        ]
        for statement in statements:
            await self._query(statement)

    async def insert_snapshots(self, snapshots: list[EtfSnapshot]) -> int:
        if not self.enabled or not snapshots:
            return 0
        rows = [
            {
                "fetched_at": _dt(item.fetched_at),
                "source_time": _dt(item.source_time),
                "code": item.code,
                "name": item.name,
                "role": item.role,
                "price": item.price,
                "change_pct": item.change_pct,
                "volume": item.volume,
                "amount": item.amount,
                "main_net_inflow": item.main_net_inflow,
                "main_net_inflow_pct": item.main_net_inflow_pct,
                "iopv": item.iopv,
                "premium_pct": item.premium_pct,
                "payload": item.model_dump_json(),
            }
            for item in snapshots
        ]
        await self._insert("etf_snapshots", rows)
        return len(rows)

    async def insert_signals(self, plans: list[TradePlan]) -> int:
        if not self.enabled or not plans:
            return 0
        signal_at = datetime.now(timezone.utc)
        rows = [
            {
                "signal_at": _dt(signal_at),
                "code": plan.code,
                "name": plan.name,
                "role": plan.role,
                "signal": plan.signal,
                "confidence": plan.confidence,
                "direction_score": plan.direction_score,
                "low_buy_score": plan.low_buy_score,
                "hold_score": plan.hold_score,
                "take_profit_score": plan.take_profit_score,
                "risk_score": plan.risk_score,
                "current_price": plan.current_price,
                "data_state": plan.data_state,
                "payload": plan.model_dump_json(),
            }
            for plan in plans
        ]
        await self._insert("signal_history", rows)
        return len(rows)

    async def insert_source_status(self, statuses: list[SourceStatus]) -> int:
        if not self.enabled or not statuses:
            return 0
        checked_at = datetime.now(timezone.utc)
        rows = [
            {
                "checked_at": _dt(checked_at),
                "code": item.code,
                "role": item.role,
                "ok": 1 if item.ok else 0,
                "issues": item.issues,
                "price": item.price,
                "iopv": item.iopv,
                "premium_pct": item.premium_pct,
                "payload": item.model_dump_json(),
            }
            for item in statuses
        ]
        await self._insert("source_status", rows)
        return len(rows)

    async def health(self) -> tuple[bool, str | None]:
        if not self.enabled:
            return False, "disabled"
        try:
            await self._query("SELECT 1")
            return True, self.last_error
        except Exception as exc:
            self.last_error = str(exc)[:300]
            return False, self.last_error

    async def _insert(self, table: str, rows: list[dict[str, Any]]) -> None:
        db = _ident(self.settings.clickhouse_database)
        table_name = _ident(table)
        body = "\n".join(json.dumps(row, ensure_ascii=False, default=str) for row in rows)
        await self._query(f"INSERT INTO {db}.{table_name} FORMAT JSONEachRow", body=body)

    async def _query(self, query: str, body: str | None = None) -> str:
        if not self.enabled:
            return ""
        try:
            response = await self._client.post("/", params={"query": query}, content=body)
            response.raise_for_status()
            self.last_error = None
            return response.text
        except Exception as exc:
            self.last_error = str(exc)[:300]
            raise


def _ident(value: str) -> str:
    if not _IDENTIFIER.match(value):
        raise ValueError(f"invalid ClickHouse identifier: {value}")
    return value


def _dt(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    value = value.astimezone(timezone.utc)
    return value.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
