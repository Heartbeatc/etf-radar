from __future__ import annotations

from datetime import datetime, timezone

from app.adapters.event_sources import classify_event_text, parse_event_payload
from app.domain.models import EventItem
from app.services.event_corpus import build_event_corpus_report
from app.services.market_flow import DirectionHistoryStats, _direction_factor_scores


def test_rss_event_payload_parses_and_classifies_direction() -> None:
    rss = """<?xml version="1.0" encoding="utf-8"?>
    <rss version="2.0"><channel><title>free source</title>
      <item>
        <title>工信部发布人形机器人产业政策 机器人方向获订单催化</title>
        <link>https://example.com/a</link>
        <description>多家公司中标，行业景气度提升。</description>
        <pubDate>Fri, 03 Jul 2026 02:00:00 GMT</pubDate>
      </item>
    </channel></rss>
    """
    items, warnings = parse_event_payload("https://example.com/feed.xml", rss, "text/xml")
    assert warnings == []
    assert len(items) == 1
    assert items[0].direction_key == "robotics_highend"
    assert items[0].catalyst_type == "policy"
    assert items[0].relevance_score >= 60


def test_event_report_builds_direction_signal() -> None:
    item = EventItem(
        id="evt1",
        source="unit",
        title="半导体设备订单增长",
        summary="国产设备公司订单增长",
        url="https://example.com/b",
        published_at=datetime.now(timezone.utc),
        fetched_at=datetime.now(timezone.utc),
        direction_key="semiconductor",
        direction_label="半导体/芯片",
        relevance_score=78,
        sentiment="positive",
        catalyst_type="order",
        symbols=[],
        tags=["半导体", "order"],
        raw_hash="hash",
    )
    report = build_event_corpus_report(items=[item], fetched_count=1, stored_count=1)
    assert report.direction_signals[0].direction_key == "semiconductor"
    assert report.direction_signals[0].score >= 50


def test_event_score_is_weak_factor_not_mainline_bypass() -> None:
    class Signal:
        score = 90
        event_count = 6

    factors, _ = _direction_factor_scores(
        items=[],
        total_amount=500_000_000,
        market_amount=20_000_000_000,
        inflow=0,
        avg_change=0,
        breadth=45,
        linked_etfs=[],
        linked_stocks=[],
        history_stats=DirectionHistoryStats(days_count=0, observations=0),
        event_signal=Signal(),
    )
    assert factors["event_score"] == 90
    assert factors["mainline_probability"] <= 52


def test_event_text_classifier_maps_ai_compute() -> None:
    key, label, hits = classify_event_text("AI算力 数据中心 光模块订单增长")
    assert key == "ai_compute"
    assert label
    assert hits


def test_eastmoney_json_feed_shape_parses() -> None:
    payload = """{
      "code":"1",
      "data":{"list":[{
        "summary":"多只概念股获资金青睐，存储和半导体需求变化。",
        "code":"202607030001",
        "showTime":"2026-07-03 09:20:00",
        "uniqueUrl":"http://finance.eastmoney.com/a/202607030001.html",
        "title":"存储荒里逆势加单 多只半导体概念股获资金青睐"
      }]}
    }"""
    items, warnings = parse_event_payload("https://np-listapi.eastmoney.com/example", payload, "application/json")
    assert warnings == []
    assert len(items) == 1
    assert items[0].url == "http://finance.eastmoney.com/a/202607030001.html"
    assert items[0].published_at is not None
    assert items[0].direction_key == "semiconductor"
