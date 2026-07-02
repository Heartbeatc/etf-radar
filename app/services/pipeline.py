from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.core.config import Settings
from app.domain.models import EtfSnapshot, SourceStatus, TradePlan
from app.services.scoring import AnalysisInputs, build_plan

TOPIC_SUFFIXES = ["market.normalized.snapshot", "signal.generated", "source.status"]


def roles_for(settings: Settings) -> dict[str, str]:
    roles = {code: "main" for code in settings.main_codes}
    roles.update({code: "backup" for code in settings.backup_codes})
    roles.update({code: "benchmark" for code in settings.benchmark_code_list})
    return roles


def source_status_for(settings: Settings, latest: dict[str, EtfSnapshot]) -> list[SourceStatus]:
    roles = roles_for(settings)
    now = datetime.now(timezone.utc)
    statuses: list[SourceStatus] = []
    for code in settings.all_poll_codes:
        item = latest.get(code)
        role = roles.get(code, "benchmark")
        if not item:
            statuses.append(SourceStatus(code=code, role=role, ok=False, issues=["missing latest snapshot"]))
            continue
        issues: list[str] = []
        age = (now - item.fetched_at).total_seconds()
        if age > settings.source_soft_stale_seconds:
            issues.append(f"stale snapshot over {settings.source_soft_stale_seconds}s")
        if item.price is None or item.price <= 0:
            issues.append("invalid price")
        if role in {"main", "backup"}:
            if item.iopv is None or item.iopv <= 0:
                issues.append("missing ETF IOPV")
            if item.premium_pct is not None and abs(item.premium_pct) > 3:
                issues.append("ETF premium/discount absolute value over 3%")
        statuses.append(
            SourceStatus(
                code=code,
                name=item.name,
                role=role,
                ok=not issues,
                issues=issues,
                source=item.source,
                fetched_at=item.fetched_at,
                age_seconds=round(age, 2),
                source_time=item.source_time,
                price=item.price,
                iopv=item.iopv,
                premium_pct=item.premium_pct,
            )
        )
    return statuses


def build_rule_plans(settings: Settings, store) -> list[TradePlan]:
    plans: list[TradePlan] = []
    for code in settings.exposed_codes:
        plan = build_rule_plan_for_code(settings, store, code)
        if plan is not None:
            plans.append(plan)
    return plans


def build_rule_plan_for_code(settings: Settings, store, code: str) -> TradePlan | None:
    if code not in settings.exposed_codes:
        return None
    latest = store.latest_snapshots()
    snapshot = latest.get(code)
    if snapshot is None:
        return None
    positions = store.positions()
    return build_plan(
        AnalysisInputs(
            snapshot=snapshot,
            daily=store.get_daily_bars(code),
            minute=store.get_minute_bars(code),
            position=positions.get(code),
            stale_seconds=settings.data_stale_seconds,
        )
    )


def model_payload(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return dict(value)
