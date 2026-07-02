from __future__ import annotations

from datetime import datetime, timezone

from app.core.config import Settings
from app.domain.models import DataQualityItem, DataQualityReport, EtfSnapshot, SourceStatus
from app.services.pipeline import source_status_for


def build_data_quality_report(settings: Settings, snapshots: dict[str, EtfSnapshot]) -> DataQualityReport:
    statuses = {item.code: item for item in source_status_for(settings, snapshots)}
    items: list[DataQualityItem] = []
    for code in settings.all_poll_codes:
        snapshot = snapshots.get(code)
        status = statuses.get(code)
        if status is None:
            continue
        score = _score(snapshot, status, settings)
        issues = list(status.issues)
        if snapshot and snapshot.amount is not None and snapshot.amount <= 0:
            issues.append("zero amount")
            score = min(score, 50)
        items.append(
            DataQualityItem(
                code=code,
                name=snapshot.name if snapshot else status.name,
                role=status.role,
                ok=status.ok and score >= 70,
                score=score,
                issues=issues,
                source=status.source,
                age_seconds=status.age_seconds,
                source_time=status.source_time,
                price=status.price,
                iopv=status.iopv,
                premium_pct=status.premium_pct,
                amount=snapshot.amount if snapshot else None,
                main_net_inflow_pct=snapshot.main_net_inflow_pct if snapshot else None,
            )
        )
    overall = round(sum(item.score for item in items) / len(items), 2) if items else 0
    blocked = [item.code for item in items if not item.ok]
    warnings = []
    if blocked:
        warnings.append("some instruments have weak data quality; avoid using them for fresh entry signals")
    if any(item.age_seconds is not None and item.age_seconds > settings.source_soft_stale_seconds for item in items):
        warnings.append("one or more snapshots are stale")
    if any(item.source and item.source != "eastmoney" for item in items):
        warnings.append("free fallback quote source is in use; validate before fresh entry signals")
    return DataQualityReport(
        generated_at=datetime.now(timezone.utc),
        overall_score=overall,
        items=items,
        blocked_codes=blocked,
        warnings=warnings,
    )


def _score(snapshot: EtfSnapshot | None, status: SourceStatus, settings: Settings) -> int:
    if snapshot is None:
        return 0
    score = 100
    if not status.ok:
        score -= 25
    if status.age_seconds is None:
        score -= 20
    elif status.age_seconds > settings.source_soft_stale_seconds:
        score -= 25
    elif status.age_seconds > settings.poll_interval_seconds * 2:
        score -= 10
    if snapshot.price is None or snapshot.price <= 0:
        score -= 40
    if status.role in {"main", "backup"} and (snapshot.iopv is None or snapshot.iopv <= 0):
        score -= 20
    if snapshot.premium_pct is not None and abs(snapshot.premium_pct) > 3:
        score -= 20
    if snapshot.amount is None or snapshot.amount <= 0:
        score -= 10
    if snapshot.source != "eastmoney":
        score -= 5
    return max(0, min(100, score))
