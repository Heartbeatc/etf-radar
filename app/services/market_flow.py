from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from math import log10
from statistics import mean
from typing import Any

from app.adapters.market_flow import EastmoneyMarketFlowClient, from_epoch, integer, num
from app.domain.models import (
    DiscoveryEtfCandidate,
    DiscoveryResponse,
    MarketBoardCandidate,
    MarketDirection,
    MarketFlowResponse,
    MarketStockCandidate,
)
from app.services.discovery import DIRECTION_RULES

EXCLUDED_BOARD_KEYWORDS = (
    "昨日", "ST股", "融资融券", "转债", "破净", "预亏", "亏损", "退市", "次新", "新股",
)
EXCLUDED_STOCK_KEYWORDS = ("ST", "退", "N", "C")
CROSS_BORDER_ETF_KEYWORDS = ("港股", "港股通", "恒生", "中概", "H股", "香港", "纳斯达克", "标普", "日经", "德国")
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
ADDITIONAL_DIRECTION_RULES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("innovative_drug", "创新药/医药", ("医药生物", "化学制药", "生物制品", "医疗器械", "医疗服务", "CXO", "CRO", "毛发医疗", "原料药", "仿制药")),
    ("gold_resources", "黄金/资源", ("贵金属", "黄金", "钨", "铜", "铝", "锂", "钴", "小金属", "稀有金属", "工业金属", "煤炭", "有色金属", "稀土")),
    ("ai_compute", "AI算力/通信/数字经济", ("光模块", "CPO", "数据中心", "PCB", "云计算", "算力", "服务器", "液冷", "通信设备", "软件开发")),
    ("semiconductor", "半导体/芯片", ("半导体", "芯片", "存储芯片", "光刻机", "集成电路", "先进封装")),
    ("robotics_highend", "机器人/高端制造", ("机床", "机器人", "减速器", "工业母机", "工程机械", "专用设备", "通用设备")),
    ("consumer", "消费", ("养殖", "肉鸡", "猪肉", "饲料", "食品", "白酒", "饮料", "旅游", "零售", "家电", "农业")),
    ("dividend_value", "红利/央企价值", ("红利股", "价值股", "高股息", "央企", "中特估", "大盘价值")),
    ("brokerage_finance", "券商/金融", ("证券", "券商", "银行", "保险", "多元金融", "互联金融")),
    ("new_energy", "新能源", ("电池", "锂电", "光伏", "储能", "风电", "新能源车", "充电桩")),
)

@dataclass
class DirectionHistoryStats:
    observations: int = 0
    days_count: int = 0
    top3_hits: int = 0
    candidate_hits: int = 0
    hot_hits: int = 0
    weakening_hits: int = 0
    avg_score: float = 0.0
    avg_residency: float = 0.0
    avg_retention: float = 0.0
    avg_intraday: float = 0.0



def build_board_candidates(rows: list[dict[str, Any]]) -> list[MarketBoardCandidate]:
    candidates: list[MarketBoardCandidate] = []
    for row in rows:
        name = str(row.get("f14") or "")
        code = str(row.get("f12") or "")
        if not code or not name or _is_excluded_board(name):
            continue
        direction_key, direction_label = classify_direction(name)
        score, state, evidence, risk_flags = _board_score(row)
        up_count = integer(row.get("f104"))
        down_count = integer(row.get("f105"))
        breadth = _breadth(up_count, down_count)
        candidates.append(
            MarketBoardCandidate(
                code=code,
                name=name,
                board_type=str(row.get("_board_type") or "unknown"),
                direction_key=direction_key,
                direction_label=direction_label,
                score=score,
                state=state,
                price=num(row.get("f2")),
                change_pct=num(row.get("f3")),
                amount=num(row.get("f6")),
                volume_ratio=num(row.get("f10")),
                turnover_pct=num(row.get("f8")),
                main_net_inflow=num(row.get("f62")),
                up_count=up_count,
                down_count=down_count,
                breadth_pct=breadth,
                leader_code=str(row.get("f140") or "") or None,
                leader_name=str(row.get("f128") or "") or None,
                leader_change_pct=num(row.get("f136")),
                evidence=evidence,
                risk_flags=risk_flags,
                source_time=from_epoch(row.get("f124")),
            )
        )
    candidates.sort(key=lambda item: item.score, reverse=True)
    return candidates


async def build_market_flow_report(
    client: EastmoneyMarketFlowClient,
    *,
    etf_report: DiscoveryResponse | None = None,
    max_directions: int = 8,
    board_member_samples: int = 14,
    history: list[MarketFlowResponse] | None = None,
) -> MarketFlowResponse:
    rows = await client.fetch_boards()
    boards = build_board_candidates(rows)
    stock_sample_count = await _attach_representative_stocks(client, boards, board_member_samples)
    directions = _directions_from_boards(boards, etf_report, history or [])
    warnings: list[str] = []
    if not boards:
        warnings.append("免费行情源未返回行业/概念板块资金数据，市场流向暂不可用")
    if directions and all(item.state != "confirmed_mainline" for item in directions[:3]):
        warnings.append("当前未确认主线；前排方向只是热点/候选，需要下一交易日承接和资金驻留验证")
    if directions:
        warnings.append("资金驻留/承接分为免费数据代理指标，证据强度低于 Level-2 或交易所逐笔数据")
    if directions and all(item.factor_scores.get("history_days", 0) < 3 for item in directions[:3]):
        warnings.append("前排方向缺少至少3个交易日的历史驻留样本，禁止判定为确认主线")
    if any(item.main_net_inflow is not None and item.main_net_inflow < 0 for item in directions[:2]):
        warnings.append("前排方向包含估算主力净流出，只能按候选观察，不能按确认主线处理")
    return MarketFlowResponse(
        generated_at=datetime.now(timezone.utc),
        source="eastmoney_board_flow_free",
        board_count=len(boards),
        stock_sample_count=stock_sample_count,
        directions=directions[:max_directions],
        warnings=warnings,
        assumptions=[
            "资金流向先从行业/概念板块识别，不从 ETF 名称倒推。",
            "强势个股只用于验证方向强度，不等于个股买入建议。",
            "确认主线需要至少3个交易日的历史驻留、方向内扩散、代表股承接和ETF载体确认。",
            "单日成交额、量比、涨幅只能证明异动强度，不能单独证明主力资金驻留。",
            "免费源适合研究预警，不适合作为交易所级执行依据。",
        ],
    )


async def _attach_representative_stocks(
    client: EastmoneyMarketFlowClient,
    boards: list[MarketBoardCandidate],
    board_member_samples: int,
) -> int:
    targets = _representative_board_targets(boards, board_member_samples)
    sample_count = 0
    semaphore = asyncio.Semaphore(4)

    async def fetch_and_score(board: MarketBoardCandidate) -> None:
        nonlocal sample_count
        try:
            async with semaphore:
                rows = await client.fetch_board_members(board.code)
            sample_count += len(rows)
            stock = _best_stock(board, rows)
            if stock is not None:
                board.representative_stock = stock
        except Exception as exc:
            board.risk_flags.append(f"成分股抓取失败：{str(exc)[:80]}")

    await asyncio.gather(*(fetch_and_score(board) for board in targets))
    return sample_count


def _representative_board_targets(boards: list[MarketBoardCandidate], limit: int) -> list[MarketBoardCandidate]:
    targets: list[MarketBoardCandidate] = []
    seen_codes: set[str] = set()
    by_direction: dict[str, list[MarketBoardCandidate]] = defaultdict(list)
    for board in boards:
        by_direction[board.direction_key].append(board)
    for direction_boards in by_direction.values():
        direction_boards.sort(key=lambda item: item.score, reverse=True)
    ranked_directions = sorted(
        by_direction.values(),
        key=lambda items: (items[0].score, sum(item.amount or 0 for item in items[:3])),
        reverse=True,
    )
    for direction_boards in ranked_directions:
        board = direction_boards[0]
        if board.code in seen_codes:
            continue
        targets.append(board)
        seen_codes.add(board.code)
        if len(targets) >= limit:
            return targets
    for board in boards:
        if board.code in seen_codes:
            continue
        targets.append(board)
        seen_codes.add(board.code)
        if len(targets) >= limit:
            break
    return targets


def _best_stock(board: MarketBoardCandidate, rows: list[dict[str, Any]]) -> MarketStockCandidate | None:
    candidates = [_stock_candidate(board, row) for row in rows]
    candidates = [item for item in candidates if item is not None]
    if not candidates:
        return _leader_stock(board)
    candidates.sort(key=lambda item: item.score, reverse=True)
    return candidates[0]


def _leader_stock(board: MarketBoardCandidate) -> MarketStockCandidate | None:
    if not board.leader_code or not board.leader_name:
        return None
    score = 55
    evidence = ["板块接口标记为领涨股"]
    if board.leader_change_pct is not None and board.leader_change_pct >= 9:
        score += 15
        evidence.append("领涨股接近涨停")
    return MarketStockCandidate(
        code=board.leader_code,
        name=board.leader_name,
        board_code=board.code,
        board_name=board.name,
        change_pct=board.leader_change_pct,
        score=_clamp(score),
        evidence=evidence,
        risk_flags=[],
        source_time=board.source_time,
    )


def _stock_candidate(board: MarketBoardCandidate, row: dict[str, Any]) -> MarketStockCandidate | None:
    name = str(row.get("f14") or "")
    code = str(row.get("f12") or "")
    price = num(row.get("f2"))
    amount = num(row.get("f6")) or 0.0
    if not code or not name or price is None or price <= 0 or amount < 20_000_000:
        return None
    score = 32.0
    evidence: list[str] = []
    risk_flags: list[str] = []
    change = num(row.get("f3")) or 0.0
    volume_ratio = num(row.get("f10"))
    turnover = num(row.get("f8"))
    inflow_pct = num(row.get("f184"))
    inflow = num(row.get("f62"))

    if change >= 9:
        score += 22
        evidence.append("个股接近涨停")
    elif change >= 5:
        score += 16
        evidence.append("个股涨幅较强")
    elif change >= 2:
        score += 9
    elif change < 0:
        score -= 12
        risk_flags.append("个股价格走弱")

    score += min(15.0, max(0.0, log10(max(amount, 1) / 50_000_000) * 6 + 4))
    if amount >= 500_000_000:
        evidence.append("个股成交额确认关注度")

    if volume_ratio is not None:
        if volume_ratio >= 2:
            score += 8
            evidence.append("个股量比显著放大")
        elif volume_ratio >= 1.2:
            score += 4
        elif volume_ratio < 0.7:
            score -= 4
            risk_flags.append("个股量比偏弱")

    if inflow_pct is not None:
        if inflow_pct >= 10:
            score += 14
            evidence.append("估算主力资金流入较强")
        elif inflow_pct >= 3:
            score += 8
        elif inflow_pct < -5:
            score -= 10
            risk_flags.append("估算主力资金为净流出")

    if turnover is not None:
        if 3 <= turnover <= 18:
            score += 5
        elif turnover > 30:
            score -= 6
            risk_flags.append("换手率过高，短线波动风险上升")

    if _is_excluded_stock(name):
        score -= 25
        risk_flags.append("新股/ST/异常简称，强股验证权重降低")

    return MarketStockCandidate(
        code=code,
        name=name,
        board_code=board.code,
        board_name=board.name,
        price=price,
        change_pct=change,
        amount=amount,
        volume_ratio=volume_ratio,
        turnover_pct=turnover,
        main_net_inflow=inflow,
        main_net_inflow_pct=inflow_pct,
        score=_clamp(score),
        evidence=evidence[:8],
        risk_flags=risk_flags[:8],
        source_time=from_epoch(row.get("f124")),
    )


def _directions_from_boards(
    boards: list[MarketBoardCandidate],
    etf_report: DiscoveryResponse | None,
    history: list[MarketFlowResponse],
) -> list[MarketDirection]:
    groups: dict[str, list[MarketBoardCandidate]] = defaultdict(list)
    for board in boards:
        groups[board.direction_key].append(board)
    etfs_by_direction = _etfs_by_direction(etf_report)
    history_by_direction = _history_by_direction(history)
    market_amount = sum(item.amount or 0 for item in boards)
    directions: list[MarketDirection] = []
    for key, items in groups.items():
        items.sort(key=lambda item: item.score, reverse=True)
        label = items[0].direction_label
        total_amount = sum(item.amount or 0 for item in items)
        inflow = sum(item.main_net_inflow or 0 for item in items)
        positive_items = [item for item in items if (item.change_pct or 0) > 0]
        avg_change = mean([item.change_pct or 0 for item in items]) if items else 0.0
        breadth_values = [item.breadth_pct for item in items if item.breadth_pct is not None]
        breadth = mean(breadth_values) if breadth_values else None
        linked_etfs = _score_direction_etfs(key, etfs_by_direction.get(key, []))
        main_etfs, backup_etf = _select_direction_etfs(key, linked_etfs)
        linked_stocks = _direction_stocks(items)
        representative = linked_stocks[0] if linked_stocks else _best_direction_stock(items)
        factor_scores, concentration_pct = _direction_factor_scores(
            items=items,
            total_amount=total_amount,
            market_amount=market_amount,
            inflow=inflow,
            avg_change=avg_change,
            breadth=breadth,
            linked_etfs=linked_etfs,
            linked_stocks=linked_stocks,
            history_stats=history_by_direction.get(key, DirectionHistoryStats()),
        )
        score = factor_scores["mainline_probability"]
        state = _quant_direction_state(factor_scores, inflow)
        evidence = _direction_evidence(items, breadth, inflow, linked_etfs)
        evidence.extend(_quant_evidence(factor_scores, concentration_pct, state))
        risk_flags = _direction_risks(items, breadth, inflow)
        risk_flags.extend(_quant_risks(factor_scores, state, linked_etfs))
        trade_action = _trade_action(state, factor_scores)
        directions.append(
            MarketDirection(
                direction_key=key,
                direction_label=label,
                score=_clamp(score),
                state=state,
                board_count=len(items),
                positive_board_count=len(positive_items),
                total_amount=round(total_amount, 2),
                main_net_inflow=round(inflow, 2),
                avg_change_pct=round(avg_change, 2),
                breadth_pct=round(breadth, 2) if breadth is not None else None,
                representative_stock=representative,
                linked_stocks=linked_stocks[:5],
                linked_etfs=linked_etfs[:5],
                main_etfs=main_etfs,
                backup_etf=backup_etf,
                top_boards=items[:4],
                capital_concentration_pct=round(concentration_pct, 2) if concentration_pct is not None else None,
                factor_scores=factor_scores,
                mainline_probability=factor_scores["mainline_probability"],
                residency_score=factor_scores["residency"],
                retention_score=factor_scores["retention"],
                etf_confirmation_score=factor_scores["etf_confirmation"],
                low_buy_readiness_score=factor_scores["low_buy_readiness"],
                capital_status=_capital_status(state),
                trade_action=trade_action,
                risk_watch=_risk_watch(items, linked_stocks, linked_etfs),
                evidence=evidence[:10],
                risk_flags=risk_flags[:10],
            )
        )
    directions.sort(key=lambda item: (item.score, item.factor_scores.get("intraday_strength", 0)), reverse=True)
    return directions


def _score_direction_etfs(direction_key: str, etfs: list[DiscoveryEtfCandidate]) -> list[DiscoveryEtfCandidate]:
    scored: list[DiscoveryEtfCandidate] = []
    for item in etfs:
        candidate = item.model_copy(deep=True)
        score = 22.0
        reasons: list[str] = []
        if candidate.direction_key == direction_key:
            score += 22
            reasons.append("ETF主题匹配当前资金方向")
        score += min(22.0, max(0.0, log10(max(candidate.amount or 1, 1) / 80_000_000) * 7 + 8))
        if (candidate.amount or 0) >= 300_000_000:
            reasons.append("ETF成交额足够，适合低吸执行")
        if candidate.entry_bias in {"watch_low_buy", "pullback_watch"}:
            score += 16
            reasons.append("ETF更接近低吸区，追高压力较低")
        elif candidate.entry_bias == "direction_hot_wait_pullback":
            score -= 8
            reasons.append("ETF短线偏热，可作方向载体但需等回落")
        elif candidate.entry_bias == "avoid_premium":
            score -= 18
            reasons.append("ETF溢价风险降低可交易性")
        premium = abs(candidate.premium_pct or 0.0)
        if premium <= 0.6:
            score += 9
            reasons.append("ETF溢折价处于可控区间")
        elif premium >= 1.5:
            score -= 12
        if candidate.volume_ratio is not None:
            if candidate.volume_ratio >= 1.4:
                score += 8
                reasons.append("ETF量能确认资金关注")
            elif candidate.volume_ratio < 0.75:
                score -= 6
        if candidate.main_net_inflow_pct is not None:
            if candidate.main_net_inflow_pct >= 3:
                score += 7
            elif candidate.main_net_inflow_pct <= -5:
                score -= 8
        if direction_key in A_SHARE_PREFERRED_DIRECTIONS:
            if _is_cross_border_etf(candidate.name):
                score -= 24
                reasons.append("港股/跨境载体降权，非港股方向不优先")
            else:
                score += 10
                reasons.append("A股场内载体优先")
        candidate.mapping_score = _clamp(score)
        candidate.mapping_reason = reasons[:6]
        scored.append(candidate)
    scored.sort(key=lambda item: (item.mapping_score or 0, item.score, item.amount or 0), reverse=True)
    return scored


def _select_direction_etfs(
    direction_key: str,
    linked_etfs: list[DiscoveryEtfCandidate],
) -> tuple[list[DiscoveryEtfCandidate], DiscoveryEtfCandidate | None]:
    ranked = list(linked_etfs)
    if direction_key in A_SHARE_PREFERRED_DIRECTIONS:
        domestic = [item for item in ranked if not _is_cross_border_etf(item.name)]
        cross_border = [item for item in ranked if _is_cross_border_etf(item.name)]
        if domestic:
            best_domestic = domestic[0].mapping_score or domestic[0].score
            strong_cross = [
                item
                for item in cross_border
                if (item.mapping_score or item.score) >= best_domestic + 15
            ]
            ranked = [*domestic, *strong_cross, *[item for item in cross_border if item not in strong_cross]]
    selected = [item.model_copy(deep=True) for item in ranked[:3]]
    for idx, item in enumerate(selected):
        item.rank = idx + 1
        item.role = "main" if idx < 2 else "backup"
    main = selected[:2]
    backup = selected[2] if len(selected) >= 3 else None
    return main, backup


def _is_cross_border_etf(name: str) -> bool:
    normalized = name.upper()
    return any(keyword.upper() in normalized for keyword in CROSS_BORDER_ETF_KEYWORDS)


def _direction_stocks(items: list[MarketBoardCandidate]) -> list[MarketStockCandidate]:
    by_code: dict[str, MarketStockCandidate] = {}
    for item in items:
        if item.representative_stock is None:
            continue
        stock = item.representative_stock.model_copy(deep=True)
        existing = by_code.get(stock.code)
        if existing is None or stock.score > existing.score:
            by_code[stock.code] = stock
    stocks = list(by_code.values())
    stocks.sort(key=lambda item: item.score, reverse=True)
    for idx, stock in enumerate(stocks):
        stock.verifier_role = "leader" if idx == 0 else "expansion"
    return stocks


def _history_by_direction(history: list[MarketFlowResponse]) -> dict[str, DirectionHistoryStats]:
    raw: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "observations": 0,
        "days": set(),
        "top3_hits": 0,
        "candidate_hits": 0,
        "hot_hits": 0,
        "weakening_hits": 0,
        "scores": [],
        "residency": [],
        "retention": [],
        "intraday": [],
    })
    for report in history[:240]:
        day = report.generated_at.date().isoformat()
        for rank, direction in enumerate(report.directions, start=1):
            bucket = raw[direction.direction_key]
            bucket["observations"] += 1
            bucket["days"].add(day)
            if rank <= 3:
                bucket["top3_hits"] += 1
            if direction.state in {"confirmed_mainline", "candidate"}:
                bucket["candidate_hits"] += 1
            if direction.state == "hot_today":
                bucket["hot_hits"] += 1
            if direction.state in {"weakening", "weak_direction"}:
                bucket["weakening_hits"] += 1
            bucket["scores"].append(direction.score)
            bucket["residency"].append(direction.residency_score)
            bucket["retention"].append(direction.retention_score)
            bucket["intraday"].append(direction.factor_scores.get("intraday_strength", direction.score))

    stats: dict[str, DirectionHistoryStats] = {}
    for key, bucket in raw.items():
        stats[key] = DirectionHistoryStats(
            observations=int(bucket["observations"]),
            days_count=len(bucket["days"]),
            top3_hits=int(bucket["top3_hits"]),
            candidate_hits=int(bucket["candidate_hits"]),
            hot_hits=int(bucket["hot_hits"]),
            weakening_hits=int(bucket["weakening_hits"]),
            avg_score=mean(bucket["scores"]) if bucket["scores"] else 0.0,
            avg_residency=mean(bucket["residency"]) if bucket["residency"] else 0.0,
            avg_retention=mean(bucket["retention"]) if bucket["retention"] else 0.0,
            avg_intraday=mean(bucket["intraday"]) if bucket["intraday"] else 0.0,
        )
    return stats


def _persistence_score(stats: DirectionHistoryStats) -> int:
    if stats.observations <= 0:
        return 25
    top3_rate = stats.top3_hits / max(stats.observations, 1)
    candidate_rate = stats.candidate_hits / max(stats.observations, 1)
    weakening_rate = stats.weakening_hits / max(stats.observations, 1)
    score = (
        24
        + min(30, stats.days_count * 9)
        + min(16, stats.observations * 1.5)
        + top3_rate * 18
        + candidate_rate * 16
        + min(10, stats.avg_retention * 0.12)
        + min(10, stats.avg_residency * 0.10)
        - weakening_rate * 22
    )
    if stats.days_count < 2:
        score = min(score, 45)
    elif stats.days_count < 3:
        score = min(score, 58)
    return _clamp(score)


def _impulse_risk(
    *,
    volume_expansion: int,
    intraday_strength: int,
    flow_proxy: int,
    breadth_score: int,
    leadership: int,
    etf_confirmation: int,
    retention: int,
    history_days: int,
) -> int:
    risk = 22.0
    if history_days < 2:
        risk += 24
    elif history_days < 3:
        risk += 12
    if volume_expansion >= 75 and intraday_strength >= 68:
        risk += 16
    if intraday_strength >= 70 and flow_proxy < 55:
        risk += 14
    if breadth_score < 48:
        risk += 10
    if leadership < 55:
        risk += 10
    if retention < 55:
        risk += 10
    if etf_confirmation < 50:
        risk += 6
    if flow_proxy >= 62 and breadth_score >= 55 and leadership >= 62:
        risk -= 10
    return _clamp(risk)


def _evidence_quality(
    *,
    breadth: float | None,
    linked_etfs: list[DiscoveryEtfCandidate],
    linked_stocks: list[MarketStockCandidate],
    history_days: int,
) -> int:
    score = 28.0
    if breadth is not None:
        score += 14
    if linked_stocks:
        score += 14
    if linked_etfs:
        score += 12
    if len(linked_etfs) >= 2:
        score += 8
    score += min(24, history_days * 8)
    return _clamp(score)


def _direction_factor_scores(
    *,
    items: list[MarketBoardCandidate],
    total_amount: float,
    market_amount: float,
    inflow: float,
    avg_change: float,
    breadth: float | None,
    linked_etfs: list[DiscoveryEtfCandidate],
    linked_stocks: list[MarketStockCandidate],
    history_stats: DirectionHistoryStats,
) -> tuple[dict[str, int], float | None]:
    concentration_pct = total_amount / market_amount * 100 if market_amount > 0 else None
    concentration_bonus = (concentration_pct or 0.0) * 3.2
    capital_weight = _clamp(34 + concentration_bonus + log10(max(total_amount, 1) / 1_000_000_000) * 12)

    volume_ratios = [item.volume_ratio for item in items[:6] if item.volume_ratio is not None]
    avg_volume_ratio = mean(volume_ratios) if volume_ratios else 1.0
    volume_expansion = _clamp(46 + (avg_volume_ratio - 1) * 28)

    flow_ratio = inflow / total_amount if total_amount > 0 else 0.0
    flow_proxy = _clamp(50 + flow_ratio * 650 + (8 if inflow > 1_000_000_000 else 0) - (8 if inflow < -1_000_000_000 else 0))

    top_change = mean([item.change_pct or 0.0 for item in items[: min(4, len(items))]]) if items else 0.0
    relative_strength = _clamp(44 + avg_change * 7.5 + top_change * 3.0)

    breadth_score = _clamp(35 + ((breadth if breadth is not None else 50) - 50) * 1.15)
    strong_boards = len([item for item in items if item.score >= 70])
    expansion = _clamp(38 + strong_boards * 7 + min(len(items), 8) * 2 + (breadth_score - 50) * 0.35)

    stock_score = linked_stocks[0].score if linked_stocks else 45
    board_score = mean([item.score for item in items[: min(5, len(items))]]) if items else 45
    leadership = _clamp(stock_score * 0.6 + board_score * 0.4)

    etf_confirmation = _etf_confirmation_score(linked_etfs)
    intraday_strength = _clamp(
        capital_weight * 0.20
        + volume_expansion * 0.16
        + flow_proxy * 0.18
        + relative_strength * 0.18
        + breadth_score * 0.12
        + expansion * 0.08
        + leadership * 0.08
    )

    residency = _clamp(
        capital_weight * 0.24
        + flow_proxy * 0.20
        + relative_strength * 0.16
        + expansion * 0.18
        + etf_confirmation * 0.12
        + leadership * 0.10
    )
    # Free data has no identity for a fund and no guaranteed multi-day order-flow history.
    # Keep residency conservative until persisted multi-day snapshots or paid L2 are available.
    if strong_boards >= 3 and inflow > 0 and (breadth is None or breadth >= 55):
        residency += 5
    if intraday_strength < 70:
        residency = min(residency, 62)
    else:
        residency = min(residency, 74)

    retention = _clamp(breadth_score * 0.28 + leadership * 0.24 + flow_proxy * 0.20 + volume_expansion * 0.14 + etf_confirmation * 0.14)
    persistence = _persistence_score(history_stats)
    impulse_risk = _impulse_risk(
        volume_expansion=volume_expansion,
        intraday_strength=intraday_strength,
        flow_proxy=flow_proxy,
        breadth_score=breadth_score,
        leadership=leadership,
        etf_confirmation=etf_confirmation,
        retention=retention,
        history_days=history_stats.days_count,
    )
    evidence_quality = _evidence_quality(
        breadth=breadth,
        linked_etfs=linked_etfs,
        linked_stocks=linked_stocks,
        history_days=history_stats.days_count,
    )
    low_buy_readiness = _low_buy_readiness(linked_etfs, relative_strength, breadth_score, flow_proxy)
    raw_probability = _clamp(
        residency * 0.24
        + retention * 0.20
        + intraday_strength * 0.16
        + etf_confirmation * 0.08
        + persistence * 0.24
        + evidence_quality * 0.08
    )
    uncapped_probability = _clamp(raw_probability - max(0, impulse_risk - 45) * 0.40)
    mainline_probability, evidence_cap = _apply_probability_evidence_cap(
        probability=uncapped_probability,
        history_days=history_stats.days_count,
        residency=_clamp(residency),
        retention=retention,
        flow_proxy=flow_proxy,
        breadth_score=breadth_score,
        evidence_quality=evidence_quality,
        linked_etfs=linked_etfs,
        linked_stocks=linked_stocks,
        impulse_risk=impulse_risk,
        intraday_strength=intraday_strength,
        low_buy_readiness=low_buy_readiness,
    )

    return {
        "capital_weight": capital_weight,
        "volume_expansion": volume_expansion,
        "flow_proxy": flow_proxy,
        "relative_strength": relative_strength,
        "breadth": breadth_score,
        "expansion": expansion,
        "leadership": leadership,
        "etf_confirmation": etf_confirmation,
        "intraday_strength": intraday_strength,
        "residency": _clamp(residency),
        "retention": retention,
        "persistence": persistence,
        "history_days": history_stats.days_count,
        "history_observations": history_stats.observations,
        "impulse_risk": impulse_risk,
        "evidence_quality": evidence_quality,
        "raw_mainline_probability": raw_probability,
        "uncapped_mainline_probability": uncapped_probability,
        "evidence_cap": evidence_cap,
        "low_buy_readiness": low_buy_readiness,
        "mainline_probability": mainline_probability,
    }, concentration_pct


def _etf_confirmation_score(etfs: list[DiscoveryEtfCandidate]) -> int:
    if not etfs:
        return 30
    top = etfs[0]
    score = 38 + (top.mapping_score or top.score) * 0.42
    if len(etfs) >= 2:
        score += 8
    if any(item.entry_bias in {"watch_low_buy", "pullback_watch"} for item in etfs[:2]):
        score += 7
    if any(item.entry_bias == "avoid_premium" for item in etfs[:2]):
        score -= 10
    return _clamp(score)


def _low_buy_readiness(etfs: list[DiscoveryEtfCandidate], relative_strength: int, breadth_score: int, flow_proxy: int) -> int:
    if not etfs:
        return 35
    entry_scores = []
    for item in etfs[:3]:
        if item.entry_bias == "pullback_watch":
            entry_scores.append(78)
        elif item.entry_bias == "watch_low_buy":
            entry_scores.append(70)
        elif item.entry_bias == "direction_hot_wait_pullback":
            entry_scores.append(42)
        elif item.entry_bias == "avoid_premium":
            entry_scores.append(25)
        else:
            entry_scores.append(50)
    entry = max(entry_scores) if entry_scores else 45
    return _clamp(entry * 0.44 + flow_proxy * 0.22 + breadth_score * 0.18 + min(relative_strength, 70) * 0.16)


def _apply_probability_evidence_cap(
    *,
    probability: int,
    history_days: int,
    residency: int,
    retention: int,
    flow_proxy: int,
    breadth_score: int,
    evidence_quality: int,
    linked_etfs: list[DiscoveryEtfCandidate],
    linked_stocks: list[MarketStockCandidate],
    impulse_risk: int,
    intraday_strength: int,
    low_buy_readiness: int,
) -> tuple[int, int]:
    cap = 100
    if history_days < 2:
        cap = min(cap, 52)
    elif history_days < 3:
        cap = min(cap, 66)
    if residency < 55:
        cap = min(cap, 58)
    elif residency < 62:
        cap = min(cap, 68)
    if retention < 55:
        cap = min(cap, 58)
    elif retention < 62:
        cap = min(cap, 68)
    if flow_proxy < 45:
        cap = min(cap, 55)
    if breadth_score < 48:
        cap = min(cap, 58)
    if evidence_quality < 55:
        cap = min(cap, 60)
    if not linked_etfs:
        cap = min(cap, 62)
    if not linked_stocks:
        cap = min(cap, 66)
    if impulse_risk >= 70:
        cap = min(cap, 50)
    elif impulse_risk >= 60:
        cap = min(cap, 58)
    elif impulse_risk >= 50:
        cap = min(cap, 68)
    if intraday_strength >= 76 and low_buy_readiness < 45:
        cap = min(cap, 55)
    return min(probability, cap), cap


def _quant_direction_state(factors: dict[str, int], inflow: float) -> str:
    intraday = factors["intraday_strength"]
    residency = factors["residency"]
    retention = factors["retention"]
    persistence = factors.get("persistence", 0)
    history_days = factors.get("history_days", 0)
    impulse_risk = factors.get("impulse_risk", 100)
    low_buy = factors["low_buy_readiness"]
    probability = factors["mainline_probability"]
    breadth = factors["breadth"]
    if inflow < 0 and breadth < 46 and retention < 52:
        return "weakening"
    if intraday >= 76 and low_buy < 45:
        return "overheated"
    if (
        history_days >= 3
        and probability >= 78
        and residency >= 68
        and retention >= 66
        and persistence >= 68
        and impulse_risk <= 45
    ):
        return "confirmed_mainline"
    if probability >= 64 and retention >= 58 and persistence >= 50 and impulse_risk <= 62:
        return "candidate"
    if intraday >= 70:
        return "hot_today"
    if intraday >= 56:
        return "watch_direction"
    return "weak_direction"


def _capital_status(state: str) -> str:
    return {
        "confirmed_mainline": "资金驻留已确认",
        "candidate": "资金驻留候选",
        "hot_today": "今日资金集中，等待次日承接",
        "overheated": "资金集中但短线过热",
        "weakening": "资金承接弱化",
        "watch_direction": "有资金迹象但证据不足",
        "weak_direction": "资金重心不明显",
    }.get(state, "未知")


def _trade_action(state: str, factors: dict[str, int]) -> str:
    low_buy = factors["low_buy_readiness"]
    if state == "confirmed_mainline" and low_buy >= 65:
        return "low_buy_allowed"
    if state in {"confirmed_mainline", "candidate"} and low_buy >= 58:
        return "wait_pullback_low_buy"
    if state == "hot_today":
        return "observe_next_day_retention"
    if state == "overheated":
        return "do_not_chase_wait_pullback"
    if state == "weakening":
        return "avoid_or_reduce"
    return "wait"


def _quant_evidence(factors: dict[str, int], concentration_pct: float | None, state: str) -> list[str]:
    evidence: list[str] = []
    if concentration_pct is not None and concentration_pct >= 8:
        evidence.append("全市场板块资金集中度较高")
    if factors["residency"] >= 65:
        evidence.append("资金驻留代理分较强，仍需多日确认")
    if factors["retention"] >= 65:
        evidence.append("资金承接代理分较强")
    if factors.get("persistence", 0) >= 65:
        evidence.append("历史方向驻留样本通过初步验证")
    elif factors.get("history_days", 0) < 3:
        evidence.append("历史驻留样本不足3个交易日，不能确认主线")
    if factors["etf_confirmation"] >= 65:
        evidence.append("ETF载体对方向形成确认")
    if state == "hot_today":
        evidence.append("先判定为当日热点，确认主线前需要次日承接")
    return evidence


def _quant_risks(factors: dict[str, int], state: str, etfs: list[DiscoveryEtfCandidate]) -> list[str]:
    risks: list[str] = []
    if state == "overheated":
        risks.append("方向偏热但低吸条件不足，避免追高")
    if factors.get("history_days", 0) < 3:
        risks.append("缺少3个交易日以上方向驻留样本")
    if factors.get("impulse_risk", 0) >= 60:
        risks.append("一日脉冲/热点噪声风险较高，不能按主线处理")
    if factors.get("evidence_cap", 100) < factors.get("uncapped_mainline_probability", factors.get("mainline_probability", 0)):
        risks.append("证据闸门已压低主线概率，当前只能按降级信号处理")
    if factors["residency"] < 58 and factors["intraday_strength"] >= 70:
        risks.append("单日强度不足以证明资金驻留")
    if factors["flow_proxy"] < 45:
        risks.append("资金流代理分偏弱或为负")
    if any(item.entry_bias == "avoid_premium" for item in etfs[:2]):
        risks.append("一个或多个ETF载体存在溢价风险")
    return risks


def _risk_watch(
    items: list[MarketBoardCandidate],
    stocks: list[MarketStockCandidate],
    etfs: list[DiscoveryEtfCandidate],
) -> list[str]:
    watches: list[str] = []
    for stock in stocks[:3]:
        watches.append(f"{stock.name}({stock.code}) 跌破趋势或放量长上影")
    for board in items[:2]:
        watches.append(f"{board.name} 板块成交额跌出前排")
    for etf in etfs[:2]:
        watches.append(f"{etf.name}({etf.code}) 放量跌破VWAP/MA10")
    return watches[:8]


def _etfs_by_direction(etf_report: DiscoveryResponse | None) -> dict[str, list[DiscoveryEtfCandidate]]:
    if etf_report is None:
        return {}
    result: dict[str, list[DiscoveryEtfCandidate]] = {}
    for direction in etf_report.directions:
        result[direction.direction_key] = direction.top_etfs[:10]
    return result


def _best_direction_stock(items: list[MarketBoardCandidate]) -> MarketStockCandidate | None:
    stocks = [item.representative_stock for item in items if item.representative_stock is not None]
    if not stocks:
        return None
    stocks.sort(key=lambda item: item.score, reverse=True)
    return stocks[0]


def _direction_evidence(
    items: list[MarketBoardCandidate],
    breadth: float | None,
    inflow: float,
    etfs: list[DiscoveryEtfCandidate],
) -> list[str]:
    evidence: list[str] = []
    if len(items) >= 2:
        evidence.append("多个相关板块共同确认方向")
    if breadth is not None and breadth >= 60:
        evidence.append("板块内部涨跌广度较好")
    if inflow > 0:
        evidence.append("板块层面估算主力资金为净流入")
    if sum(item.amount or 0 for item in items[:3]) >= 5_000_000_000:
        evidence.append("前排板块成交容量足够")
    if etfs:
        evidence.append("该方向存在可交易ETF载体")
    return evidence[:8]


def _direction_risks(items: list[MarketBoardCandidate], breadth: float | None, inflow: float) -> list[str]:
    risks: list[str] = []
    if inflow < 0:
        risks.append("板块层面估算主力资金为净流出")
    if breadth is not None and breadth < 50:
        risks.append("板块内部广度偏弱，可能只是少数标的拉升")
    if any((item.change_pct or 0) >= 7 for item in items[:3]):
        risks.append("前排板块短线偏热，避免追高介入")
    return risks[:8]


def _board_score(row: dict[str, Any]) -> tuple[int, str, list[str], list[str]]:
    score = 35.0
    evidence: list[str] = []
    risk_flags: list[str] = []
    change = num(row.get("f3")) or 0.0
    amount = num(row.get("f6")) or 0.0
    volume_ratio = num(row.get("f10"))
    inflow = num(row.get("f62")) or 0.0
    up_count = integer(row.get("f104"))
    down_count = integer(row.get("f105"))
    breadth = _breadth(up_count, down_count)
    leader_change = num(row.get("f136"))

    if change >= 5:
        score += 22
        evidence.append("板块涨幅领先")
    elif change >= 2:
        score += 15
        evidence.append("板块涨幅为正")
    elif change >= 0:
        score += 6
    else:
        score += max(-14.0, change * 3.0)
        risk_flags.append("板块价格走弱")

    score += min(18.0, max(0.0, log10(max(amount, 1) / 100_000_000) * 7 + 6))
    if amount >= 3_000_000_000:
        evidence.append("板块成交额具备容量")

    if volume_ratio is not None:
        if volume_ratio >= 1.5:
            score += 8
            evidence.append("板块量比确认关注度")
        elif volume_ratio >= 1.1:
            score += 4
        elif volume_ratio < 0.75:
            score -= 5
            risk_flags.append("板块量比偏弱")

    if inflow > 1_000_000_000:
        score += 13
        evidence.append("估算主力资金流入较强")
    elif inflow > 100_000_000:
        score += 8
        evidence.append("估算主力资金为净流入")
    elif inflow < -1_000_000_000:
        score -= 12
        risk_flags.append("估算主力资金明显净流出")
    elif inflow < -100_000_000:
        score -= 6

    if breadth is not None:
        if breadth >= 75:
            score += 12
            evidence.append("板块内部涨跌广度充分")
        elif breadth >= 60:
            score += 7
        elif breadth < 45:
            score -= 8
            risk_flags.append("板块内部涨跌广度偏弱")

    if leader_change is not None and leader_change >= 9:
        score += 4
        evidence.append("领涨股接近涨停")

    clamped = _clamp(score)
    return clamped, _board_state(clamped), evidence[:8], risk_flags[:8]


def classify_direction(name: str) -> tuple[str, str]:
    normalized = name.upper()
    for key, label, keywords in ADDITIONAL_DIRECTION_RULES + DIRECTION_RULES:
        if any(keyword.upper() in normalized for keyword in keywords):
            return key, label
    return "other_theme", "其他主题"


def _breadth(up_count: int | None, down_count: int | None) -> float | None:
    if up_count is None or down_count is None:
        return None
    total = up_count + down_count
    if total <= 0:
        return None
    return round(up_count / total * 100, 2)


def _board_state(score: int) -> str:
    if score >= 82:
        return "hot_board"
    if score >= 70:
        return "strong_board"
    if score >= 58:
        return "watch_board"
    return "weak_board"


def _direction_state(score: float, breadth: float | None, inflow: float) -> str:
    if score >= 80 and (breadth is None or breadth >= 55) and inflow > 0:
        return "mainline_candidate"
    if score >= 70:
        return "strong_direction"
    if score >= 58:
        return "watch_direction"
    return "weak_direction"


def _is_excluded_board(name: str) -> bool:
    normalized = name.upper()
    return any(keyword.upper() in normalized for keyword in EXCLUDED_BOARD_KEYWORDS)


def _is_excluded_stock(name: str) -> bool:
    normalized = name.upper()
    if normalized.startswith(("N", "C")):
        return True
    return any(keyword.upper() in normalized for keyword in EXCLUDED_STOCK_KEYWORDS[:2])


def _clamp(value: float) -> int:
    return max(0, min(100, round(value)))
