from __future__ import annotations

import json
from dataclasses import dataclass
from time import monotonic

import httpx

from app.core.config import Settings
from app.domain.models import TradePlan


@dataclass
class _CachedSummary:
    fingerprint: str
    summary: str
    updated_at: float


class AIAnalyst:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._cache: dict[str, _CachedSummary] = {}

    async def explain(self, plans: list[TradePlan]) -> dict[str, str]:
        if not self.settings.deepseek_api_key:
            return {plan.code: _fallback_summary(plan) for plan in plans}

        now = monotonic()
        result: dict[str, str] = {}
        pending: list[TradePlan] = []
        pending_fingerprints: dict[str, str] = {}

        for plan in plans:
            fingerprint = _fingerprint(plan)
            cached = self._cache.get(plan.code)
            cache_alive = cached is not None and now - cached.updated_at < self.settings.deepseek_cache_seconds
            if cached and cached.fingerprint == fingerprint and cache_alive:
                result[plan.code] = cached.summary
                continue
            pending.append(plan)
            pending_fingerprints[plan.code] = fingerprint

        if pending:
            summaries = await self._request_summaries(pending)
            for plan in pending:
                summary = summaries.get(plan.code) or _fallback_summary(plan)
                self._cache[plan.code] = _CachedSummary(
                    fingerprint=pending_fingerprints[plan.code],
                    summary=summary,
                    updated_at=now,
                )
                result[plan.code] = summary

        return result

    async def summarize_market(self, kind: str, context: dict) -> str:
        if not self.settings.deepseek_api_key:
            return _fallback_market_summary(kind, context)
        payload = {
            "model": self.settings.deepseek_model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是A股场内ETF交易辅助系统的风控型分析员。"
                        "只基于输入数据做盘面总结，不承诺收益，不给绝对买卖命令。"
                        "输出中文，结构清晰，控制在220字以内。必须包含：市场情绪、主线/候选方向、量化候选ETF动作倾向、风险、下一步观察。"
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps({"summary_kind": kind, "context": context}, ensure_ascii=False),
                },
            ],
            "temperature": 0.1,
            "max_tokens": 420,
        }
        endpoint = _chat_endpoint(self.settings.deepseek_base_url)
        try:
            async with httpx.AsyncClient(timeout=self.settings.deepseek_timeout_seconds) as client:
                response = await client.post(
                    endpoint,
                    headers={"Authorization": f"Bearer {self.settings.deepseek_api_key}"},
                    json=payload,
                )
                response.raise_for_status()
                return str(response.json()["choices"][0]["message"]["content"]).strip()
        except Exception:
            return _fallback_market_summary(kind, context)

    async def _request_summaries(self, plans: list[TradePlan]) -> dict[str, str]:
        payload = {
            "model": self.settings.deepseek_model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You explain ETF signal data for a decision-support API. "
                        "Do not promise returns. Do not give absolute buy/sell commands. "
                        "Return JSON where keys are ETF codes and values are concise Chinese summaries under 40 chars."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        [
                            {
                                "code": p.code,
                                "name": p.name,
                                "signal": p.signal,
                                "direction_score": p.direction_score,
                                "low_buy_score": p.low_buy_score,
                                "hold_score": p.hold_score,
                                "take_profit_score": p.take_profit_score,
                                "risk_score": p.risk_score,
                                "current_price": p.current_price,
                                "buy_zone": p.buy_zone,
                                "take_profit_plan": p.take_profit_plan,
                                "exit_plan": p.exit_plan,
                                "evidence": p.evidence,
                                "warnings": p.warnings,
                            }
                            for p in plans
                        ],
                        ensure_ascii=False,
                    ),
                },
            ],
            "temperature": 0.1,
            "max_tokens": 180,
            "response_format": {"type": "json_object"},
        }
        endpoint = _chat_endpoint(self.settings.deepseek_base_url)
        try:
            async with httpx.AsyncClient(timeout=self.settings.deepseek_timeout_seconds) as client:
                response = await client.post(
                    endpoint,
                    headers={"Authorization": f"Bearer {self.settings.deepseek_api_key}"},
                    json=payload,
                )
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
                parsed = json.loads(content)
                return {str(key): str(value) for key, value in parsed.items()}
        except Exception:
            return {plan.code: _fallback_summary(plan) for plan in plans}


def _chat_endpoint(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/v1"):
        return f"{base}/chat/completions"
    return f"{base}/chat/completions"


def _fingerprint(plan: TradePlan) -> str:
    payload = {
        "code": plan.code,
        "signal": plan.signal,
        "direction": _bucket(plan.direction_score),
        "low_buy": _bucket(plan.low_buy_score),
        "hold": _bucket(plan.hold_score),
        "take_profit": _bucket(plan.take_profit_score),
        "risk": _bucket(plan.risk_score),
        "tp_action": _dict_value(plan.take_profit_plan, "action"),
        "warnings": plan.warnings,
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _dict_value(value: object, key: str) -> object:
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)


def _bucket(score: int) -> int:
    return score // 10


def _fallback_market_summary(kind: str, context: dict) -> str:
    titles = {
        "opening_auction": "早盘竞价/开盘情绪",
        "midday": "午间复盘",
        "closing": "尾盘/收盘总结",
    }
    directions = context.get("market_directions") or []
    plans = context.get("fixed_pool") or []
    top = directions[0] if directions else {}
    strongest = top.get("direction_label") or "暂无明确方向"
    top_state = top.get("state") or "观察"
    plan_text = "；".join(
        f"{item.get('code')} {item.get('signal')} 低吸{item.get('low_buy_score')} 风险{item.get('risk_score')}"
        for item in plans[:3]
    ) or "量化候选暂无有效信号"
    return f"{titles.get(kind, kind)}：市场最强方向为{strongest}，状态{top_state}。量化候选：{plan_text}。仅按规则观察低吸、止盈和防守线，不追高。"


def _fallback_summary(plan: TradePlan) -> str:
    if plan.signal in {"low_buy_zone", "watch_low_buy"}:
        return f"{plan.name}可观察低吸，但必须分批并控制溢价。"
    if plan.signal in {"strong_take_profit", "partial_take_profit"}:
        return f"{plan.name}止盈风险升高，优先保护已有利润。"
    if plan.signal == "keep_holding":
        return f"{plan.name}持有条件仍在，重点盯10日线。"
    if plan.signal == "exit_first":
        return f"{plan.name}趋势或风险条件转弱，离场优先。"
    return f"{plan.name}暂不主动交易，等待更清晰位置。"
