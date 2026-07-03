from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from app.domain.models import DirectionEventSignal, EventCorpusReport, EventItem


def build_event_corpus_report(
    *,
    items: list[EventItem],
    fetched_count: int,
    stored_count: int,
    warnings: list[str] | None = None,
    source: str = "free_event_sources_v1",
) -> EventCorpusReport:
    ranked_items = sorted(
        items,
        key=lambda item: (item.published_at or item.fetched_at, item.relevance_score),
        reverse=True,
    )
    signals = _direction_signals(ranked_items)
    report_warnings = list(warnings or [])
    if not ranked_items:
        report_warnings.append("暂无可用事件语料；主线判断只使用行情/资金/ETF/历史驻留代理指标")
    return EventCorpusReport(
        generated_at=datetime.now(timezone.utc),
        source=source,
        fetched_count=fetched_count,
        stored_count=stored_count,
        items=ranked_items[:200],
        direction_signals=signals,
        warnings=report_warnings[:20],
        assumptions=[
            "免费事件语料只保存标题、摘要、链接、时间和方向标签，不保存付费全文。",
            "事件催化只能作为弱证据，不能单独确认主线或触发买入。",
            "方向必须继续通过资金驻留、承接、扩散、代表股和ETF载体验证。",
        ],
    )


def direction_event_scores(report: EventCorpusReport | None) -> dict[str, DirectionEventSignal]:
    if report is None:
        return {}
    return {item.direction_key: item for item in report.direction_signals}


def _direction_signals(items: list[EventItem]) -> list[DirectionEventSignal]:
    groups: dict[str, list[EventItem]] = defaultdict(list)
    for item in items:
        if item.direction_key and item.direction_key != "other_theme":
            groups[item.direction_key].append(item)
    signals: list[DirectionEventSignal] = []
    for key, events in groups.items():
        events.sort(key=lambda item: (item.relevance_score, item.published_at or item.fetched_at), reverse=True)
        latest = max((item.published_at or item.fetched_at for item in events), default=None)
        catalysts = [item.catalyst_type for item in events if item.catalyst_type]
        catalyst_diversity = len(set(catalysts))
        positive_count = sum(1 for item in events if item.sentiment == "positive")
        negative_count = sum(1 for item in events if item.sentiment == "negative")
        top_score = max((item.relevance_score for item in events), default=0)
        event_count_score = min(24, len(events) * 5)
        diversity_score = min(12, catalyst_diversity * 4)
        sentiment_score = min(12, positive_count * 4) - min(16, negative_count * 6)
        recency_score = _recency_score(latest)
        score = _clamp(top_score * 0.42 + event_count_score + diversity_score + sentiment_score + recency_score)
        label = events[0].direction_label or key
        signals.append(
            DirectionEventSignal(
                direction_key=key,
                direction_label=label,
                event_count=len(events),
                latest_event_at=latest,
                score=score,
                catalysts=list(dict.fromkeys(catalysts))[:8],
                top_events=events[:5],
            )
        )
    signals.sort(key=lambda item: (item.score, item.event_count, item.latest_event_at or datetime.min.replace(tzinfo=timezone.utc)), reverse=True)
    return signals[:12]


def _recency_score(latest: datetime | None) -> int:
    if latest is None:
        return 0
    age_hours = max(0.0, (datetime.now(timezone.utc) - latest).total_seconds() / 3600)
    if age_hours <= 4:
        return 16
    if age_hours <= 24:
        return 10
    if age_hours <= 72:
        return 5
    return 0


def _clamp(value: float) -> int:
    return max(0, min(100, round(value)))
