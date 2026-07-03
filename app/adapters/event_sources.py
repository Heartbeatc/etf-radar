from __future__ import annotations

import hashlib
import html
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlparse

import httpx

from app.core.config import Settings
from app.domain.models import EventItem
from app.services.discovery import DIRECTION_RULES

ADDITIONAL_EVENT_RULES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("innovative_drug", "创新药/医药", ("创新药", "医药", "药品", "药企", "药监", "临床", "CXO", "CRO", "ADC", "PD-1", "GLP-1", "疫苗", "医疗器械")),
    ("ai_compute", "AI算力/通信/数字经济", ("AI", "人工智能", "算力", "光模块", "CPO", "数据中心", "服务器", "液冷", "通信", "PCB", "云计算", "大模型")),
    ("semiconductor", "半导体/芯片", ("半导体", "芯片", "存储", "光刻机", "晶圆", "封装", "集成电路", "国产替代")),
    ("robotics_highend", "机器人/高端制造", ("机器人", "人形机器人", "减速器", "工业母机", "机床", "高端制造", "自动化")),
    ("gold_resources", "黄金/资源", ("黄金", "贵金属", "有色", "铜", "铝", "稀土", "锂", "钴", "煤炭", "资源")),
    ("new_energy", "新能源", ("新能源", "光伏", "储能", "锂电", "电池", "风电", "充电桩", "新能源汽车")),
    ("brokerage_finance", "券商/金融", ("券商", "证券", "银行", "保险", "金融", "互联金融", "并购重组")),
    ("consumer", "消费", ("消费", "白酒", "食品", "旅游", "零售", "家电", "农业", "猪肉", "养殖")),
    ("dividend_value", "红利/央企价值", ("红利", "高股息", "央企", "中特估", "分红", "价值")),
)

POSITIVE_KEYWORDS = (
    "获批", "批准", "中标", "签约", "订单", "增长", "大增", "预增", "突破", "上调", "利好", "扩产", "回购", "并购", "超预期",
)
NEGATIVE_KEYWORDS = (
    "下滑", "亏损", "减持", "处罚", "召回", "暂停", "退市", "利空", "下调", "暴跌", "风险", "立案", "问询",
)
POLICY_KEYWORDS = ("政策", "国务院", "发改委", "工信部", "证监会", "央行", "财政部", "药监局", "商务部", "监管", "规划", "指导意见")
ORDER_KEYWORDS = ("订单", "合同", "中标", "签约", "采购", "交付")
EARNINGS_KEYWORDS = ("业绩", "预增", "财报", "利润", "营收", "扭亏", "超预期")
TECH_KEYWORDS = ("突破", "发布", "研发", "量产", "首款", "升级", "创新")
SYMBOL_RE = re.compile(r"(?<!\d)(?:[036]\d{5}|[48]\d{5})(?!\d)")
TAG_CLEAN_RE = re.compile(r"<[^>]+>")


class FreeEventSourceClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = httpx.AsyncClient(
            timeout=settings.event_corpus_request_timeout_seconds,
            headers={"User-Agent": "ETF-Radar/1.0 (+free event metadata only)"},
            follow_redirects=True,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def fetch(self) -> tuple[list[EventItem], list[str]]:
        if not self.settings.event_corpus_enabled:
            return [], ["事件语料开关已关闭"]
        urls = self.settings.event_source_url_list
        if not urls:
            return [], ["未配置 EVENT_CORPUS_SOURCE_URLS；事件催化因子不会参与评分"]
        warnings: list[str] = []
        events: list[EventItem] = []
        for url in urls[:12]:
            try:
                request_url = _resolve_url(url)
                response = await self._client.get(request_url)
                response.raise_for_status()
                parsed, source_warnings = parse_event_payload(request_url, response.text, response.headers.get("content-type", ""))
                events.extend(parsed)
                warnings.extend(source_warnings)
            except Exception as exc:
                warnings.append(f"事件源抓取失败 {url}: {str(exc)[:120]}")
        events = _dedupe_events(events)
        events.sort(key=lambda item: (item.published_at or item.fetched_at, item.relevance_score), reverse=True)
        return events[: self.settings.event_corpus_max_items], warnings[:20]


def _resolve_url(url: str) -> str:
    stamp = str(round(datetime.now(timezone.utc).timestamp() * 1000))
    return url.replace("{timestamp}", stamp).replace("req_trace=auto", f"req_trace={stamp}")


def parse_event_payload(url: str, content: str, content_type: str = "") -> tuple[list[EventItem], list[str]]:
    stripped = content.lstrip()
    if _looks_like_xml(stripped, content_type):
        return parse_rss_or_atom(url, content), []
    if _looks_like_json(stripped, content_type):
        return parse_json_feed(url, content)
    return [], [f"事件源不是 RSS/Atom/JSON，已跳过：{url}"]


def parse_rss_or_atom(url: str, content: str) -> list[EventItem]:
    root = ET.fromstring(content.encode("utf-8"))
    source = _source_name(url, root)
    items = root.findall(".//item")
    if items:
        return [_event_from_mapping(source, _rss_item_mapping(item)) for item in items if _node_text(item, "title")]
    entries = root.findall(".//{http://www.w3.org/2005/Atom}entry") or root.findall(".//entry")
    return [_event_from_mapping(source, _atom_entry_mapping(entry)) for entry in entries if _atom_text(entry, "title")]


def parse_json_feed(url: str, content: str) -> tuple[list[EventItem], list[str]]:
    warnings: list[str] = []
    try:
        data = json.loads(_strip_jsonp(content))
    except Exception as exc:
        return [], [f"JSON事件源解析失败 {url}: {str(exc)[:80]}"]
    rows = _json_rows(data)
    source = urlparse(url).netloc or url
    events: list[EventItem] = []
    for row in rows[:300]:
        if not isinstance(row, dict):
            continue
        title = _first_text(row, ("title", "name", "content", "brief", "digest"))
        if not title:
            continue
        events.append(
            _event_from_mapping(
                source,
                {
                    "title": title,
                    "summary": _first_text(row, ("summary", "digest", "description", "content")),
                    "url": _first_text(row, ("url", "uniqueUrl", "link", "share_url")),
                    "published_at": _parse_datetime(_first_text(row, ("published_at", "publish_time", "showTime", "pubDate", "time", "ctime", "datetime"))),
                },
            )
        )
    if not events:
        warnings.append(f"JSON事件源没有可识别的新闻条目：{url}")
    return events, warnings


def classify_event_text(text: str) -> tuple[str, str, list[str]]:
    normalized = text.upper()
    hits: list[str] = []
    for key, label, keywords in ADDITIONAL_EVENT_RULES + DIRECTION_RULES:
        matched = [keyword for keyword in keywords if keyword.upper() in normalized]
        if matched:
            hits.extend(matched[:4])
            return key, label, hits[:8]
    return "other_theme", "其他主题", []


def _rss_item_mapping(item: ET.Element) -> dict[str, Any]:
    return {
        "title": _node_text(item, "title"),
        "summary": _node_text(item, "description"),
        "url": _node_text(item, "link"),
        "published_at": _parse_datetime(_node_text(item, "pubDate") or _node_text(item, "dc:date")),
    }


def _atom_entry_mapping(entry: ET.Element) -> dict[str, Any]:
    link = ""
    for child in list(entry):
        if _local_name(child.tag) == "link":
            link = child.attrib.get("href") or (child.text or "")
            if link:
                break
    return {
        "title": _atom_text(entry, "title"),
        "summary": _atom_text(entry, "summary") or _atom_text(entry, "content"),
        "url": link,
        "published_at": _parse_datetime(_atom_text(entry, "published") or _atom_text(entry, "updated")),
    }


def _event_from_mapping(source: str, mapping: dict[str, Any]) -> EventItem:
    title = _clean_text(str(mapping.get("title") or ""))[:220]
    summary = _clean_text(str(mapping.get("summary") or ""))[:600]
    url = str(mapping.get("url") or "").strip() or None
    published_at = mapping.get("published_at")
    if isinstance(published_at, str):
        published_at = _parse_datetime(published_at)
    text = f"{title} {summary}"
    direction_key, direction_label, matched_keywords = classify_event_text(text)
    sentiment = _sentiment(text)
    catalyst_type = _catalyst_type(text)
    symbols = sorted(set(SYMBOL_RE.findall(text)))[:12]
    score = _relevance_score(direction_key, matched_keywords, sentiment, catalyst_type, symbols, published_at)
    raw = "|".join([source, url or "", title, published_at.isoformat() if published_at else ""])
    raw_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    tags = [*matched_keywords, catalyst_type, sentiment]
    return EventItem(
        id=raw_hash[:24],
        source=source[:80],
        title=title,
        summary=summary,
        url=url,
        published_at=published_at,
        fetched_at=datetime.now(timezone.utc),
        direction_key=direction_key,
        direction_label=direction_label,
        relevance_score=score,
        sentiment=sentiment,
        catalyst_type=catalyst_type,
        symbols=symbols,
        tags=[tag for tag in dict.fromkeys(tags) if tag and tag != "neutral"][:12],
        raw_hash=raw_hash,
    )


def _source_name(url: str, root: ET.Element) -> str:
    channel_title = root.findtext("./channel/title") or root.findtext("./{http://www.w3.org/2005/Atom}title")
    host = urlparse(url).netloc or url
    return _clean_text(channel_title or host)[:80]


def _node_text(item: ET.Element, name: str) -> str:
    if ":" in name:
        suffix = name.split(":", 1)[1]
        for child in list(item):
            if _local_name(child.tag) == suffix:
                return child.text or ""
        return ""
    return item.findtext(name) or ""


def _atom_text(entry: ET.Element, name: str) -> str:
    for child in list(entry):
        if _local_name(child.tag) == name:
            return child.text or ""
    return ""


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _clean_text(value: str) -> str:
    value = TAG_CLEAN_RE.sub(" ", html.unescape(value or ""))
    return re.sub(r"\s+", " ", value).strip()


def _strip_jsonp(value: str) -> str:
    stripped = value.strip()
    match = re.match(r"^[\w.]+\((.*)\);?$", stripped, re.S)
    return match.group(1) if match else stripped


def _json_rows(data: Any) -> list[Any]:
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    for key in ("items", "data", "list", "news", "articles", "result"):
        value = data.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            nested = _json_rows(value)
            if nested:
                return nested
    return []


def _first_text(row: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip():
            return _clean_text(str(value))
    return ""


def _looks_like_xml(content: str, content_type: str) -> bool:
    lower = content_type.lower()
    return "xml" in lower or content.startswith("<?xml") or content.startswith("<rss") or content.startswith("<feed")


def _looks_like_json(content: str, content_type: str) -> bool:
    lower = content_type.lower()
    return "json" in lower or content.startswith("{") or content.startswith("[") or bool(re.match(r"^[\w.]+\(\s*[\[{]", content))


def _parse_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit()):
        ts = float(value)
        if ts > 10_000_000_000:
            ts /= 1000
        try:
            return datetime.fromtimestamp(ts, timezone.utc)
        except Exception:
            return None
    text = str(value).strip()
    try:
        parsed = parsedate_to_datetime(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        pass
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def _sentiment(text: str) -> str:
    positive = sum(1 for keyword in POSITIVE_KEYWORDS if keyword in text)
    negative = sum(1 for keyword in NEGATIVE_KEYWORDS if keyword in text)
    if positive > negative:
        return "positive"
    if negative > positive:
        return "negative"
    return "neutral"


def _catalyst_type(text: str) -> str:
    if any(keyword in text for keyword in POLICY_KEYWORDS):
        return "policy"
    if any(keyword in text for keyword in ORDER_KEYWORDS):
        return "order"
    if any(keyword in text for keyword in EARNINGS_KEYWORDS):
        return "earnings"
    if any(keyword in text for keyword in TECH_KEYWORDS):
        return "technology"
    return "news"


def _relevance_score(
    direction_key: str,
    matched_keywords: list[str],
    sentiment: str,
    catalyst_type: str,
    symbols: list[str],
    published_at: datetime | None,
) -> int:
    score = 18.0
    if direction_key and direction_key != "other_theme":
        score += 38
    score += min(16, len(matched_keywords) * 4)
    if catalyst_type in {"policy", "order", "earnings", "technology"}:
        score += 10
    if sentiment == "positive":
        score += 8
    elif sentiment == "negative":
        score -= 12
    if symbols:
        score += 5
    if published_at:
        age_hours = max(0.0, (datetime.now(timezone.utc) - published_at).total_seconds() / 3600)
        if age_hours <= 8:
            score += 8
        elif age_hours <= 36:
            score += 4
        elif age_hours >= 168:
            score -= 8
    return max(0, min(100, round(score)))


def _dedupe_events(items: list[EventItem]) -> list[EventItem]:
    seen: set[str] = set()
    result: list[EventItem] = []
    for item in items:
        key = item.url or item.id
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result
