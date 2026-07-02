from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from math import log10
from statistics import mean

from app.core.config import Settings
from app.domain.models import DiscoveryDirection, DiscoveryEtfCandidate, DiscoveryResponse, EtfSnapshot

EXCLUDE_KEYWORDS = (
    "货币", "现金", "添富快线", "保证金", "债", "国债", "政金债", "地方债", "城投", "短融",
    "可转债", "转债", "信用", "中短债", "REIT", "REITS", "商品期货",
)
CROSS_BORDER_KEYWORDS = ("港股", "港股通", "恒生", "中概", "H股", "香港", "纳斯达克", "标普", "日经", "德国")
A_SHARE_PREFERRED_DIRECTIONS = {
    "innovative_drug",
    "semiconductor",
    "ai_compute",
    "gold_resources",
    "robotics_highend",
    "new_energy",
    "brokerage_finance",
    "consumer",
    "dividend_value",
    "broad_index",
}

DIRECTION_RULES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("innovative_drug", "创新药/医药", ("创新药", "生物医药", "医药", "医疗", "生物科技", "疫苗", "中药")),
    ("semiconductor", "半导体/芯片", ("半导体", "芯片", "集成电路", "科创芯片", "芯片产业")),
    ("ai_compute", "AI算力/通信/数字经济", ("人工智能", "AI", "算力", "通信", "5G", "云计算", "数据", "软件", "信创", "计算机", "数字经济", "互联网")),
    ("gold_resources", "黄金/资源", ("黄金", "有色", "稀土", "资源", "煤炭", "钢铁", "油气", "能源", "矿业")),
    ("robotics_highend", "机器人/高端制造", ("机器人", "高端制造", "机床", "工业母机", "智能制造", "机械", "军工", "国防")),
    ("new_energy", "新能源", ("新能源", "电池", "锂电", "光伏", "储能", "汽车", "智能车", "电动车")),
    ("hongkong", "港股/中概", ("港股", "恒生", "中概", "H股", "互联", "香港")),
    ("brokerage_finance", "券商/金融", ("证券", "券商", "金融", "银行", "保险", "非银")),
    ("consumer", "消费", ("消费", "酒", "食品", "饮料", "家电", "旅游", "农业", "养殖")),
    ("dividend_value", "红利/央企价值", ("红利", "高股息", "央企", "国企", "价值", "低波")),
    ("broad_index", "宽基指数", ("沪深300", "中证500", "中证1000", "A500", "创业板", "科创50", "上证50", "深证", "MSCI")),
)


def build_discovery_report(
    settings: Settings,
    snapshots: list[EtfSnapshot],
    *,
    min_amount: float | None = None,
    max_directions: int = 8,
) -> DiscoveryResponse:
    threshold = min_amount if min_amount is not None else settings.discovery_min_amount
    filtered: list[EtfSnapshot] = []
    rejected_count = 0
    for snapshot in snapshots:
        if _is_tradable_etf(snapshot, threshold):
            filtered.append(snapshot)
        else:
            rejected_count += 1

    candidates = [_candidate(snapshot, threshold) for snapshot in filtered]
    groups: dict[str, list[DiscoveryEtfCandidate]] = defaultdict(list)
    for item in candidates:
        groups[item.direction_key].append(item)

    directions = [_direction(key, items) for key, items in groups.items()]
    directions.sort(key=lambda item: item.score, reverse=True)
    selected = _select_candidates(directions)
    for idx, item in enumerate(selected):
        item.role = "main" if idx < 2 else "backup"
        item.rank = idx + 1

    warnings: list[str] = []
    if not selected:
        warnings.append("no ETF candidate passed liquidity and quality filters")
    if any(item.entry_bias == "direction_hot_wait_pullback" for item in selected):
        warnings.append("one or more selected directions are hot; wait for pullback instead of chasing")
    if rejected_count > 0:
        warnings.append(f"filtered out {rejected_count} low-liquidity or non-equity/bond/cash-like instruments")

    return DiscoveryResponse(
        generated_at=datetime.now(timezone.utc),
        source="eastmoney_universe_free",
        universe_count=len(snapshots),
        filtered_count=len(filtered),
        min_amount=threshold,
        main_candidates=selected[:2],
        backup_candidate=selected[2] if len(selected) >= 3 else None,
        directions=directions[:max_directions],
        warnings=warnings,
        assumptions=[
            "Free source, not paid exchange-grade feed.",
            "Discovery ranks directions; it does not mean immediate buy.",
            "Candidate pool is dynamic, but existing tracked ETF list is not auto-rewritten.",
            "High score with large same-day gain is treated as direction confirmation, not a chase signal.",
        ],
    )


def _is_tradable_etf(snapshot: EtfSnapshot, min_amount: float) -> bool:
    name = snapshot.name.upper()
    if "ETF" not in name:
        return False
    if any(keyword.upper() in name for keyword in EXCLUDE_KEYWORDS):
        return False
    if snapshot.price is None or snapshot.price <= 0:
        return False
    if snapshot.amount is None or snapshot.amount < min_amount:
        return False
    if snapshot.iopv is None or snapshot.iopv <= 0:
        return False
    if snapshot.premium_pct is not None and abs(snapshot.premium_pct) > 4:
        return False
    return True


def _candidate(snapshot: EtfSnapshot, min_amount: float) -> DiscoveryEtfCandidate:
    direction_key, direction_label = _classify(snapshot.name)
    score, evidence, risk_flags = _candidate_score(snapshot, min_amount, direction_key)
    return DiscoveryEtfCandidate(
        code=snapshot.code,
        name=snapshot.name,
        direction_key=direction_key,
        direction_label=direction_label,
        role="watch",
        rank=None,
        score=score,
        price=snapshot.price,
        change_pct=snapshot.change_pct,
        amount=snapshot.amount,
        volume_ratio=snapshot.volume_ratio,
        turnover_pct=snapshot.turnover_pct,
        main_net_inflow=snapshot.main_net_inflow,
        main_net_inflow_pct=snapshot.main_net_inflow_pct,
        premium_pct=snapshot.premium_pct,
        iopv=snapshot.iopv,
        entry_bias=_entry_bias(snapshot),
        evidence=evidence,
        risk_flags=risk_flags,
        source_time=snapshot.source_time,
    )


def _candidate_score(snapshot: EtfSnapshot, min_amount: float, direction_key: str) -> tuple[int, list[str], list[str]]:
    score = 35.0
    evidence: list[str] = []
    risk_flags: list[str] = []
    change = snapshot.change_pct or 0.0
    amount = snapshot.amount or 0.0
    volume_ratio = snapshot.volume_ratio
    turnover = snapshot.turnover_pct
    inflow_pct = snapshot.main_net_inflow_pct
    premium = snapshot.premium_pct
    amplitude = snapshot.amplitude_pct

    if change >= 5:
        score += 22
        evidence.append("same-day strength is leading")
    elif change >= 2:
        score += 16
        evidence.append("same-day strength is positive")
    elif change >= 0:
        score += 7
    else:
        score += max(-12, change * 2.5)
        risk_flags.append("same-day price is weak")

    liquidity_score = min(22.0, max(0.0, log10(max(amount, 1) / max(min_amount, 1)) * 10 + 8))
    score += liquidity_score
    if amount >= max(min_amount * 4, 200_000_000):
        evidence.append("liquidity is strong")

    if volume_ratio is not None:
        if volume_ratio >= 1.8:
            score += 11
            evidence.append("volume ratio confirms attention")
        elif volume_ratio >= 1.2:
            score += 6
        elif volume_ratio < 0.7:
            score -= 5
            risk_flags.append("volume ratio is weak")

    if turnover is not None:
        if turnover >= 5:
            score += 8
        elif turnover >= 2:
            score += 4

    if inflow_pct is not None:
        if inflow_pct >= 8:
            score += 12
            evidence.append("estimated big-order flow is positive")
        elif inflow_pct >= 2:
            score += 6
        elif inflow_pct <= -10:
            score -= 10
            risk_flags.append("estimated big-order flow is negative")
        elif inflow_pct <= -3:
            score -= 4

    if premium is not None:
        abs_premium = abs(premium)
        if abs_premium <= 0.6:
            score += 7
            evidence.append("ETF premium/discount is controlled")
        elif abs_premium <= 1.2:
            score += 2
        elif abs_premium >= 2:
            score -= 12
            risk_flags.append("ETF premium/discount is high")

    if amplitude is not None and amplitude >= 8:
        score -= 5
        risk_flags.append("intraday amplitude is high")
    if change >= 6 and amplitude is not None and amplitude >= 8:
        risk_flags.append("hot direction, avoid chasing at high price")

    if direction_key in A_SHARE_PREFERRED_DIRECTIONS:
        if _is_cross_border_theme(snapshot.name):
            score -= 26
            risk_flags.append("港股/跨境载体，非港股主线不优先作为主ETF")
        else:
            score += 10
            evidence.append("A股场内载体，符合本系统优先交易范围")

    return _clamp(score), evidence[:8], risk_flags[:8]


def _entry_bias(snapshot: EtfSnapshot) -> str:
    change = snapshot.change_pct or 0.0
    premium = abs(snapshot.premium_pct or 0.0)
    amount = snapshot.amount or 0.0
    if premium >= 1.5:
        return "avoid_premium"
    if change >= 5.5:
        return "direction_hot_wait_pullback"
    if 0.5 <= change <= 3.5 and amount >= 150_000_000:
        return "watch_low_buy"
    if -2 <= change < 0.5 and amount >= 150_000_000:
        return "pullback_watch"
    return "wait"


def _direction(key: str, items: list[DiscoveryEtfCandidate]) -> DiscoveryDirection:
    items = sorted(items, key=lambda item: item.score, reverse=True)
    label = items[0].direction_label if items else key
    total_amount = sum(item.amount or 0 for item in items)
    positive = [item for item in items if (item.change_pct or 0) > 0]
    positive_amount = sum(item.amount or 0 for item in positive)
    avg_change = mean([item.change_pct or 0 for item in items]) if items else 0.0
    avg_top_score = mean([item.score for item in items[: min(5, len(items))]]) if items else 0.0
    inflow = sum(item.main_net_inflow or 0 for item in items)
    score = avg_top_score * 0.45
    score += min(22.0, log10(max(total_amount, 1) / 100_000_000) * 8 + 8)
    score += min(16.0, max(0.0, avg_change * 2.4))
    score += (positive_amount / total_amount * 14) if total_amount > 0 else 0
    if inflow > 0:
        score += 5
    elif inflow < -50_000_000:
        score -= 5
    if len(items) < 2:
        score -= 5
    return DiscoveryDirection(
        direction_key=key,
        direction_label=label,
        score=_clamp(score),
        etf_count=len(items),
        positive_count=len(positive),
        avg_change_pct=round(avg_change, 2),
        total_amount=round(total_amount, 2),
        positive_amount_pct=round(positive_amount / total_amount * 100, 2) if total_amount > 0 else None,
        main_net_inflow=round(inflow, 2),
        top_etfs=items[:12],
    )


def _select_candidates(directions: list[DiscoveryDirection]) -> list[DiscoveryEtfCandidate]:
    selected: list[DiscoveryEtfCandidate] = []
    used_codes: set[str] = set()
    for direction in directions:
        candidate = next((item for item in direction.top_etfs if item.code not in used_codes), None)
        if candidate is None:
            continue
        selected.append(candidate.model_copy(deep=True))
        used_codes.add(candidate.code)
        if len(selected) >= 3:
            break
    if len(selected) < 3:
        all_items = [item for direction in directions for item in direction.top_etfs]
        for item in sorted(all_items, key=lambda value: value.score, reverse=True):
            if item.code in used_codes:
                continue
            selected.append(item.model_copy(deep=True))
            used_codes.add(item.code)
            if len(selected) >= 3:
                break
    return selected[:3]


def _is_cross_border_theme(name: str) -> bool:
    normalized = name.upper()
    return any(keyword.upper() in normalized for keyword in CROSS_BORDER_KEYWORDS)


def _classify(name: str) -> tuple[str, str]:
    normalized = name.upper()
    for key, label, keywords in DIRECTION_RULES:
        if any(keyword.upper() in normalized for keyword in keywords):
            return key, label
    return "other_theme", "其他主题"


def _clamp(value: float) -> int:
    return max(0, min(100, round(value)))
