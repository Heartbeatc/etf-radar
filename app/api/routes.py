from __future__ import annotations

from datetime import datetime, timezone
from fastapi import Depends, FastAPI, HTTPException, Query

from app.core.config import Settings
from app.core.runtime import Runtime
from app.domain.models import (
    AiControlRequest,
    ActionDecisionResponse,
    AiStatus,
    AiSummaryItem,
    AiSummaryReport,
    AlertEvent,
    BacktestResult,
    BacktestSummary,
    DataQualityReport,
    DiscoveryResponse,
    EtfSnapshot,
    IntegrationStatus,
    LatestResponse,
    MarketFlowResponse,
    PoolRecommendationResponse,
    Position,
    PositionInput,
    SignalRecord,
    RiskReport,
    SourceStatus,
    TradePlan,
    WebLoginRequest,
    WebSessionInfo,
    WebSessionResponse,
)
from app.services.action_decision import build_action_decision_report
from app.services.backtest import run_backtest
from app.services.data_quality import build_data_quality_report
from app.services.pool_recommendation import build_pool_recommendation_report
from app.services.risk import build_risk_report
from app.api.security import AuthPrincipal, authenticate_web_user, require_api_token

PROTECTED = [Depends(require_api_token)]


def register_routes(app: FastAPI, runtime: Runtime, settings: Settings) -> None:
    @app.get("/health")
    async def health() -> dict:
        latest = runtime.store.latest_snapshots()
        statuses = runtime.source_status()
        bad = [status.code for status in statuses if not status.ok]
        return {
            "ok": bool(latest) and runtime._last_error is None,
            "auth_required": bool(settings.api_token or settings.web_auth_enabled),
            "web_auth_enabled": settings.web_auth_enabled,
            "last_error": runtime._last_error,
            "last_warning": runtime._last_warning,
            "tracked": settings.exposed_codes,
            "benchmarks": settings.benchmark_code_list,
            "snapshot_count": len(latest),
            "source_bad_count": len(bad),
            "source_bad_codes": bad,
        }

    @app.post("/api/v1/auth/login", response_model=WebSessionResponse)
    async def auth_login(payload: WebLoginRequest) -> WebSessionResponse:
        session = authenticate_web_user(payload.username, payload.password, settings)
        if session is None:
            raise HTTPException(
                status_code=401,
                detail="Invalid username or password",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return session

    @app.get("/api/v1/auth/session", response_model=WebSessionInfo)
    async def auth_session(principal: AuthPrincipal = Depends(require_api_token)) -> WebSessionInfo:
        return WebSessionInfo(
            principal_type=principal.principal_type,
            username=principal.username,
            expires_at=principal.expires_at,
        )

    @app.post("/api/v1/auth/logout", dependencies=PROTECTED)
    async def auth_logout() -> dict:
        return {"ok": True}

    @app.get("/api/v1/latest", response_model=LatestResponse, dependencies=PROTECTED)
    async def latest() -> LatestResponse:
        return await runtime.latest()

    @app.get("/api/v1/plan", response_model=list[TradePlan], dependencies=PROTECTED)
    async def plan() -> list[TradePlan]:
        return await runtime.plans()

    @app.get("/api/v1/detail/{code}", response_model=TradePlan, dependencies=PROTECTED)
    async def detail(code: str, entry_price: float | None = Query(default=None, gt=0)) -> TradePlan:
        return runtime.detail(code, entry_price=entry_price)

    @app.get("/api/v1/source-status", response_model=list[SourceStatus], dependencies=PROTECTED)
    async def source_status() -> list[SourceStatus]:
        statuses = runtime.source_status()
        runtime.store.save_source_status(statuses)
        return statuses

    @app.get("/api/v1/data-quality", response_model=DataQualityReport, dependencies=PROTECTED)
    async def data_quality() -> DataQualityReport:
        return build_data_quality_report(settings, runtime.store.latest_snapshots())

    @app.get("/api/v1/discovery", response_model=DiscoveryResponse, dependencies=PROTECTED)
    async def discovery(
        force: bool = Query(default=False),
        min_amount: float | None = Query(default=None, ge=1_000_000),
    ) -> DiscoveryResponse:
        return await runtime.discovery(force=force, min_amount=min_amount)

    @app.get("/api/v1/market-flow", response_model=MarketFlowResponse, dependencies=PROTECTED)
    async def market_flow(force: bool = Query(default=False)) -> MarketFlowResponse:
        return await runtime.market_flow(force=force)


    @app.get("/api/v1/pool-recommendation", response_model=PoolRecommendationResponse, dependencies=PROTECTED)
    async def pool_recommendation() -> PoolRecommendationResponse:
        market_flow_report = await runtime.market_flow()
        return build_pool_recommendation_report(settings, market_flow_report, runtime.store.latest_snapshots())


    @app.get("/api/v1/action-decisions", response_model=ActionDecisionResponse, dependencies=PROTECTED)
    async def action_decisions() -> ActionDecisionResponse:
        return build_action_decision_report(runtime.build_rule_plans(), runtime.store.positions())

    @app.get("/api/v1/risk", response_model=RiskReport, dependencies=PROTECTED)
    async def risk() -> RiskReport:
        return build_risk_report(runtime.build_rule_plans())

    @app.get("/api/v1/integrations", response_model=list[IntegrationStatus], dependencies=PROTECTED)
    async def integrations() -> list[IntegrationStatus]:
        return await runtime.integrations_status()

    @app.get("/api/v1/ai/status", response_model=AiStatus, dependencies=PROTECTED)
    async def ai_status() -> AiStatus:
        return runtime.ai_status()

    @app.put("/api/v1/ai/status", response_model=AiStatus, dependencies=PROTECTED)
    async def set_ai_status(payload: AiControlRequest) -> AiStatus:
        return runtime.set_ai_enabled(payload.enabled)

    @app.get("/api/v1/ai/summaries", response_model=AiSummaryReport, dependencies=PROTECTED)
    async def ai_summaries(limit: int = Query(default=10, ge=1, le=50)) -> AiSummaryReport:
        return runtime.ai_summary_report(limit=limit)

    @app.post("/api/v1/ai/summaries/{kind}", response_model=AiSummaryItem, dependencies=PROTECTED)
    async def generate_ai_summary(kind: str, force: bool = Query(default=False)) -> AiSummaryItem:
        item = await runtime.generate_ai_summary(kind=kind, force=force)
        if item is None:
            raise HTTPException(status_code=409, detail="AI summary is disabled, not configured, or daily call limit has been reached")
        return item

    @app.get("/api/v1/snapshots", response_model=list[EtfSnapshot], dependencies=PROTECTED)
    async def snapshots() -> list[EtfSnapshot]:
        latest = runtime.store.latest_snapshots()
        return [latest[code] for code in settings.exposed_codes if code in latest]

    @app.get("/api/v1/signals", response_model=list[SignalRecord], dependencies=PROTECTED)
    async def signals(code: str | None = None, limit: int = Query(default=200, ge=1, le=1000)) -> list[SignalRecord]:
        return runtime.store.signal_history(code=code, limit=limit)

    @app.get("/api/v1/alerts", response_model=list[AlertEvent], dependencies=PROTECTED)
    async def alerts(code: str | None = None, limit: int = Query(default=100, ge=1, le=1000)) -> list[AlertEvent]:
        return runtime.store.alert_events(code=code, limit=limit)

    @app.post("/api/v1/alerts/test", response_model=AlertEvent, dependencies=PROTECTED)
    async def test_alert() -> AlertEvent:
        return await runtime.alerts.send_test()

    @app.get("/api/v1/backtest/{code}", response_model=BacktestResult, dependencies=PROTECTED)
    async def backtest(code: str, days: int = Query(default=120, ge=45, le=500)) -> BacktestResult:
        if code not in settings.exposed_codes:
            raise HTTPException(status_code=400, detail=f"{code} is not in exposed ETF list")
        daily = await runtime.ensure_daily_bars(code)
        latest = runtime.store.latest_snapshots()
        snapshot = latest.get(code)
        name = snapshot.name if snapshot else code
        role = snapshot.role if snapshot else runtime.roles().get(code, "main")
        return run_backtest(code=code, name=name, role=role, daily=daily, days=days)

    @app.get("/api/v1/backtest-summary", response_model=BacktestSummary, dependencies=PROTECTED)
    async def backtest_summary(days: int = Query(default=120, ge=45, le=500)) -> BacktestSummary:
        latest = runtime.store.latest_snapshots()
        results: list[BacktestResult] = []
        for code in settings.exposed_codes:
            daily = await runtime.ensure_daily_bars(code)
            snapshot = latest.get(code)
            name = snapshot.name if snapshot else code
            role = snapshot.role if snapshot else runtime.roles().get(code, "main")
            results.append(run_backtest(code=code, name=name, role=role, daily=daily, days=days))
        ranking = [
            {
                "code": item.code,
                "name": item.name,
                "total_return_pct": item.total_return_pct,
                "max_drawdown_pct": item.max_drawdown_pct,
                "win_rate_pct": item.win_rate_pct,
                "trade_count": item.trade_count,
            }
            for item in sorted(results, key=lambda value: (value.total_return_pct, -value.max_drawdown_pct), reverse=True)
        ]
        return BacktestSummary(
            generated_at=datetime.now(timezone.utc),
            days=days,
            results=results,
            ranking=ranking,
            assumptions=[
                "Uses locally cached daily bars; refresh history first if bars are stale.",
                "Backtest is rule validation, not a promise of future return.",
                "Fees, spread, premium drift, and execution slippage are simplified.",
            ],
        )

    @app.post("/api/v1/refresh-history", dependencies=PROTECTED)
    async def refresh_history() -> dict:
        return await runtime.refresh_history()

    @app.get("/api/v1/positions", response_model=list[Position], dependencies=PROTECTED)
    async def positions() -> list[Position]:
        return list(runtime.store.positions().values())

    @app.put("/api/v1/positions/{code}", response_model=Position, dependencies=PROTECTED)
    async def upsert_position(code: str, position: PositionInput) -> Position:
        if code not in settings.exposed_codes:
            raise HTTPException(status_code=400, detail=f"{code} is not in exposed ETF list")
        return runtime.store.upsert_position(code, position)

    @app.delete("/api/v1/positions/{code}", dependencies=PROTECTED)
    async def delete_position(code: str) -> dict:
        deleted = runtime.store.delete_position(code)
        return {"deleted": deleted}
