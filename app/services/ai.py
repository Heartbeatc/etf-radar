from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from time import monotonic

import httpx

from app.core.config import Settings
from app.domain.models import AiTradeRiskReview, TradePlan


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
                        "你是A股量化系统的方向研究员。"
                        "只基于输入数据做方向探索，不承诺收益，不给绝对买卖命令。"
                        "输出中文，控制在260字以内。必须包含：最强方向、主力是否仍在、当前阶段、下一时段可能流向、反证/风险、操作建议只允许写观察/等待/小仓验证/防守。"
                        "必须区分确认主线、候选方向、单日脉冲和退潮方向；不要把成交额大直接等同主线。"
                        "当summary_kind为direction_shift时，必须优先判断：方向是否真的切换、触发原因、是真切换还是脉冲、下一步等什么确认。"
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

    async def review_trade_opportunity(self, event: dict) -> AiTradeRiskReview:
        if not self.settings.deepseek_api_key:
            return _fallback_trade_review(
                event,
                self.settings.deepseek_model,
                status="skipped",
                source="rules_fallback",
                error="DeepSeek API key is not configured",
            )
        payload = {
            "model": self.settings.deepseek_model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是A股量化系统的交易风控复核员，只基于输入的规则信号做反方风险预判。"
                        "规则引擎已经先判断出买入或卖出机会；你不能创造新的标的，不能承诺收益，"
                        "不能输出绝对化命令。必须优先识别：资金撤退、追高、破位、数据不足、方向退潮。"
                        "返回严格JSON，字段：risk_level(low/medium/high), conclusion, risk_points, invalidation, "
                        "suggested_next_check, ai_should_block。conclusion不超过90个中文字符；risk_points和invalidation各不超过3条。"
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps({"trade_opportunity": event}, ensure_ascii=False),
                },
            ],
            "temperature": 0.05,
            "max_tokens": 360,
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
                return _trade_review_from_payload(event, parsed, self.settings.deepseek_model)
        except Exception as exc:
            return _fallback_trade_review(
                event,
                self.settings.deepseek_model,
                status="error",
                source="rules_fallback",
                error=str(exc)[:300],
            )


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


def _trade_review_from_payload(event: dict, parsed: dict, model: str) -> AiTradeRiskReview:
    return AiTradeRiskReview(
        review_key=str(event.get("review_key", "")),
        code=str(event.get("code", "")),
        name=str(event.get("name", "")),
        side=str(event.get("side", "")),
        action=str(event.get("action", "")),
        trading_date=str(event.get("trading_date", "")),
        generated_at=datetime.now(timezone.utc),
        model=model,
        status="ok",
        source="deepseek",
        risk_level=_risk_level(parsed.get("risk_level")),
        conclusion=_short_text(parsed.get("conclusion"), 120) or "AI复核未给出明确结论，继续以规则引擎为准。",
        risk_points=_text_list(parsed.get("risk_points"), limit=3),
        invalidation=_text_list(parsed.get("invalidation"), limit=3),
        suggested_next_check=_short_text(parsed.get("suggested_next_check"), 80),
        ai_should_block=bool(parsed.get("ai_should_block")),
        payload={"event": event, "raw": parsed},
    )


def _fallback_trade_review(
    event: dict,
    model: str,
    status: str = "ok",
    source: str = "rules_fallback",
    error: str | None = None,
) -> AiTradeRiskReview:
    side = str(event.get("side", "")).upper()
    action = str(event.get("action", ""))
    risk_flags = _text_list(event.get("risk_flags"), limit=3)
    if side == "BUY":
        conclusion = "规则买点出现，但只能小仓试错；资金转弱或跌破防守价必须撤退。"
        risk_points = risk_flags or ["买点依赖资金承接延续", "价格进入低吸区不等于趋势确认"]
        invalidation = _text_list(event.get("invalidation"), limit=3) or ["主力净流入转负", "跌破防守价", "方向跌出前排"]
        next_check = "复核资金承接和低吸区下沿"
        risk_level = "medium"
    elif side == "SELL":
        conclusion = "规则卖出/减仓信号出现，优先保护本金和利润，不等待AI反向确认。"
        risk_points = risk_flags or ["持仓风险已经抬升", "趋势或止盈条件触发"]
        invalidation = _text_list(event.get("invalidation"), limit=3) or ["风险分继续升高", "跌破有效离场价"]
        next_check = "复核防守价和风险分"
        risk_level = "high" if action in {"SELL_ALL", "REDUCE_OR_HOLD_TIGHT"} else "medium"
    else:
        conclusion = "未识别为买入或卖出机会，不调用AI交易复核。"
        risk_points = risk_flags
        invalidation = _text_list(event.get("invalidation"), limit=3)
        next_check = "等待规则信号"
        risk_level = "unknown"
    return AiTradeRiskReview(
        review_key=str(event.get("review_key", "")),
        code=str(event.get("code", "")),
        name=str(event.get("name", "")),
        side=side,
        action=action,
        trading_date=str(event.get("trading_date", "")),
        generated_at=datetime.now(timezone.utc),
        model=model,
        status=status,
        source=source,
        risk_level=risk_level,
        conclusion=conclusion,
        risk_points=risk_points,
        invalidation=invalidation,
        suggested_next_check=next_check,
        ai_should_block=False,
        error=error,
        payload={"event": event},
    )


def _risk_level(value: object) -> str:
    text = str(value or "unknown").strip().lower()
    return text if text in {"low", "medium", "high", "unknown"} else "unknown"


def _text_list(value: object, limit: int) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        items = value
    else:
        items = [value]
    result: list[str] = []
    for item in items:
        text = _short_text(item, 90)
        if text:
            result.append(text)
        if len(result) >= limit:
            break
    return result


def _short_text(value: object, limit: int) -> str:
    text = str(value or "").strip().replace("\n", " ")
    return text[:limit]


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
        "opening_auction": "早盘方向探索",
        "midday": "午盘方向复盘",
        "closing": "晚盘方向复盘",
        "direction_shift": "方向突变复核",
    }
    directions = context.get("market_directions") or []
    plans = context.get("fixed_pool") or []
    top = directions[0] if directions else {}
    strongest = top.get("direction_label") or "暂无明确方向"
    top_state = top.get("state") or "观察"
    direction_text = "；".join(
        f"{item.get('direction_label')} 状态{item.get('state')} 主线{item.get('mainline_probability')} 驻留{item.get('residency_score')} 承接{item.get('retention_score')}"
        for item in directions[:3]
    ) or "暂无明确方向"
    if kind == "direction_shift":
        event = context.get("direction_shift_event") or {}
        reasons = "、".join(event.get("reasons") or []) or "方向结构出现变化"
        previous = (event.get("previous") or {}).get("direction_label") or "上一方向"
        current = (event.get("current") or {}).get("direction_label") or strongest
        return f"方向突变复核：{previous}切到{current}，触发原因：{reasons}。当前仍按{top_state}处理，先看资金驻留和龙头/二龙承接，不把一次脉冲直接当主线。"
    return f"{titles.get(kind, kind)}：最强方向为{strongest}，状态{top_state}。方向队列：{direction_text}。建议只观察资金驻留、龙头/二龙承接和退潮反证，不追单日脉冲。"


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
