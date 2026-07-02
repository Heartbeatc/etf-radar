from __future__ import annotations

from typing import Any

import httpx

from app.core.config import Settings
from app.domain.models import AlertEvent, TradePlan
from app.adapters.store import Store

IMPORTANT_SIGNALS = {"low_buy_zone", "partial_take_profit", "strong_take_profit", "exit_first"}
WATCH_SIGNALS = {"watch_low_buy", "hold_watch"}


class AlertManager:
    def __init__(self, settings: Settings, store: Store) -> None:
        self.settings = settings
        self.store = store

    async def process(self, plans: list[TradePlan], previous_signals: dict[str, str]) -> list[AlertEvent]:
        events: list[AlertEvent] = []
        for plan in plans:
            alert = _alert_payload(plan, previous_signals.get(plan.code))
            if not alert:
                continue
            event_key = alert["event"]
            if self.store.recent_alert_exists(plan.code, event_key, self.settings.alert_cooldown_seconds):
                continue
            saved = self.store.save_alert_event(
                code=plan.code,
                level=alert["level"],
                event=event_key,
                message=alert["message"],
                payload=alert["payload"],
            )
            delivered, error = await self._deliver(saved)
            self.store.mark_alert_delivery(saved.id, delivered, error)
            saved.delivered = delivered
            saved.error = error
            events.append(saved)
        return events

    async def send_test(self) -> AlertEvent:
        event = self.store.save_alert_event(
            code="SYSTEM",
            level="info",
            event="test",
            message="ETF Radar webhook test",
            payload={"source": "manual_test"},
        )
        delivered, error = await self._deliver(event)
        self.store.mark_alert_delivery(event.id, delivered, error)
        event.delivered = delivered
        event.error = error
        return event

    async def _deliver(self, event: AlertEvent) -> tuple[bool, str | None]:
        if not self.settings.alert_webhook_url:
            return False, "ALERT_WEBHOOK_URL not configured"
        try:
            async with httpx.AsyncClient(timeout=self.settings.alert_webhook_timeout_seconds) as client:
                response = await client.post(
                    self.settings.alert_webhook_url,
                    json=event.model_dump(mode="json"),
                )
                response.raise_for_status()
            return True, None
        except Exception as exc:
            return False, str(exc)[:300]


def _alert_payload(plan: TradePlan, previous_signal: str | None) -> dict[str, Any] | None:
    changed = previous_signal is not None and previous_signal != plan.signal
    first_seen = previous_signal is None
    actionable = plan.signal in IMPORTANT_SIGNALS or plan.signal in WATCH_SIGNALS
    if not actionable:
        return None
    if not changed and not first_seen and plan.signal not in IMPORTANT_SIGNALS:
        return None
    level = "info"
    if plan.signal in {"exit_first", "strong_take_profit"}:
        level = "high"
    elif plan.signal in {"low_buy_zone", "partial_take_profit", "watch_low_buy"}:
        level = "medium"
    event = f"signal:{plan.signal}"
    message = (
        f"{plan.code} {plan.name} {plan.signal} "
        f"price={plan.current_price} direction={plan.direction_score} "
        f"low_buy={plan.low_buy_score} risk={plan.risk_score}"
    )
    return {
        "level": level,
        "event": event,
        "message": message,
        "payload": {
            "code": plan.code,
            "name": plan.name,
            "signal": plan.signal,
            "previous_signal": previous_signal,
            "changed": changed,
            "current_price": plan.current_price,
            "direction_score": plan.direction_score,
            "low_buy_score": plan.low_buy_score,
            "hold_score": plan.hold_score,
            "take_profit_score": plan.take_profit_score,
            "risk_score": plan.risk_score,
            "buy_zone": plan.buy_zone,
            "take_profit_plan": plan.take_profit_plan,
            "exit_plan": plan.exit_plan,
            "warnings": plan.warnings,
        },
    }
