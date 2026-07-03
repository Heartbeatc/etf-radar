export interface HealthResponse {
  ok: boolean;
  auth_required: boolean;
  web_auth_enabled?: boolean;
  last_error: string | null;
  last_warning: string | null;
  tracked: string[];
  benchmarks: string[];
  monitored?: string[];
  snapshot_count: number;
  source_bad_count: number;
  source_bad_codes: string[];
}


export interface PositionInput {
  entry_price: number;
  shares: number | null;
  note: string;
}

export interface Position extends PositionInput {
  code: string;
  updated_at: string;
}

export interface BuyZoneReference {
  vwap: number | null;
  ma5: number | null;
  ma10: number | null;
  ma20: number | null;
  iopv: number | null;
  premium_pct: number | null;
  atr14: number | null;
}

export interface BuyZone {
  zone_low: number | null;
  zone_high: number | null;
  avoid_above: number | null;
  reference: BuyZoneReference;
  batching: string;
}

export interface HoldPlan {
  mode: string;
  floating_profit_pct: number | null;
  expected_window: string;
  watch: string[];
}

export interface TakeProfitPlan {
  score: number;
  action: string;
  first_take_profit_price: number | null;
  second_take_profit_price: number | null;
  conditions: string[];
}

export interface ExitPlan {
  hard_stop_price: number | null;
  trend_exit_price: number | null;
  effective_exit_price: number | null;
  conditions: string[];
}

export interface TradingPlan {
  code: string;
  name: string;
  role: 'main' | 'backup' | 'benchmark' | string;
  data_state: string;
  signal: string;
  confidence: string;
  direction_score: number;
  low_buy_score: number;
  hold_score: number;
  take_profit_score: number;
  risk_score: number;
  current_price: number | null;
  source_time: string | null;
  fetched_at: string | null;
  buy_zone: BuyZone;
  hold_plan: HoldPlan;
  take_profit_plan: TakeProfitPlan;
  exit_plan: ExitPlan;
  evidence: string[];
  warnings: string[];
  ai_summary: string | null;
}

export interface LatestResponse {
  generated_at: string;
  data_time: string | null;
  poll_interval_seconds: number;
  market_status: string;
  data_age_seconds: number | null;
  top_low_buy: string | null;
  top_hold: string | null;
  top_take_profit_risk: string | null;
  plans: TradingPlan[];
}

export interface DiscoveryEtfCandidate {
  code: string;
  name: string;
  direction_key: string;
  direction_label: string;
  role: 'main' | 'backup' | 'watch' | string;
  rank: number | null;
  score: number;
  price: number | null;
  change_pct: number | null;
  amount: number | null;
  volume_ratio: number | null;
  turnover_pct: number | null;
  main_net_inflow: number | null;
  main_net_inflow_pct: number | null;
  premium_pct: number | null;
  iopv: number | null;
  entry_bias: string;
  mapping_score: number | null;
  mapping_reason: string[];
  evidence: string[];
  risk_flags: string[];
  source_time: string | null;
}

export interface DiscoveryDirection {
  direction_key: string;
  direction_label: string;
  score: number;
  etf_count: number;
  positive_count: number;
  avg_change_pct: number | null;
  total_amount: number | null;
  positive_amount_pct: number | null;
  main_net_inflow: number | null;
  top_etfs: DiscoveryEtfCandidate[];
}

export interface DiscoveryResponse {
  generated_at: string;
  source: string;
  universe_count: number;
  filtered_count: number;
  min_amount: number;
  main_candidates: DiscoveryEtfCandidate[];
  backup_candidate: DiscoveryEtfCandidate | null;
  directions: DiscoveryDirection[];
  warnings: string[];
}



export interface MarketStockCandidate {
  code: string;
  name: string;
  board_code: string | null;
  board_name: string | null;
  price: number | null;
  change_pct: number | null;
  amount: number | null;
  volume_ratio: number | null;
  turnover_pct: number | null;
  main_net_inflow: number | null;
  main_net_inflow_pct: number | null;
  score: number;
  verifier_role: string;
  evidence: string[];
  risk_flags: string[];
  source_time: string | null;
}

export interface MarketBoardCandidate {
  code: string;
  name: string;
  board_type: string;
  direction_key: string;
  direction_label: string;
  score: number;
  state: string;
  price: number | null;
  change_pct: number | null;
  amount: number | null;
  volume_ratio: number | null;
  turnover_pct: number | null;
  main_net_inflow: number | null;
  up_count: number | null;
  down_count: number | null;
  breadth_pct: number | null;
  leader_code: string | null;
  leader_name: string | null;
  leader_change_pct: number | null;
  representative_stock: MarketStockCandidate | null;
  top_stocks: MarketStockCandidate[];
  evidence: string[];
  risk_flags: string[];
  source_time: string | null;
}

export interface MarketDirection {
  direction_key: string;
  direction_label: string;
  score: number;
  state: string;
  board_count: number;
  positive_board_count: number;
  total_amount: number;
  main_net_inflow: number | null;
  avg_change_pct: number | null;
  breadth_pct: number | null;
  representative_stock: MarketStockCandidate | null;
  linked_stocks: MarketStockCandidate[];
  linked_etfs: DiscoveryEtfCandidate[];
  main_etfs: DiscoveryEtfCandidate[];
  backup_etf: DiscoveryEtfCandidate | null;
  top_boards: MarketBoardCandidate[];
  capital_concentration_pct: number | null;
  factor_scores: Record<string, number>;
  mainline_probability: number;
  residency_score: number;
  retention_score: number;
  etf_confirmation_score: number;
  stock_confirmation_score?: number;
  carrier_confirmation_score?: number;
  low_buy_readiness_score: number;
  capital_status: string;
  trade_action: string;
  risk_watch: string[];
  evidence: string[];
  risk_flags: string[];
}

export interface MarketFlowResponse {
  generated_at: string;
  source: string;
  board_count: number;
  stock_sample_count: number;
  directions: MarketDirection[];
  warnings: string[];
  assumptions: string[];
}

export interface PoolRecommendationItem {
  code: string;
  name: string;
  current_role: string | null;
  recommended_role: string | null;
  action: string;
  score: number;
  rank: number | null;
  direction_key: string | null;
  direction_label: string | null;
  direction_state: string | null;
  mainline_probability: number | null;
  low_buy_readiness_score: number | null;
  carrier_score: number | null;
  price: number | null;
  amount: number | null;
  premium_pct: number | null;
  entry_bias: string | null;
  source_time: string | null;
  reasons: string[];
  risk_flags: string[];
}

export interface PoolRecommendationResponse {
  generated_at: string;
  source: string;
  status: string;
  current_main_codes: string[];
  current_backup_codes: string[];
  recommended_main_codes: string[];
  recommended_backup_codes: string[];
  items: PoolRecommendationItem[];
  warnings: string[];
  assumptions: string[];
}

export interface QuantDirectionDecision {
  direction_key: string | null;
  direction_label: string | null;
  phase: string;
  phase_label: string;
  phase_score: number;
  confidence: string;
  operation: string;
  mainline_probability: number | null;
  seven_day_score: number | null;
  residency_score: number | null;
  retention_score: number | null;
  low_buy_readiness_score: number | null;
  evidence: string[];
  risk_flags: string[];
}

export interface QuantEtfDecision {
  code: string;
  name: string;
  role: string | null;
  action: string;
  operation: string;
  score: number;
  direction_label: string | null;
  price: number | null;
  has_position: boolean;
  floating_profit_pct: number | null;
  suggested_position_pct: number | null;
  buy_zone_low: number | null;
  buy_zone_high: number | null;
  avoid_above: number | null;
  take_profit_price: number | null;
  exit_price: number | null;
  reasons: string[];
  risk_flags: string[];
}

export interface QuantStockExecutionCondition {
  key: string;
  label: string;
  status: string;
  value: string | null;
  threshold: string | null;
  reason: string;
}

export interface QuantStockExecutionPlan {
  decision_state: string;
  decision_label: string;
  decision_reason: string;
  order_style: string;
  buy_zone_low: number | null;
  buy_zone_high: number | null;
  avoid_above: number | null;
  stop_price: number | null;
  take_profit_price: number | null;
  trigger_signal: string;
  invalidation_signal: string;
  position_plan: string;
  conditions: QuantStockExecutionCondition[];
  blockers: string[];
}

export interface QuantStockDecision {
  code: string;
  name: string;
  action: string;
  operation: string;
  score: number;
  direction_label: string | null;
  board_name: string | null;
  verifier_role: string | null;
  price: number | null;
  change_pct: number | null;
  amount: number | null;
  volume_ratio: number | null;
  main_net_inflow: number | null;
  main_net_inflow_pct: number | null;
  source_time: string | null;
  execution: QuantStockExecutionPlan | null;
  reasons: string[];
  risk_flags: string[];
}

export interface QuantDecisionResponse {
  generated_at: string;
  market_status: string;
  conclusion: string;
  direction: QuantDirectionDecision;
  etfs: QuantEtfDecision[];
  stocks: QuantStockDecision[];
  fixed_pool_actions: QuantEtfDecision[];
  warnings: string[];
  assumptions: string[];
}


export interface QuantUniverseAsset {
  asset_type: string;
  code: string | null;
  name: string;
  direction_key: string | null;
  direction_label: string | null;
  role: string;
  rank: number | null;
  selected: boolean;
  reason: string;
  evidence: string[];
  risk_flags: string[];
}

export interface QuantFeatureRow {
  asset_type: string;
  code: string | null;
  name: string;
  direction_key: string | null;
  direction_label: string | null;
  feature_set: string;
  features: Record<string, unknown>;
  score: number;
  evidence: string[];
  risk_flags: string[];
}

export interface QuantInsight {
  asset_type: string;
  code: string | null;
  name: string;
  direction: string;
  magnitude_score: number;
  confidence_score: number;
  confidence_label: string;
  horizon: string;
  insight_type: string;
  generated_from: string;
  evidence: string[];
  risk_flags: string[];
}

export interface QuantPortfolioTarget {
  code: string;
  name: string;
  target_role: string;
  rebalance_action: string;
  target_weight_pct: number | null;
  position_delta_pct: number | null;
  source_insight: string;
  target_reason: string;
  evidence: string[];
  risk_flags: string[];
}

export interface QuantRiskAdjustment {
  code: string;
  name: string;
  original_target_weight_pct: number | null;
  adjusted_target_weight_pct: number | null;
  position_delta_pct: number | null;
  risk_level: string;
  blocked: boolean;
  reasons: string[];
  risk_flags: string[];
}

export interface QuantExecutionCondition {
  key: string;
  label: string;
  status: string;
  value: string | null;
  threshold: string | null;
  reason: string;
}

export interface QuantExecutionAdvice {
  code: string;
  name: string;
  side: string;
  action: string;
  urgency: string;
  decision_state: string;
  decision_reason: string;
  current_price: number | null;
  action_score: number | null;
  low_buy_score: number | null;
  risk_score: number | null;
  target_weight_pct: number | null;
  position_delta_pct: number | null;
  order_style: string;
  trigger_price_low: number | null;
  trigger_price_high: number | null;
  avoid_above: number | null;
  stop_price: number | null;
  take_profit_price: number | null;
  conditions: QuantExecutionCondition[];
  notes: string[];
  blockers: string[];
}

export interface QuantFrameworkValidation {
  research_grade: boolean;
  live_trading_ready: boolean;
  evidence_strength: string;
  passed: string[];
  blockers: string[];
  required_upgrades: string[];
}

export interface QuantSignalRecord {
  id: number;
  signal_at: string;
  code: string;
  name: string;
  side: string;
  action: string;
  urgency: string;
  target_weight_pct: number | null;
  current_price: number | null;
  trigger_price_low: number | null;
  trigger_price_high: number | null;
  stop_price: number | null;
  take_profit_price: number | null;
  evidence_strength: string;
  live_trading_ready: boolean;
  blocker_count: number;
  signal_key: string;
  payload: Record<string, unknown>;
}

export interface QuantForwardMetric {
  horizon_days: number;
  sample_count: number;
  resolved_count: number;
  pending_count: number;
  win_rate_pct: number | null;
  avg_forward_return_pct: number | null;
  median_forward_return_pct: number | null;
}

export interface QuantCodeValidationItem {
  code: string;
  name: string;
  last_signal_at: string | null;
  last_side: string | null;
  last_action: string | null;
  actionable_count: number;
  resolved_3d: number;
  win_rate_3d_pct: number | null;
  avg_return_3d_pct: number | null;
}

export interface QuantValidationReport {
  generated_at: string;
  total_records: number;
  actionable_records: number;
  evidence_strength: string;
  live_trading_ready: boolean;
  horizon_metrics: QuantForwardMetric[];
  by_code: QuantCodeValidationItem[];
  recent_records: QuantSignalRecord[];
  warnings: string[];
  assumptions: string[];
}

export interface QuantFrameworkResponse {
  generated_at: string;
  market_status: string;
  architecture: string[];
  universe: QuantUniverseAsset[];
  features: QuantFeatureRow[];
  insights: QuantInsight[];
  portfolio_targets: QuantPortfolioTarget[];
  risk_adjustments: QuantRiskAdjustment[];
  execution_plan: QuantExecutionAdvice[];
  final_actions: ActionDecisionItem[];
  validation: QuantFrameworkValidation;
  warnings: string[];
  assumptions: string[];
}

export interface RiskItem {
  code: string;
  name: string;
  signal: string;
  current_price: number | null;
  risk_score: number;
  risk_level: string;
  take_profit_score: number;
  take_profit_action: string;
  hard_stop_price: number | null;
  trend_exit_price: number | null;
  effective_exit_price: number | null;
  warnings: string[];
}

export interface RiskResponse {
  generated_at: string;
  risk_budget_state: string;
  high_risk_count: number;
  items: RiskItem[];
  rules: string[];
}

export interface ActionDecisionItem {
  code: string;
  name: string;
  role: string;
  has_position: boolean;
  action: string;
  side: string;
  urgency: string;
  confidence: string;
  action_score: number;
  signal: string;
  current_price: number | null;
  entry_price: number | null;
  position_shares: number | null;
  floating_profit_pct: number | null;
  suggested_position_pct: number | null;
  execution_note: string;
  buy_zone_low: number | null;
  buy_zone_high: number | null;
  avoid_above: number | null;
  first_take_profit_price: number | null;
  second_take_profit_price: number | null;
  effective_exit_price: number | null;
  direction_score: number;
  low_buy_score: number;
  hold_score: number;
  take_profit_score: number;
  risk_score: number;
  reasons: string[];
  risk_flags: string[];
}

export interface ActionDecisionResponse {
  generated_at: string;
  scope: string;
  market_status: string;
  status: string;
  items: ActionDecisionItem[];
  warnings: string[];
  assumptions: string[];
}

export interface DataQualityItem {
  code: string;
  name: string;
  role: string;
  ok: boolean;
  score: number;
  issues: string[];
  source: string;
  age_seconds: number | null;
  source_time: string | null;
  price: number | null;
  iopv: number | null;
  premium_pct: number | null;
  amount: number | null;
  main_net_inflow_pct: number | null;
}

export interface DataQualityResponse {
  generated_at: string;
  overall_score: number;
  items: DataQualityItem[];
  blocked_codes: string[];
  warnings: string[];
}

export interface IntegrationStatus {
  name: string;
  enabled: boolean;
  ok: boolean;
  detail: string;
  last_error: string | null;
}

export type AiSummaryKind = 'opening_auction' | 'midday' | 'closing';

export interface AiStatus {
  enabled: boolean;
  configured: boolean;
  model: string;
  daily_call_limit: number;
  calls_used_today: number;
  force_cooldown_seconds: number;
  check_interval_seconds: number;
  windows: Array<{ kind: AiSummaryKind | string; title: string; start: string; end: string }>;
}

export interface AiSummaryItem {
  kind: AiSummaryKind | string;
  title: string;
  trading_date: string;
  generated_at: string;
  source_data_time: string | null;
  model: string;
  status: string;
  summary: string;
  error: string | null;
  payload: Record<string, unknown>;
}

export interface AiSummaryReport {
  generated_at: string;
  status: AiStatus;
  summaries: AiSummaryItem[];
  warnings: string[];
}


export interface WebLoginResponse {
  access_token: string;
  token_type: string;
  expires_at: string;
  expires_in_seconds: number;
  username: string;
}

export interface WebSessionInfo {
  authenticated: boolean;
  principal_type: string;
  username: string;
  expires_at: string | null;
}

export interface QuantMaturityModule {
  key: string;
  label: string;
  status: string;
  score: number;
  evidence: string[];
  gaps: string[];
}

export interface QuantProductionGate {
  key: string;
  label: string;
  status: string;
  score: number;
  evidence: string[];
  blockers: string[];
  next_actions: string[];
}

export interface QuantMaturityReport {
  generated_at: string;
  grade: string;
  score: number;
  verdict: string;
  modules: QuantMaturityModule[];
  production_ready: boolean;
  auto_trade_allowed: boolean;
  gates: QuantProductionGate[];
  production_blockers: string[];
  next_upgrades: string[];
  warnings: string[];
  assumptions: string[];
}

export interface QuantAlgorithmCandidate {
  key: string;
  label: string;
  family: string;
  status: string;
  fit_score: number;
  implementation_state: string;
  why_it_matters: string;
  required_data: string[];
  current_support: string[];
  evidence: string[];
  gaps: string[];
  next_actions: string[];
  source_refs: string[];
}

export interface QuantAlgorithmReport {
  generated_at: string;
  current_stack: string[];
  recommended_next: string[];
  candidates: QuantAlgorithmCandidate[];
  warnings: string[];
  assumptions: string[];
}


export interface QuantAuditFinding {
  key: string;
  label: string;
  severity: string;
  passed: boolean;
  score: number;
  claim: string;
  counterargument: string;
  evidence: string[];
  blockers: string[];
  required_evidence: string[];
}

export interface QuantCapitalVerdict {
  mature: boolean;
  maturity_label: string;
  capital_mode: string;
  max_allowed_action: string;
  auto_trade_allowed: boolean;
  summary: string;
  hard_no: string[];
  conditional_yes: string[];
}

export interface QuantSelfAuditReport {
  generated_at: string;
  verdict: QuantCapitalVerdict;
  proof_summary: string[];
  disproof_summary: string[];
  findings: QuantAuditFinding[];
  source_refs: string[];
  warnings: string[];
  assumptions: string[];
}


export interface PythonQuantReference {
  key: string;
  label: string;
  role: string;
  source_url: string;
  patterns: string[];
  adoption_decision: string;
}

export interface PythonQuantCapability {
  key: string;
  label: string;
  reference_stack: string[];
  current_state: string;
  score: number;
  adoption_state: string;
  implemented_evidence: string[];
  blockers: string[];
  next_actions: string[];
}

export interface PythonQuantStackReport {
  generated_at: string;
  current_level: string;
  readiness_score: number;
  verdict: string;
  references: PythonQuantReference[];
  capabilities: PythonQuantCapability[];
  adoption_sequence: string[];
  source_refs: string[];
  warnings: string[];
  assumptions: string[];
}
