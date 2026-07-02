from __future__ import annotations

from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo
from typing import Iterable

from app.core.config import Settings
from app.domain.models import AiSummaryItem, MarketFlowResponse, TradePlan
from app.services.data_quality import build_data_quality_report
from app.services.risk import build_risk_report

CN_TZ = ZoneInfo("Asia/Shanghai")
SUMMARY_KINDS = ("opening_auction", "midday", "closing")
SUMMARY_WINDOWS: dict[str, tuple[time, time]] = {
    "opening_auction": (time(9, 25), time(9, 45)),
    "midday": (time(11, 30), time(12, 45)),
    "closing": (time(14, 50), time(15, 20)),
}
SUMMARY_TITLES = {
    "opening_auction": "早盘竞价/开盘情绪",
    "midday": "午间复盘",
    "closing": "尾盘/收盘总结",
}


def trading_date(now: datetime | None = None) -> str:
    current = (now or datetime.now(timezone.utc)).astimezone(CN_TZ)
    return current.date().isoformat()


def due_summary_kinds(now: datetime | None = None) -> list[str]:
    current = (now or datetime.now(timezone.utc)).astimezone(CN_TZ)
    if current.weekday() >= 5:
        return []
    current_time = current.time()
    return [kind for kind, (start, end) in SUMMARY_WINDOWS.items() if start <= current_time <= end]


def summary_windows_payload() -> list[dict[str, str]]:
    return [
        {
            "kind": kind,
            "title": SUMMARY_TITLES[kind],
            "start": start.strftime("%H:%M"),
            "end": end.strftime("%H:%M"),
        }
        for kind, (start, end) in SUMMARY_WINDOWS.items()
    ]


def summary_title(kind: str) -> str:
    return SUMMARY_TITLES.get(kind, kind)


def build_ai_context(
    settings: Settings,
    plans: list[TradePlan],
    market_flow: MarketFlowResponse | None,
    snapshots: dict,
) -> tuple[dict, datetime | None]:
    fixed_snapshots = [snapshots.get(plan.code) for plan in plans]
    data_times = [item.source_time for item in fixed_snapshots if item and item.source_time]
    source_data_time = max(data_times) if data_times else None
    risk = build_risk_report(plans)
    data_quality = build_data_quality_report(settings, snapshots)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_data_time": source_data_time.isoformat() if source_data_time else None,
        "tracked_etfs": settings.exposed_codes,
        "market_directions": [_direction_payload(item) for item in (market_flow.directions[:5] if market_flow else [])],
        "market_warnings": market_flow.warnings if market_flow else [],
        "fixed_pool": [_plan_payload(plan) for plan in plans],
        "risk_state": {
            "budget": risk.risk_budget_state,
            "high_risk_count": risk.high_risk_count,
            "items": [item.model_dump(mode="json") for item in risk.items],
        },
        "data_quality": {
            "overall_score": data_quality.overall_score,
            "blocked_codes": data_quality.blocked_codes,
            "warnings": data_quality.warnings,
        },
        "summary_focus": [
            "情绪强弱和是否一致",
            "主线/候选方向是否有资金留存",
            "量化候选ETF是否只适合等待、低吸、持有、止盈或回避",
            "溢价、破位、放量滞涨、数据质量风险",
            "下一时段只观察哪些条件，不给绝对买卖命令",
        ],
    }, source_data_time


def make_summary_item(
    kind: str,
    trading_date_value: str,
    model: str,
    summary: str,
    source_data_time: datetime | None,
    status: str = "ok",
    error: str | None = None,
    payload: dict | None = None,
) -> AiSummaryItem:
    return AiSummaryItem(
        kind=kind,
        title=summary_title(kind),
        trading_date=trading_date_value,
        generated_at=datetime.now(timezone.utc),
        source_data_time=source_data_time,
        model=model,
        status=status,
        summary=summary,
        error=error,
        payload=payload or {},
    )


def _direction_payload(item) -> dict:
    return {
        "direction_label": item.direction_label,
        "score": item.score,
        "state": item.state,
        "mainline_probability": item.mainline_probability,
        "trade_action": item.trade_action,
        "capital_status": item.capital_status,
        "avg_change_pct": item.avg_change_pct,
        "breadth_pct": item.breadth_pct,
        "main_net_inflow": item.main_net_inflow,
        "risk_flags": item.risk_flags[:5],
        "main_etfs": [f"{etf.code} {etf.name}" for etf in item.main_etfs[:2]],
        "linked_stocks": [f"{stock.code} {stock.name}" for stock in item.linked_stocks[:3]],
    }


def _plan_payload(plan: TradePlan) -> dict:
    return {
        "code": plan.code,
        "name": plan.name,
        "signal": plan.signal,
        "confidence": plan.confidence,
        "direction_score": plan.direction_score,
        "low_buy_score": plan.low_buy_score,
        "hold_score": plan.hold_score,
        "take_profit_score": plan.take_profit_score,
        "risk_score": plan.risk_score,
        "current_price": plan.current_price,
        "buy_zone": plan.buy_zone,
        "take_profit_plan": plan.take_profit_plan,
        "exit_plan": plan.exit_plan,
        "warnings": plan.warnings,
    }
