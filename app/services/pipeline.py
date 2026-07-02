from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from app.core.config import Settings
from app.domain.models import EtfSnapshot, SourceStatus, TradePlan
from app.services.scoring import AnalysisInputs, build_plan

TOPIC_SUFFIXES = ["market.normalized.snapshot", "signal.generated", "source.status"]


def roles_for(settings: Settings, position_codes: Iterable[str] | None = None) -> dict[str, str]:
    roles = {code: "main" for code in settings.main_codes}
    roles.update({code: "backup" for code in settings.backup_codes})
    roles.update({code: "benchmark" for code in settings.benchmark_code_list})
    for code in position_codes or []:
        roles.setdefault(code, "position")
    return roles


def monitor_codes(settings: Settings, store) -> list[str]:
    return _dedupe([*settings.all_poll_codes, *position_codes(store)])


def trade_codes(settings: Settings, store) -> list[str]:
    return _dedupe([*settings.exposed_codes, *position_codes(store)])


def position_codes(store) -> list[str]:
    return list(store.positions().keys())


def source_status_for(
    settings: Settings,
    latest: dict[str, EtfSnapshot],
    codes: Iterable[str] | None = None,
    roles: dict[str, str] | None = None,
) -> list[SourceStatus]:
    codes_to_check = list(codes) if codes is not None else settings.all_poll_codes
    role_map = roles or roles_for(settings)
    now = datetime.now(timezone.utc)
    statuses: list[SourceStatus] = []
    for code in codes_to_check:
        item = latest.get(code)
        role = role_map.get(code, "watch")
        if not item:
            statuses.append(SourceStatus(code=code, role=role, ok=False, issues=["missing latest snapshot"]))
            continue
        issues: list[str] = []
        age = (now - item.fetched_at).total_seconds()
        if age > settings.source_soft_stale_seconds:
            issues.append(f"stale snapshot over {settings.source_soft_stale_seconds}s")
        if item.price is None or item.price <= 0:
            issues.append("invalid price")
        if role in {"main", "backup", "position"}:
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
    for code in trade_codes(settings, store):
        plan = build_rule_plan_for_code(settings, store, code)
        if plan is not None:
            plans.append(plan)
    return plans


def build_rule_plan_for_code(settings: Settings, store, code: str) -> TradePlan | None:
    if code not in trade_codes(settings, store):
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


def _dedupe(codes: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for code in codes:
        if not code or code in seen:
            continue
        result.append(code)
        seen.add(code)
    return result


def model_payload(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return dict(value)
