from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import datetime, timezone

from fastapi import HTTPException

from app.adapters.clickhouse import ClickHouseWriter
from app.adapters.market_data import MarketDataClient
from app.adapters.market_flow import EastmoneyMarketFlowClient
from app.adapters.event_bus import KafkaEventBus
from app.adapters.etf_universe import EastmoneyEtfUniverseClient
from app.adapters.infra import PostgresInfra, RedisInfra
from app.adapters.store import Store
from app.core.config import Settings
from app.core.market import market_status
from app.domain.models import AiStatus, AiSummaryItem, AiSummaryReport, DiscoveryResponse, IntegrationStatus, LatestResponse, MarketFlowResponse, Position, SourceStatus, TradePlan
from app.services.ai import AIAnalyst
from app.services.ai_summary import build_ai_context, due_summary_kinds, make_summary_item, summary_title, summary_windows_payload, trading_date
from app.services.alerts import AlertManager
from app.services.discovery import build_discovery_report
from app.services.market_flow import build_market_flow_report
from app.services.pipeline import TOPIC_SUFFIXES, build_rule_plans, model_payload, monitor_codes, roles_for, source_status_for, trade_codes
from app.services.scoring import AnalysisInputs, build_plan


class Runtime:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        settings.ensure_data_dir()
        self.store = Store(settings.database_path)
        self.client = MarketDataClient(settings)
        self.universe_client = EastmoneyEtfUniverseClient()
        self.market_flow_client = EastmoneyMarketFlowClient()
        self.ai = AIAnalyst(settings)
        self.alerts = AlertManager(settings, self.store)
        self.event_bus = KafkaEventBus(settings)
        self.clickhouse = ClickHouseWriter(settings)
        self.postgres = PostgresInfra(settings)
        self.redis = RedisInfra(settings)
        self._task: asyncio.Task | None = None
        self._ai_task: asyncio.Task | None = None
        self._last_error: str | None = None
        self._last_warning: str | None = None
        self._integration_errors: dict[str, str | None] = {"kafka": None, "clickhouse": None, "postgres": None, "redis": None}
        self._discovery_cache: tuple[datetime, DiscoveryResponse] | None = None
        self._market_flow_cache: tuple[datetime, MarketFlowResponse] | None = None

    async def start(self) -> None:
        await self._setup_integrations()
        self._ai_task = asyncio.create_task(self._ai_summary_loop())
        if not self.settings.api_polling_enabled:
            self._last_warning = None
            return
        try:
            await self.poll_once(refresh_history=False)
            self._last_error = None
        except Exception as exc:
            self._last_error = str(exc)
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._ai_task:
            self._ai_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._ai_task
        self.event_bus.close()
        await self.clickhouse.close()
        await self.redis.close()
        await self.universe_client.close()
        await self.market_flow_client.close()
        await self.client.close()

    async def _setup_integrations(self) -> None:
        try:
            self.event_bus.ensure_topics(TOPIC_SUFFIXES)
            self._integration_errors["kafka"] = self.event_bus.last_error
        except Exception as exc:
            self._integration_errors["kafka"] = str(exc)[:300]
        try:
            await self.clickhouse.ensure_schema()
            self._integration_errors["clickhouse"] = self.clickhouse.last_error
        except Exception as exc:
            self._integration_errors["clickhouse"] = str(exc)[:300]
        try:
            await self.postgres.ensure_schema()
            self._integration_errors["postgres"] = self.postgres.last_error
        except Exception as exc:
            self._integration_errors["postgres"] = str(exc)[:300]
        try:
            redis_ok, redis_error = await self.redis.health()
            self._integration_errors["redis"] = None if redis_ok else redis_error
        except Exception as exc:
            self._integration_errors["redis"] = str(exc)[:300]

    async def _ai_summary_loop(self) -> None:
        while True:
            try:
                await self.generate_due_ai_summaries()
            except Exception:
                pass
            await asyncio.sleep(self.settings.ai_summary_check_interval_seconds)

    async def _loop(self) -> None:
        tick = 1
        while True:
            try:
                refresh = tick % self.settings.history_refresh_every_ticks == 0
                await self.poll_once(refresh_history=refresh)
                self._last_error = None
            except Exception as exc:
                self._last_error = str(exc)
            tick += 1
            await asyncio.sleep(self.settings.poll_interval_seconds)

    async def poll_once(self, refresh_history: bool = False) -> None:
        codes = self.monitor_codes()
        roles = self.roles()
        previous_signals = self.store.previous_signals(self.trade_codes())
        snapshots = await self.client.fetch_spot(codes, roles)
        self.store.save_snapshots(snapshots)
        await self._publish_snapshots(snapshots)
        await self._write_snapshots(snapshots)

        statuses = self.source_status()
        self.store.save_source_status(statuses)
        await self._publish_source_status(statuses)
        await self._write_source_status(statuses)

        history_errors: list[str] = []
        if refresh_history:
            for code in codes:
                try:
                    daily, minute = await asyncio.gather(self.client.fetch_daily(code), self.client.fetch_minute(code))
                except Exception as exc:
                    history_errors.append(f"{code}: {exc}")
                    continue
                self.store.save_daily_bars(code, daily)
                self.store.save_minute_bars(code, minute)
        self._last_warning = "; ".join(history_errors[:3]) if history_errors else None

        plans = self.build_rule_plans()
        if plans:
            self.store.save_signal_history(plans)
            await self._publish_signals(plans)
            await self._write_signals(plans)
            await self.alerts.process(plans, previous_signals)

    async def discovery(self, force: bool = False, min_amount: float | None = None) -> DiscoveryResponse:
        now = datetime.now(timezone.utc)
        if not force and min_amount is None and self._discovery_cache is not None:
            cached_at, cached = self._discovery_cache
            if (now - cached_at).total_seconds() <= self.settings.discovery_cache_seconds:
                return cached
        snapshots = await self.universe_client.fetch_universe()
        report = build_discovery_report(
            self.settings,
            snapshots,
            min_amount=min_amount,
            max_directions=self.settings.discovery_max_directions,
        )
        if min_amount is None:
            self._discovery_cache = (now, report)
        return report

    async def market_flow(self, force: bool = False) -> MarketFlowResponse:
        now = datetime.now(timezone.utc)
        if not force and self._market_flow_cache is not None:
            cached_at, cached = self._market_flow_cache
            if (now - cached_at).total_seconds() <= self.settings.discovery_cache_seconds:
                return cached
        etf_report: DiscoveryResponse | None = None
        try:
            etf_report = await self.discovery(force=force)
        except Exception:
            etf_report = None
        report = await build_market_flow_report(
            self.market_flow_client,
            etf_report=etf_report,
            max_directions=self.settings.discovery_max_directions,
        )
        self._market_flow_cache = (now, report)
        return report

    async def latest(self) -> LatestResponse:
        plans = self.build_rule_plans()
        snapshots = self.store.latest_snapshots()
        benchmarks = [snapshots[code] for code in self.settings.benchmark_code_list if code in snapshots]
        ages = [(datetime.now(timezone.utc) - item.fetched_at).total_seconds() for item in snapshots.values()]
        fixed_snapshots = [snapshots.get(plan.code) for plan in plans]
        fixed_times = [item.source_time for item in fixed_snapshots if item and item.source_time]
        return LatestResponse(
            generated_at=datetime.now(timezone.utc),
            data_time=max(fixed_times) if fixed_times else None,
            poll_interval_seconds=self.settings.poll_interval_seconds,
            market_status=market_status(),
            data_age_seconds=round(min(ages), 2) if ages else None,
            top_low_buy=_top(plans, "low_buy_score"),
            top_hold=_top(plans, "hold_score"),
            top_take_profit_risk=_top(plans, "take_profit_score"),
            plans=plans,
            benchmarks=benchmarks,
        )

    async def plans(self) -> list[TradePlan]:
        return self.build_rule_plans()

    def build_rule_plans(self) -> list[TradePlan]:
        return build_rule_plans(self.settings, self.store)

    def monitor_codes(self) -> list[str]:
        return monitor_codes(self.settings, self.store)

    def trade_codes(self) -> list[str]:
        return trade_codes(self.settings, self.store)

    def detail(self, code: str, entry_price: float | None = None) -> TradePlan:
        latest = self.store.latest_snapshots()
        if code not in latest:
            raise HTTPException(status_code=404, detail=f"No data for ETF {code}")
        position = self.store.positions().get(code)
        if entry_price:
            position = Position(
                code=code,
                entry_price=entry_price,
                shares=None,
                note="query override",
                updated_at=datetime.now(timezone.utc),
            )
        return build_plan(
            AnalysisInputs(
                snapshot=latest[code],
                daily=self.store.get_daily_bars(code),
                minute=self.store.get_minute_bars(code),
                position=position,
                stale_seconds=self.settings.data_stale_seconds,
            )
        )

    def ai_enabled(self) -> bool:
        return self.store.get_bool_setting("ai_enabled", self.settings.ai_enabled)

    def set_ai_enabled(self, enabled: bool) -> AiStatus:
        self.store.set_bool_setting("ai_enabled", enabled)
        return self.ai_status()

    def ai_status(self) -> AiStatus:
        date = trading_date()
        return AiStatus(
            enabled=self.ai_enabled(),
            configured=bool(self.settings.deepseek_api_key),
            model=self.settings.deepseek_model,
            daily_call_limit=self.settings.ai_summary_daily_call_limit,
            calls_used_today=self.store.ai_call_count(date),
            force_cooldown_seconds=self.settings.ai_summary_force_cooldown_seconds,
            check_interval_seconds=self.settings.ai_summary_check_interval_seconds,
            windows=summary_windows_payload(),
        )

    def ai_summary_report(self, limit: int = 10) -> AiSummaryReport:
        warnings: list[str] = []
        if not self.ai_enabled():
            warnings.append("AI summaries are disabled")
        if not self.settings.deepseek_api_key:
            warnings.append("DeepSeek API key is not configured")
        return AiSummaryReport(
            generated_at=datetime.now(timezone.utc),
            status=self.ai_status(),
            summaries=self.store.latest_ai_summaries(limit=limit),
            warnings=warnings,
        )

    async def generate_due_ai_summaries(self) -> list[AiSummaryItem]:
        if not self.ai_enabled() or not self.settings.deepseek_api_key:
            return []
        result: list[AiSummaryItem] = []
        for kind in due_summary_kinds():
            item = await self.generate_ai_summary(kind=kind, force=False)
            if item is not None:
                result.append(item)
        return result

    async def generate_ai_summary(self, kind: str, force: bool = False) -> AiSummaryItem | None:
        if kind not in {"opening_auction", "midday", "closing"}:
            raise HTTPException(status_code=400, detail=f"Unsupported AI summary kind: {kind}")
        date = trading_date()
        existing = self.store.ai_summary_for(kind, date)
        if existing and not force:
            return existing
        if not self.ai_enabled():
            return existing
        if not self.settings.deepseek_api_key:
            return existing
        if force and existing:
            age = (datetime.now(timezone.utc) - existing.generated_at).total_seconds()
            if age < self.settings.ai_summary_force_cooldown_seconds:
                return existing
        if self.store.ai_call_count(date) >= self.settings.ai_summary_daily_call_limit:
            return existing

        plans = self.build_rule_plans()
        snapshots = self.store.latest_snapshots()
        market_flow: MarketFlowResponse | None = None
        try:
            market_flow = await self.market_flow(force=False)
        except Exception:
            market_flow = None
        context, source_data_time = build_ai_context(self.settings, plans, market_flow, snapshots)
        try:
            summary_text = await self.ai.summarize_market(kind, context)
            item = make_summary_item(
                kind=kind,
                trading_date_value=date,
                model=self.settings.deepseek_model,
                summary=summary_text,
                source_data_time=source_data_time,
                payload={"context": context},
            )
            self.store.log_ai_call("market_summary", kind, date, "ok")
            return self.store.save_ai_summary(item)
        except Exception as exc:
            error = str(exc)[:300]
            self.store.log_ai_call("market_summary", kind, date, "error", error=error)
            item = make_summary_item(
                kind=kind,
                trading_date_value=date,
                model=self.settings.deepseek_model,
                summary=f"{summary_title(kind)}生成失败，继续以规则引擎信号为准。",
                source_data_time=source_data_time,
                status="error",
                error=error,
                payload={"context": context},
            )
            return self.store.save_ai_summary(item)

    def source_status(self) -> list[SourceStatus]:
        return source_status_for(self.settings, self.store.latest_snapshots(), codes=self.monitor_codes(), roles=self.roles())

    async def integrations_status(self) -> list[IntegrationStatus]:
        kafka_ok, kafka_detail = self.event_bus.health()
        ch_ok, ch_detail = await self.clickhouse.health()
        pg_ok, pg_detail = await self.postgres.health()
        redis_ok, redis_detail = await self.redis.health()
        return [
            IntegrationStatus(
                name="kafka",
                enabled=self.settings.kafka_enabled,
                ok=kafka_ok,
                detail=(
                    f"bootstrap={self.settings.kafka_bootstrap_servers}; prefix={self.settings.kafka_topic_prefix}"
                    if self.settings.kafka_enabled
                    else "disabled"
                ),
                last_error=self._integration_errors.get("kafka") or kafka_detail or self.event_bus.last_error,
            ),
            IntegrationStatus(
                name="clickhouse",
                enabled=self.settings.clickhouse_enabled,
                ok=ch_ok,
                detail=(
                    f"url={self.settings.clickhouse_url}; database={self.settings.clickhouse_database}"
                    if self.settings.clickhouse_enabled
                    else "disabled"
                ),
                last_error=self._integration_errors.get("clickhouse") or ch_detail or self.clickhouse.last_error,
            ),
            IntegrationStatus(
                name="postgres",
                enabled=self.settings.postgres_enabled,
                ok=pg_ok,
                detail=(
                    f"host={self.settings.postgres_host}:{self.settings.postgres_port}; database={self.settings.postgres_db}"
                    if self.settings.postgres_enabled
                    else "disabled"
                ),
                last_error=self._integration_errors.get("postgres") or pg_detail or self.postgres.last_error,
            ),
            IntegrationStatus(
                name="redis",
                enabled=self.settings.redis_enabled,
                ok=redis_ok,
                detail=self.settings.redis_url if self.settings.redis_enabled else "disabled",
                last_error=self._integration_errors.get("redis") or redis_detail or self.redis.last_error,
            ),
        ]

    async def ensure_daily_bars(self, code: str) -> list:
        daily = self.store.get_daily_bars(code)
        if len(daily) >= 40:
            return daily
        daily = await self.client.fetch_daily(code)
        self.store.save_daily_bars(code, daily)
        return daily

    async def refresh_history(self) -> dict:
        errors: list[str] = []
        updated: list[str] = []
        for code in self.monitor_codes():
            try:
                daily, minute = await asyncio.gather(self.client.fetch_daily(code), self.client.fetch_minute(code))
                self.store.save_daily_bars(code, daily)
                self.store.save_minute_bars(code, minute)
                updated.append(code)
            except Exception as exc:
                errors.append(f"{code}: {exc}")
        return {"updated": updated, "errors": errors}

    def roles(self) -> dict[str, str]:
        return roles_for(self.settings, self.store.positions().keys())

    async def _publish_snapshots(self, snapshots) -> None:
        try:
            self.event_bus.publish_many("market.normalized.snapshot", [model_payload(item) for item in snapshots])
            self._integration_errors["kafka"] = self.event_bus.last_error
        except Exception as exc:
            self._integration_errors["kafka"] = str(exc)[:300]

    async def _publish_signals(self, plans: list[TradePlan]) -> None:
        try:
            self.event_bus.publish_many("signal.generated", [model_payload(plan) for plan in plans])
            self._integration_errors["kafka"] = self.event_bus.last_error
        except Exception as exc:
            self._integration_errors["kafka"] = str(exc)[:300]

    async def _publish_source_status(self, statuses: list[SourceStatus]) -> None:
        try:
            self.event_bus.publish_many("source.status", [model_payload(status) for status in statuses])
            self._integration_errors["kafka"] = self.event_bus.last_error
        except Exception as exc:
            self._integration_errors["kafka"] = str(exc)[:300]

    async def _write_snapshots(self, snapshots) -> None:
        try:
            await self.clickhouse.insert_snapshots(snapshots)
            self._integration_errors["clickhouse"] = self.clickhouse.last_error
        except Exception as exc:
            self._integration_errors["clickhouse"] = str(exc)[:300]

    async def _write_signals(self, plans: list[TradePlan]) -> None:
        try:
            await self.clickhouse.insert_signals(plans)
            self._integration_errors["clickhouse"] = self.clickhouse.last_error
        except Exception as exc:
            self._integration_errors["clickhouse"] = str(exc)[:300]

    async def _write_source_status(self, statuses: list[SourceStatus]) -> None:
        try:
            await self.clickhouse.insert_source_status(statuses)
            self._integration_errors["clickhouse"] = self.clickhouse.last_error
        except Exception as exc:
            self._integration_errors["clickhouse"] = str(exc)[:300]


def _top(plans: list[TradePlan], field: str) -> str | None:
    if not plans:
        return None
    return max(plans, key=lambda plan: getattr(plan, field)).code
