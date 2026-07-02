export interface HealthResponse {
  ok: boolean;
  auth_required: boolean;
  web_auth_enabled?: boolean;
  last_error: string | null;
  last_warning: string | null;
  tracked: string[];
  benchmarks: string[];
  snapshot_count: number;
  source_bad_count: number;
  source_bad_codes: string[];
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
