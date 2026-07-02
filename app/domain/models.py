from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class EtfSnapshot(BaseModel):
    code: str
    name: str
    market_id: int
    role: str = "benchmark"
    source: str = "eastmoney"
    price: float | None = None
    change_pct: float | None = None
    change_amount: float | None = None
    volume: float | None = None
    amount: float | None = None
    amplitude_pct: float | None = None
    turnover_pct: float | None = None
    volume_ratio: float | None = None
    high: float | None = None
    low: float | None = None
    open: float | None = None
    previous_close: float | None = None
    bid1: float | None = None
    ask1: float | None = None
    order_imbalance_pct: float | None = None
    shares: float | None = None
    float_market_value: float | None = None
    main_net_inflow: float | None = None
    main_net_inflow_pct: float | None = None
    iopv: float | None = None
    premium_pct: float | None = None
    source_time: datetime | None = None
    fetched_at: datetime


class DailyBar(BaseModel):
    date: str
    open: float
    close: float
    high: float
    low: float
    volume: float
    amount: float
    amplitude_pct: float | None = None
    change_pct: float | None = None
    change_amount: float | None = None
    turnover_pct: float | None = None


class MinuteBar(BaseModel):
    time: str
    open: float
    close: float
    high: float
    low: float
    volume: float
    amount: float
    vwap: float | None = None


class PositionInput(BaseModel):
    entry_price: float = Field(gt=0)
    shares: float | None = Field(default=None, gt=0)
    note: str = ""


class Position(PositionInput):
    code: str
    updated_at: datetime


class TradePlan(BaseModel):
    code: str
    name: str
    role: str
    data_state: str
    signal: str
    confidence: str
    direction_score: int
    low_buy_score: int
    hold_score: int
    take_profit_score: int
    risk_score: int
    current_price: float | None
    source_time: datetime | None = None
    fetched_at: datetime | None = None
    buy_zone: dict[str, Any]
    hold_plan: dict[str, Any]
    take_profit_plan: dict[str, Any]
    exit_plan: dict[str, Any]
    evidence: list[str]
    warnings: list[str]
    ai_summary: str | None = None


class LatestResponse(BaseModel):
    generated_at: datetime
    data_time: datetime | None = None
    poll_interval_seconds: int
    market_status: str
    data_age_seconds: float | None
    top_low_buy: str | None
    top_hold: str | None
    top_take_profit_risk: str | None
    plans: list[TradePlan]
    benchmarks: list[EtfSnapshot]


class IntegrationStatus(BaseModel):
    name: str
    enabled: bool
    ok: bool
    detail: str | None = None
    last_error: str | None = None


class AiControlRequest(BaseModel):
    enabled: bool


class AiSummaryItem(BaseModel):
    kind: str
    title: str
    trading_date: str
    generated_at: datetime
    source_data_time: datetime | None = None
    model: str
    status: str = "ok"
    summary: str
    error: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class AiStatus(BaseModel):
    enabled: bool
    configured: bool
    model: str
    daily_call_limit: int
    calls_used_today: int
    force_cooldown_seconds: int
    check_interval_seconds: int
    windows: list[dict[str, str]]


class AiSummaryReport(BaseModel):
    generated_at: datetime
    status: AiStatus
    summaries: list[AiSummaryItem]
    warnings: list[str] = Field(default_factory=list)


class SourceStatus(BaseModel):
    code: str
    name: str | None = None
    role: str
    ok: bool
    issues: list[str]
    source: str | None = None
    fetched_at: datetime | None = None
    age_seconds: float | None = None
    source_time: datetime | None = None
    price: float | None = None
    iopv: float | None = None
    premium_pct: float | None = None


class SignalRecord(BaseModel):
    id: int
    code: str
    name: str
    role: str
    signal_at: datetime
    signal: str
    confidence: str
    direction_score: int
    low_buy_score: int
    hold_score: int
    take_profit_score: int
    risk_score: int
    current_price: float | None = None
    data_state: str
    payload: dict[str, Any]


class AlertEvent(BaseModel):
    id: int
    code: str
    alert_at: datetime
    level: str
    event: str
    message: str
    delivered: bool
    error: str | None = None
    payload: dict[str, Any]


class BacktestTrade(BaseModel):
    entry_date: str
    entry_price: float
    exit_date: str | None = None
    exit_price: float | None = None
    return_pct: float | None = None
    reason: str | None = None


class BacktestResult(BaseModel):
    code: str
    name: str
    days: int
    bars_used: int
    trades: list[BacktestTrade]
    trade_count: int
    win_rate_pct: float | None
    total_return_pct: float
    max_drawdown_pct: float
    exposure_days: int
    latest_signal: str | None
    assumptions: list[str]


class DataQualityItem(BaseModel):
    code: str
    name: str | None = None
    role: str
    ok: bool
    score: int
    issues: list[str]
    source: str | None = None
    age_seconds: float | None = None
    source_time: datetime | None = None
    price: float | None = None
    iopv: float | None = None
    premium_pct: float | None = None
    amount: float | None = None
    main_net_inflow_pct: float | None = None


class DataQualityReport(BaseModel):
    generated_at: datetime
    overall_score: float
    items: list[DataQualityItem]
    blocked_codes: list[str]
    warnings: list[str]


class RiskItem(BaseModel):
    code: str
    name: str
    signal: str
    current_price: float | None = None
    risk_score: int
    risk_level: str
    take_profit_score: int
    take_profit_action: str
    hard_stop_price: float | None = None
    trend_exit_price: float | None = None
    effective_exit_price: float | None = None
    warnings: list[str]


class RiskReport(BaseModel):
    generated_at: datetime
    risk_budget_state: str
    high_risk_count: int
    items: list[RiskItem]
    rules: list[str]


class ActionDecisionItem(BaseModel):
    code: str
    name: str
    role: str
    has_position: bool
    action: str
    side: str
    urgency: str
    confidence: str
    action_score: int
    signal: str
    current_price: float | None = None
    entry_price: float | None = None
    position_shares: float | None = None
    floating_profit_pct: float | None = None
    suggested_position_pct: int | None = None
    execution_note: str = ""
    buy_zone_low: float | None = None
    buy_zone_high: float | None = None
    avoid_above: float | None = None
    first_take_profit_price: float | None = None
    second_take_profit_price: float | None = None
    effective_exit_price: float | None = None
    direction_score: int
    low_buy_score: int
    hold_score: int
    take_profit_score: int
    risk_score: int
    reasons: list[str]
    risk_flags: list[str]


class ActionDecisionResponse(BaseModel):
    generated_at: datetime
    scope: str
    market_status: str
    status: str
    items: list[ActionDecisionItem]
    warnings: list[str]
    assumptions: list[str]


class BacktestSummary(BaseModel):
    generated_at: datetime
    days: int
    results: list[BacktestResult]
    ranking: list[dict[str, Any]]
    assumptions: list[str]

class DiscoveryEtfCandidate(BaseModel):
    code: str
    name: str
    direction_key: str
    direction_label: str
    role: str = "watch"
    rank: int | None = None
    score: int
    price: float | None = None
    change_pct: float | None = None
    amount: float | None = None
    volume_ratio: float | None = None
    turnover_pct: float | None = None
    main_net_inflow: float | None = None
    main_net_inflow_pct: float | None = None
    premium_pct: float | None = None
    iopv: float | None = None
    entry_bias: str
    mapping_score: int | None = None
    mapping_reason: list[str] = Field(default_factory=list)
    evidence: list[str]
    risk_flags: list[str]
    source_time: datetime | None = None


class DiscoveryDirection(BaseModel):
    direction_key: str
    direction_label: str
    score: int
    etf_count: int
    positive_count: int
    avg_change_pct: float | None = None
    total_amount: float
    positive_amount_pct: float | None = None
    main_net_inflow: float | None = None
    top_etfs: list[DiscoveryEtfCandidate]


class DiscoveryResponse(BaseModel):
    generated_at: datetime
    source: str
    universe_count: int
    filtered_count: int
    min_amount: float
    main_candidates: list[DiscoveryEtfCandidate]
    backup_candidate: DiscoveryEtfCandidate | None = None
    directions: list[DiscoveryDirection]
    warnings: list[str]
    assumptions: list[str]


class MarketStockCandidate(BaseModel):
    code: str
    name: str
    board_code: str | None = None
    board_name: str | None = None
    price: float | None = None
    change_pct: float | None = None
    amount: float | None = None
    volume_ratio: float | None = None
    turnover_pct: float | None = None
    main_net_inflow: float | None = None
    main_net_inflow_pct: float | None = None
    score: int
    verifier_role: str = "leader"
    evidence: list[str]
    risk_flags: list[str]
    source_time: datetime | None = None


class MarketBoardCandidate(BaseModel):
    code: str
    name: str
    board_type: str
    direction_key: str
    direction_label: str
    score: int
    state: str
    price: float | None = None
    change_pct: float | None = None
    amount: float | None = None
    volume_ratio: float | None = None
    turnover_pct: float | None = None
    main_net_inflow: float | None = None
    up_count: int | None = None
    down_count: int | None = None
    breadth_pct: float | None = None
    leader_code: str | None = None
    leader_name: str | None = None
    leader_change_pct: float | None = None
    representative_stock: MarketStockCandidate | None = None
    evidence: list[str]
    risk_flags: list[str]
    source_time: datetime | None = None


class MarketDirection(BaseModel):
    direction_key: str
    direction_label: str
    score: int
    state: str
    board_count: int
    positive_board_count: int
    total_amount: float
    main_net_inflow: float | None = None
    avg_change_pct: float | None = None
    breadth_pct: float | None = None
    representative_stock: MarketStockCandidate | None = None
    linked_stocks: list[MarketStockCandidate] = Field(default_factory=list)
    linked_etfs: list[DiscoveryEtfCandidate]
    main_etfs: list[DiscoveryEtfCandidate] = Field(default_factory=list)
    backup_etf: DiscoveryEtfCandidate | None = None
    top_boards: list[MarketBoardCandidate]
    capital_concentration_pct: float | None = None
    factor_scores: dict[str, int] = Field(default_factory=dict)
    mainline_probability: int = 0
    residency_score: int = 0
    retention_score: int = 0
    etf_confirmation_score: int = 0
    low_buy_readiness_score: int = 0
    capital_status: str = "unknown"
    trade_action: str = "wait"
    risk_watch: list[str] = Field(default_factory=list)
    evidence: list[str]
    risk_flags: list[str]


class MarketFlowResponse(BaseModel):
    generated_at: datetime
    source: str
    board_count: int
    stock_sample_count: int
    directions: list[MarketDirection]
    warnings: list[str]
    assumptions: list[str]


class PoolRecommendationItem(BaseModel):
    code: str
    name: str
    current_role: str | None = None
    recommended_role: str | None = None
    action: str
    score: int
    rank: int | None = None
    direction_key: str | None = None
    direction_label: str | None = None
    direction_state: str | None = None
    mainline_probability: int | None = None
    low_buy_readiness_score: int | None = None
    carrier_score: int | None = None
    price: float | None = None
    amount: float | None = None
    premium_pct: float | None = None
    entry_bias: str | None = None
    source_time: datetime | None = None
    reasons: list[str]
    risk_flags: list[str]


class PoolRecommendationResponse(BaseModel):
    generated_at: datetime
    source: str
    status: str
    current_main_codes: list[str]
    current_backup_codes: list[str]
    recommended_main_codes: list[str]
    recommended_backup_codes: list[str]
    items: list[PoolRecommendationItem]
    warnings: list[str]
    assumptions: list[str]


class QuantDirectionDecision(BaseModel):
    direction_key: str | None = None
    direction_label: str | None = None
    phase: str
    phase_label: str
    phase_score: int
    confidence: str
    operation: str
    mainline_probability: int | None = None
    residency_score: int | None = None
    retention_score: int | None = None
    low_buy_readiness_score: int | None = None
    evidence: list[str]
    risk_flags: list[str]


class QuantEtfDecision(BaseModel):
    code: str
    name: str
    role: str | None = None
    action: str
    operation: str
    score: int
    direction_label: str | None = None
    price: float | None = None
    has_position: bool = False
    floating_profit_pct: float | None = None
    suggested_position_pct: int | None = None
    buy_zone_low: float | None = None
    buy_zone_high: float | None = None
    avoid_above: float | None = None
    take_profit_price: float | None = None
    exit_price: float | None = None
    reasons: list[str]
    risk_flags: list[str]


class QuantStockDecision(BaseModel):
    code: str
    name: str
    action: str
    operation: str
    score: int
    direction_label: str | None = None
    change_pct: float | None = None
    reasons: list[str]
    risk_flags: list[str]


class QuantDecisionResponse(BaseModel):
    generated_at: datetime
    market_status: str
    conclusion: str
    direction: QuantDirectionDecision
    etfs: list[QuantEtfDecision]
    stocks: list[QuantStockDecision]
    fixed_pool_actions: list[QuantEtfDecision]
    warnings: list[str]
    assumptions: list[str]



class QuantUniverseAsset(BaseModel):
    asset_type: str
    code: str | None = None
    name: str
    direction_key: str | None = None
    direction_label: str | None = None
    role: str = "candidate"
    rank: int | None = None
    selected: bool
    reason: str
    evidence: list[str]
    risk_flags: list[str]


class QuantFeatureRow(BaseModel):
    asset_type: str
    code: str | None = None
    name: str
    direction_key: str | None = None
    direction_label: str | None = None
    feature_set: str
    features: dict[str, Any]
    score: int
    evidence: list[str]
    risk_flags: list[str]


class QuantInsight(BaseModel):
    asset_type: str
    code: str | None = None
    name: str
    direction: str
    magnitude_score: int
    confidence_score: int
    confidence_label: str
    horizon: str
    insight_type: str
    generated_from: str
    evidence: list[str]
    risk_flags: list[str]


class QuantPortfolioTarget(BaseModel):
    code: str
    name: str
    target_role: str
    rebalance_action: str
    target_weight_pct: float | None = None
    position_delta_pct: int | None = None
    source_insight: str
    target_reason: str
    evidence: list[str]
    risk_flags: list[str]


class QuantRiskAdjustment(BaseModel):
    code: str
    name: str
    original_target_weight_pct: float | None = None
    adjusted_target_weight_pct: float | None = None
    position_delta_pct: int | None = None
    risk_level: str
    blocked: bool
    reasons: list[str]
    risk_flags: list[str]


class QuantExecutionAdvice(BaseModel):
    code: str
    name: str
    side: str
    action: str
    urgency: str
    target_weight_pct: float | None = None
    position_delta_pct: int | None = None
    order_style: str
    trigger_price_low: float | None = None
    trigger_price_high: float | None = None
    avoid_above: float | None = None
    stop_price: float | None = None
    take_profit_price: float | None = None
    notes: list[str]
    blockers: list[str]


class QuantFrameworkValidation(BaseModel):
    research_grade: bool
    live_trading_ready: bool
    evidence_strength: str
    passed: list[str]
    blockers: list[str]
    required_upgrades: list[str]


class QuantFrameworkResponse(BaseModel):
    generated_at: datetime
    market_status: str
    architecture: list[str]
    universe: list[QuantUniverseAsset]
    features: list[QuantFeatureRow]
    insights: list[QuantInsight]
    portfolio_targets: list[QuantPortfolioTarget]
    risk_adjustments: list[QuantRiskAdjustment]
    execution_plan: list[QuantExecutionAdvice]
    final_actions: list[ActionDecisionItem]
    validation: QuantFrameworkValidation
    warnings: list[str]
    assumptions: list[str]



class WebLoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=256)


class WebSessionResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    expires_in_seconds: int
    username: str


class WebSessionInfo(BaseModel):
    authenticated: bool = True
    principal_type: str
    username: str
    expires_at: datetime | None = None
