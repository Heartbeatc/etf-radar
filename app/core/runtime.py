from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from datetime import datetime, timezone

from fastapi import HTTPException

from app.adapters.clickhouse import ClickHouseWriter
from app.adapters.event_sources import FreeEventSourceClient
from app.adapters.market_data import MarketDataClient
from app.adapters.market_flow import EastmoneyMarketFlowClient
from app.adapters.event_bus import KafkaEventBus
from app.adapters.etf_universe import EastmoneyEtfUniverseClient
from app.adapters.infra import PostgresInfra, RedisInfra
from app.adapters.store import Store
from app.core.config import Settings
from app.core.market import market_clock, market_status
from app.domain.models import AiStatus, AiSummaryItem, AiSummaryReport, AiTradeRiskReview, DiscoveryResponse, EventCorpusReport, IntegrationStatus, LatestResponse, MarketFlowResponse, PoolRecommendationResponse, Position, QuantDecisionResponse, SourceStatus, TradePlan
from app.services.ai import AIAnalyst
from app.services.ai_summary import build_ai_context, due_summary_kinds, make_summary_item, summary_title, summary_windows_payload, trading_date
from app.services.alerts import AlertManager
from app.services.discovery import build_discovery_report
from app.services.event_corpus import build_event_corpus_report
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
        self.event_source_client = FreeEventSourceClient(settings)
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
        self._event_corpus_cache: tuple[datetime, EventCorpusReport] | None = None

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
        await self.event_source_client.close()
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
        clock = market_clock(extra_closed_dates=self.settings.market_extra_closed_date_list)
        if not clock.should_poll_realtime:
            self._last_warning = clock.note
            statuses = self.source_status()
            self.store.save_source_status(statuses)
            return

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
        clock = market_clock(extra_closed_dates=self.settings.market_extra_closed_date_list)
        if not force and not clock.should_poll_realtime:
            if self._market_flow_cache is not None:
                return self._market_flow_cache[1]
            history = self.store.market_flow_history(limit=1)
            if history:
                self._market_flow_cache = (now, history[0])
                return history[0]
        etf_report: DiscoveryResponse | None = None
        event_report: EventCorpusReport | None = None
        if not self.settings.stock_focus_enabled:
            try:
                etf_report = await self.discovery(force=force)
            except Exception:
                etf_report = None
        if self.settings.event_corpus_enabled and self.settings.event_source_url_list:
            try:
                event_report = await self.event_corpus(force=force)
            except Exception:
                event_report = None
        report = await build_market_flow_report(
            self.market_flow_client,
            etf_report=etf_report,
            event_report=event_report,
            max_directions=self.settings.discovery_max_directions,
            history=self.store.market_flow_history(),
        )
        self.store.save_market_flow_report(report)
        self._market_flow_cache = (now, report)
        return report

    async def event_corpus(self, force: bool = False) -> EventCorpusReport:
        now = datetime.now(timezone.utc)
        if not force and self._event_corpus_cache is not None:
            cached_at, cached = self._event_corpus_cache
            if (now - cached_at).total_seconds() <= self.settings.event_corpus_cache_seconds:
                return cached
        fetched, warnings = await self.event_source_client.fetch()
        inserted = self.store.save_event_items(fetched) if fetched else 0
        recent = self.store.event_items(limit=self.settings.event_corpus_max_items)
        report = build_event_corpus_report(
            items=recent,
            fetched_count=len(fetched),
            stored_count=inserted,
            warnings=warnings,
        )
        self._event_corpus_cache = (now, report)
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

    async def build_rule_plans_for_pool(self, pool: PoolRecommendationResponse) -> list[TradePlan]:
        roles = {code: "main" for code in pool.recommended_main_codes}
        roles.update({code: "backup" for code in pool.recommended_backup_codes})
        codes = [*pool.recommended_main_codes, *pool.recommended_backup_codes, *self.store.positions().keys()]
        return await self.build_rule_plans_for_codes(codes, roles)

    async def build_rule_plans_for_codes(self, codes: list[str], roles: dict[str, str] | None = None) -> list[TradePlan]:
        code_list = _unique_codes(codes)
        if not code_list:
            return []
        role_map = {code: (roles or {}).get(code, "position") for code in code_list}
        await self._ensure_plan_data(code_list, role_map)
        latest = self.store.latest_snapshots()
        positions = self.store.positions()
        clock = market_clock(extra_closed_dates=self.settings.market_extra_closed_date_list)
        stale_seconds = self.settings.data_stale_seconds if clock.should_poll_realtime else self.settings.closed_market_stale_seconds
        plans: list[TradePlan] = []
        for code in code_list:
            snapshot = latest.get(code)
            if snapshot is None:
                continue
            role = role_map.get(code, snapshot.role)
            if code in positions:
                role = "position"
            plans.append(
                build_plan(
                    AnalysisInputs(
                        snapshot=snapshot.model_copy(update={"role": role}),
                        daily=self.store.get_daily_bars(code),
                        minute=self.store.get_minute_bars(code),
                        position=positions.get(code),
                        stale_seconds=stale_seconds,
                    )
                )
            )
        return plans

    async def _ensure_plan_data(self, codes: list[str], roles: dict[str, str]) -> None:
        latest = self.store.latest_snapshots()
        if not market_clock(extra_closed_dates=self.settings.market_extra_closed_date_list).should_poll_realtime:
            return
        now = datetime.now(timezone.utc)
        stale_codes = []
        for code in codes:
            snapshot = latest.get(code)
            if snapshot is None:
                stale_codes.append(code)
                continue
            age = (now - snapshot.fetched_at).total_seconds()
            if age > self.settings.data_stale_seconds:
                stale_codes.append(code)
        if stale_codes:
            snapshots = await self.client.fetch_spot(stale_codes, roles)
            self.store.save_snapshots(snapshots)
        for code in codes:
            if len(self.store.get_daily_bars(code)) < 20:
                with suppress(Exception):
                    self.store.save_daily_bars(code, await self.client.fetch_daily(code))
            if not self.store.get_minute_bars(code):
                with suppress(Exception):
                    self.store.save_minute_bars(code, await self.client.fetch_minute(code))

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
            calls_used_today=self.store.ai_call_count(date, purpose="market_summary"),
            force_cooldown_seconds=self.settings.ai_summary_force_cooldown_seconds,
            check_interval_seconds=self.settings.ai_summary_check_interval_seconds,
            trade_review_daily_call_limit=self.settings.ai_trade_review_daily_call_limit,
            trade_review_calls_used_today=self.store.ai_call_count(date, purpose="trade_risk_review"),
            trade_review_cooldown_seconds=self.settings.ai_trade_review_cooldown_seconds,
            trade_review_max_per_run=self.settings.ai_trade_review_max_per_run,
            direction_shift_daily_call_limit=self.settings.ai_direction_shift_daily_call_limit,
            direction_shift_calls_used_today=self.store.ai_call_count(date, purpose="direction_shift"),
            direction_shift_cooldown_seconds=self.settings.ai_direction_shift_cooldown_seconds,
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
        shift_item = await self.generate_direction_shift_summary()
        if shift_item is not None:
            result.append(shift_item)
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
        if self.store.ai_call_count(date, purpose="market_summary") >= self.settings.ai_summary_daily_call_limit:
            return existing

        plans = self.build_rule_plans()
        snapshots = self.store.latest_snapshots()
        market_flow: MarketFlowResponse | None = None
        try:
            market_flow = await self.market_flow(force=False)
        except Exception:
            market_flow = None
        context, source_data_time = build_ai_context(self.settings, plans, market_flow, snapshots, kind=kind)
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
            saved = self.store.save_ai_summary(item)
            self._remember_direction_state_from_context(context)
            return saved
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
            saved = self.store.save_ai_summary(item)
            self._remember_direction_state_from_context(context)
            return saved

    async def generate_direction_shift_summary(
        self,
        market_flow_report: MarketFlowResponse | None = None,
    ) -> AiSummaryItem | None:
        if not self.ai_enabled() or not self.settings.deepseek_api_key:
            return None
        if self.settings.ai_direction_shift_daily_call_limit <= 0:
            return None
        date = trading_date()
        existing = self.store.ai_summary_for("direction_shift", date)
        market_flow = market_flow_report
        if market_flow is None:
            try:
                market_flow = await self.market_flow(force=False)
            except Exception:
                return existing
        event = self._direction_shift_event(market_flow)
        if event is None:
            return None
        if self.store.ai_call_count(date, purpose="direction_shift") >= self.settings.ai_direction_shift_daily_call_limit:
            self._remember_direction_state(event["current"])
            return existing
        last_call_at = _parse_datetime(self.store.get_text_setting("ai_direction_shift_last_call_at", ""))
        now = datetime.now(timezone.utc)
        if last_call_at and (now - last_call_at).total_seconds() < self.settings.ai_direction_shift_cooldown_seconds:
            return existing

        plans = self.build_rule_plans()
        snapshots = self.store.latest_snapshots()
        extra_context = {
            "direction_shift_event": event,
            "summary_focus": [
                "判断方向是否真的切换，而不是只看一轮成交额放大",
                "解释触发原因：方向、阶段、主线概率、主力状态哪一项变了",
                "区分新主线、候选切换和单日脉冲",
                "说明下一步等什么确认，以及哪些反证会否定切换",
            ],
        }
        context, source_data_time = build_ai_context(
            self.settings,
            plans,
            market_flow,
            snapshots,
            kind="direction_shift",
            extra_context=extra_context,
        )
        try:
            summary_text = await self.ai.summarize_market("direction_shift", context)
            item = make_summary_item(
                kind="direction_shift",
                trading_date_value=date,
                model=self.settings.deepseek_model,
                summary=summary_text,
                source_data_time=source_data_time,
                payload={"context": context},
            )
            self.store.log_ai_call("direction_shift", event["trigger"], date, "ok")
            self.store.set_text_setting("ai_direction_shift_last_call_at", now.isoformat())
            self._remember_direction_state(event["current"])
            return self.store.save_ai_summary(item)
        except Exception as exc:
            error = str(exc)[:300]
            self.store.log_ai_call("direction_shift", event["trigger"], date, "error", error=error)
            self.store.set_text_setting("ai_direction_shift_last_call_at", now.isoformat())
            self._remember_direction_state(event["current"])
            item = make_summary_item(
                kind="direction_shift",
                trading_date_value=date,
                model=self.settings.deepseek_model,
                summary="方向突变复核生成失败，暂以规则引擎方向变化为准。",
                source_data_time=source_data_time,
                status="error",
                error=error,
                payload={"context": context},
            )
            return self.store.save_ai_summary(item)

    def _direction_shift_event(self, market_flow: MarketFlowResponse) -> dict | None:
        if not market_flow.directions:
            return None
        current = _direction_state_payload(market_flow.directions[0])
        previous = self._previous_direction_state()
        if previous is None:
            self._remember_direction_state(current)
            return None
        reasons = _direction_shift_reasons(previous, current, self.settings.ai_direction_shift_probability_delta)
        if not reasons:
            self._remember_direction_state(current)
            return None
        return {
            "trigger": "+".join(reasons),
            "previous": previous,
            "current": current,
            "reasons": reasons,
            "thresholds": {
                "probability_delta": self.settings.ai_direction_shift_probability_delta,
                "cooldown_seconds": self.settings.ai_direction_shift_cooldown_seconds,
                "daily_limit": self.settings.ai_direction_shift_daily_call_limit,
            },
        }

    def _previous_direction_state(self) -> dict | None:
        raw = self.store.get_text_setting("ai_direction_shift_last_state", "")
        if raw:
            try:
                value = json.loads(raw)
                if isinstance(value, dict) and value.get("direction_key"):
                    return value
            except Exception:
                pass
        for summary in self.store.latest_ai_summaries(limit=5):
            state = _summary_top_direction_state(summary.payload)
            if state is not None:
                return state
        return None

    def _remember_direction_state_from_context(self, context: dict) -> None:
        state = _summary_top_direction_state({"context": context})
        if state is not None:
            self._remember_direction_state(state)

    def _remember_direction_state(self, state: dict) -> None:
        self.store.set_text_setting("ai_direction_shift_last_state", json.dumps(state, ensure_ascii=False, sort_keys=True))

    async def attach_ai_trade_reviews(self, report: QuantDecisionResponse) -> QuantDecisionResponse:
        events = self._trade_review_events(report)[: self.settings.ai_trade_review_max_per_run]
        if not events:
            return report
        if not self.ai_enabled() or not self.settings.deepseek_api_key:
            return report
        if self.settings.ai_trade_review_daily_call_limit <= 0:
            return report

        reviews: list[AiTradeRiskReview] = []
        date = trading_date()
        now = datetime.now(timezone.utc)
        for event in events:
            review_key = str(event["review_key"])
            existing = self.store.ai_trade_review_for(review_key)
            if existing is not None:
                age = (now - existing.generated_at).total_seconds()
                if age < self.settings.ai_trade_review_cooldown_seconds:
                    self._attach_ai_trade_review(report, existing)
                    reviews.append(existing)
                    continue
            calls_used = self.store.ai_call_count(date, purpose="trade_risk_review")
            if calls_used >= self.settings.ai_trade_review_daily_call_limit:
                if existing is not None:
                    self._attach_ai_trade_review(report, existing)
                    reviews.append(existing)
                continue
            review = await self.ai.review_trade_opportunity(event)
            self.store.log_ai_call(
                "trade_risk_review",
                str(event.get("kind", event.get("side", "trade"))),
                date,
                review.status,
                error=review.error,
            )
            saved = self.store.save_ai_trade_review(review)
            self._attach_ai_trade_review(report, saved)
            reviews.append(saved)

        report.ai_risk_reviews = _unique_reviews([*report.ai_risk_reviews, *reviews])
        return report

    def _trade_review_events(self, report: QuantDecisionResponse) -> list[dict]:
        date = trading_date()
        events: list[dict] = []
        direction = report.direction
        for item in report.stocks:
            execution = item.execution
            if not execution or item.action != "BUY_PROBE" or execution.decision_state != "buy_probe":
                continue
            events.append(
                {
                    "kind": "stock_buy",
                    "review_key": f"{date}:stock:{item.code}:BUY:{item.action}:{direction.direction_key or '-'}",
                    "code": item.code,
                    "name": item.name,
                    "side": "BUY",
                    "action": item.action,
                    "trading_date": date,
                    "direction": {
                        "label": direction.direction_label,
                        "phase": direction.phase_label,
                        "confidence": direction.confidence,
                        "mainline_probability": direction.mainline_probability,
                        "seven_day_score": direction.seven_day_score,
                        "residency_score": direction.residency_score,
                        "retention_score": direction.retention_score,
                    },
                    "price": item.price,
                    "change_pct": item.change_pct,
                    "main_net_inflow_pct": item.main_net_inflow_pct,
                    "volume_ratio": item.volume_ratio,
                    "score": item.score,
                    "buy_zone": [execution.buy_zone_low, execution.buy_zone_high],
                    "avoid_above": execution.avoid_above,
                    "stop_price": execution.stop_price,
                    "take_profit_price": execution.take_profit_price,
                    "trigger_signal": execution.trigger_signal,
                    "decision_reason": execution.decision_reason,
                    "invalidation": [execution.invalidation_signal, execution.reduce_signal, execution.hard_exit_signal],
                    "conditions": [condition.model_dump(mode="json") for condition in execution.conditions],
                    "risk_flags": item.risk_flags[:6],
                    "blockers": execution.blockers[:6],
                }
            )

        for item in report.fixed_pool_actions:
            side = _review_side_for_fixed_action(item.action)
            if side is None:
                continue
            events.append(
                {
                    "kind": "etf_" + side.lower(),
                    "review_key": f"{date}:etf:{item.code}:{side}:{item.action}",
                    "code": item.code,
                    "name": item.name,
                    "side": side,
                    "action": item.action,
                    "trading_date": date,
                    "direction": {"label": item.direction_label},
                    "price": item.price,
                    "has_position": item.has_position,
                    "floating_profit_pct": item.floating_profit_pct,
                    "suggested_position_pct": item.suggested_position_pct,
                    "buy_zone": [item.buy_zone_low, item.buy_zone_high],
                    "avoid_above": item.avoid_above,
                    "stop_price": item.exit_price,
                    "take_profit_price": item.take_profit_price,
                    "trigger_signal": item.operation,
                    "invalidation": item.risk_flags[:3],
                    "risk_flags": item.risk_flags[:6],
                    "reasons": item.reasons[:6],
                }
            )
        for item in report.holdings:
            side = _review_side_for_holding_action(item.action)
            if side is None:
                continue
            events.append(
                {
                    "kind": "holding_" + side.lower(),
                    "review_key": f"{date}:holding:{item.code}:{side}:{item.action}:{item.risk_level}",
                    "code": item.code,
                    "name": item.name,
                    "side": side,
                    "action": item.action,
                    "trading_date": date,
                    "direction": {"label": item.related_direction_label, "match": item.direction_match},
                    "price": item.current_price,
                    "entry_price": item.entry_price,
                    "floating_profit_pct": item.floating_profit_pct,
                    "main_force_state": item.main_force_state,
                    "risk_level": item.risk_level,
                    "stop_price": item.stop_price,
                    "weak_exit_price": item.weak_exit_price,
                    "rebound_reduce_price": item.rebound_reduce_price,
                    "take_profit_price": item.take_profit_price,
                    "trigger_signal": item.position_plan,
                    "invalidation": [item.exit_plan],
                    "conditions": [condition.model_dump(mode="json") for condition in item.conditions],
                    "risk_flags": item.risk_flags[:6],
                    "reasons": item.reasons[:6],
                }
            )
        return events

    def _attach_ai_trade_review(self, report: QuantDecisionResponse, review: AiTradeRiskReview) -> None:
        for stock in report.stocks:
            if stock.code == review.code and stock.execution is not None:
                stock.execution.ai_risk_review = review
        for item in [*report.etfs, *report.fixed_pool_actions]:
            if item.code == review.code:
                item.ai_risk_review = review
        for item in report.holdings:
            if item.code == review.code:
                item.ai_risk_review = review


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


def _direction_state_payload(direction) -> dict:
    return {
        "direction_key": direction.direction_key,
        "direction_label": direction.direction_label,
        "state": direction.state,
        "mainline_probability": direction.mainline_probability,
        "residency_score": direction.residency_score,
        "retention_score": direction.retention_score,
        "capital_status": direction.capital_status,
        "trade_action": direction.trade_action,
        "seven_day_score": direction.factor_scores.get("seven_day_score", 0),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _summary_top_direction_state(payload: dict) -> dict | None:
    context = payload.get("context") if isinstance(payload, dict) else None
    if not isinstance(context, dict):
        return None
    directions = context.get("market_directions") or []
    if not directions:
        return None
    top = directions[0]
    if not isinstance(top, dict) or not top.get("direction_label"):
        return None
    return {
        "direction_key": top.get("direction_key") or _direction_key_from_label(str(top.get("direction_label") or "")),
        "direction_label": top.get("direction_label"),
        "state": top.get("state"),
        "mainline_probability": int(top.get("mainline_probability") or top.get("score") or 0),
        "residency_score": int(top.get("residency_score") or 0),
        "retention_score": int(top.get("retention_score") or 0),
        "capital_status": top.get("capital_status"),
        "trade_action": top.get("trade_action"),
        "seven_day_score": int((top.get("factor_scores") or {}).get("seven_day_score") or 0),
    }


def _direction_shift_reasons(previous: dict, current: dict, probability_delta: int) -> list[str]:
    reasons: list[str] = []
    if previous.get("direction_key") != current.get("direction_key"):
        reasons.append("第一方向切换")
    if previous.get("state") != current.get("state"):
        reasons.append("阶段切换")
    previous_probability = int(previous.get("mainline_probability") or 0)
    current_probability = int(current.get("mainline_probability") or 0)
    if abs(current_probability - previous_probability) >= probability_delta:
        reasons.append("主线概率大幅变化")
    if previous.get("capital_status") != current.get("capital_status"):
        reasons.append("主力状态变化")
    if previous.get("trade_action") != current.get("trade_action"):
        reasons.append("交易阶段变化")
    return reasons


def _direction_key_from_label(label: str) -> str:
    return label.strip().lower().replace("/", "_").replace(" ", "_") or "unknown"


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except Exception:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _top(plans: list[TradePlan], field: str) -> str | None:
    if not plans:
        return None
    return max(plans, key=lambda plan: getattr(plan, field)).code


def _unique_codes(codes) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for code in codes:
        if not code or code in seen:
            continue
        result.append(code)
        seen.add(code)
    return result


def _review_side_for_fixed_action(action: str) -> str | None:
    if action == "BUY_FIRST_BATCH":
        return "BUY"
    if action in {"SELL_ALL", "SELL_PARTIAL_50", "SELL_PARTIAL_20_30", "REDUCE_OR_HOLD_TIGHT"}:
        return "SELL"
    return None


def _review_side_for_holding_action(action: str) -> str | None:
    if action in {"EXIT", "REDUCE_OR_EXIT", "REDUCE_ON_REBOUND", "TAKE_PROFIT"}:
        return "SELL"
    return None


def _unique_reviews(items: list[AiTradeRiskReview]) -> list[AiTradeRiskReview]:
    result: list[AiTradeRiskReview] = []
    seen: set[str] = set()
    for item in items:
        if item.review_key in seen:
            continue
        result.append(item)
        seen.add(item.review_key)
    return result
