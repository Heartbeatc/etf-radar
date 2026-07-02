import type { Position, QuantExecutionAdvice, QuantFrameworkResponse } from '../../types';

export function executionShortText(item: QuantExecutionAdvice): string {
  if (item.blockers.length) return '风控阻断';
  if (item.side === 'BUY') return '低吸触发';
  if (item.side === 'SELL') return '卖出/减仓';
  if (item.side === 'HOLD') return '持有跟踪';
  if (item.action === 'AVOID') return '回避';
  if (item.action === 'WAIT_PULLBACK') return '等回落';
  if (item.action === 'WAIT_CONFIRMATION' || (isPriceInLowBuyZone(item) && (item.low_buy_score ?? 0) < 70)) return '价到，分数不足';
  if (item.action === 'WAIT_BUY_ZONE' || item.action === 'WATCH_LOW_BUY') return '等低吸区';
  return isPriceInLowBuyZone(item) ? '价到，等确认' : '等待';
}

export function isPriceInLowBuyZone(item: QuantExecutionAdvice): boolean {
  return item.current_price != null
    && item.trigger_price_low != null
    && item.trigger_price_high != null
    && item.current_price >= item.trigger_price_low
    && item.current_price <= item.trigger_price_high;
}

export function lowBuyScoreText(value: number | null | undefined): string {
  return value == null ? '-' : `${value.toFixed(0)}/70`;
}

export function formatScore(value: number | null | undefined): string {
  return value == null || !Number.isFinite(value) ? '-' : value.toFixed(0);
}

export function decisionStateLabel(value: string | null | undefined): string {
  const map: Record<string, string> = {
    ready: '契约通过',
    wait_confirmation: '等待确认',
    wait_price: '等待价格',
    blocked: '风控阻断',
    hold: '持仓跟踪',
    avoid: '回避'
  };
  return value ? map[value] ?? value : '-';
}

export function marketStatusLabel(value: string | null | undefined): string {
  const map: Record<string, string> = {
    trading: '交易中',
    closed: '已收盘',
    pre_market: '盘前',
    midday_break: '午间休市',
    unknown: '未知'
  };
  return value ? map[value] ?? value : '-';
}

export function maturityGradeLabel(value: string | null | undefined): string {
  const map: Record<string, string> = {
    prototype: '原型',
    research_quant: '研究级量化',
    production_candidate: '生产候选',
    production_quant: '生产级量化'
  };
  return value ? map[value] ?? value : '-';
}

export function maturityStatusClass(value: string | null | undefined): string {
  const normalized = normalizeStatus(value);
  if (['strong', 'usable', 'ready', 'pass'].includes(normalized)) return 'pass';
  if (['research-grade', 'research', 'medium', 'partial'].includes(normalized)) return 'warn';
  if (['prototype', 'weak', 'gap', 'fail', 'blocked'].includes(normalized)) return 'fail';
  return 'wait';
}

export function maturityStatusLabel(value: string | null | undefined): string {
  const normalized = normalizeStatus(value);
  const map: Record<string, string> = {
    strong: '强',
    usable: '可用',
    ready: '就绪',
    pass: '通过',
    'research-grade': '研究级',
    research: '研究',
    medium: '中等',
    partial: '部分',
    prototype: '原型',
    weak: '弱',
    gap: '缺口',
    fail: '失败',
    blocked: '阻断'
  };
  return map[normalized] ?? (value || '-');
}

export function conditionStatusClass(value: string | null | undefined): string {
  const normalized = normalizeStatus(value);
  if (['pass', 'passed', 'ok', 'true'].includes(normalized)) return 'pass';
  if (['fail', 'failed', 'blocked', 'false'].includes(normalized)) return 'fail';
  if (['warn', 'warning', 'partial'].includes(normalized)) return 'warn';
  return 'wait';
}

export function conditionStatusLabel(value: string | null | undefined): string {
  const normalized = normalizeStatus(value);
  if (['pass', 'passed', 'ok', 'true'].includes(normalized)) return 'PASS';
  if (['fail', 'failed', 'blocked', 'false'].includes(normalized)) return 'FAIL';
  if (['warn', 'warning', 'partial'].includes(normalized)) return 'WARN';
  return 'WAIT';
}

export function normalizeStatus(value: string | null | undefined): string {
  return (value ?? '').trim().toLowerCase().replace(/_/g, '-');
}

export function etfRegionLabel(name: string): string {
  return /港股|港股通|恒生|中概|H股|香港/.test(name) ? '港股载体' : 'A股载体';
}

export function pickPrimaryExecution(framework?: QuantFrameworkResponse, positions: Position[] = []) {
  const items = framework?.execution_plan ?? [];
  const priority = items.find((item) => item.side === 'SELL') ?? items.find((item) => item.side === 'BUY') ?? items.find((item) => item.side === 'HOLD') ?? items[0];
  if (priority) {
    return {
      code: priority.code,
      action: priority.action,
      side: priority.side,
      note: priority.blockers[0] ?? priority.decision_reason ?? priority.notes[0] ?? executionShortText(priority)
    };
  }
  return { code: null, action: 'WAIT', side: 'WAIT', note: positions.length ? '等待持仓风控信号。' : '空仓等待低吸触发。' };
}

export function frameworkStageLabel(framework?: QuantFrameworkResponse): string {
  if (!framework) return '无数据';
  if (framework.validation.live_trading_ready) return '可执行';
  if (framework.validation.blockers.length) return '验证未通过';
  if (framework.validation.evidence_strength === 'medium-low') return '研究级验证中';
  return '观察中';
}

export function frameworkConclusion(framework: QuantFrameworkResponse | undefined, primary: ReturnType<typeof pickPrimaryExecution>): string {
  if (!framework) return '暂无量化链路，先不做交易动作';
  if (primary.side === 'SELL') return `风控/止盈优先：${primary.note}`;
  if (primary.side === 'BUY') return `执行契约通过：${primary.code} 可按计划低吸`;
  if (primary.action === 'WAIT_CONFIRMATION') return `价格到位但契约未满：${primary.note}`;
  if (primary.side === 'HOLD') return `持仓跟踪：${primary.note}`;
  return `当前不交易：${primary.note}`;
}

export function executionRank(item: QuantExecutionAdvice): number {
  if (item.side === 'SELL') return 0;
  if (item.side === 'BUY') return 1;
  if (item.side === 'HOLD') return 2;
  if (item.blockers.length) return 3;
  return 4;
}

export function actionLabel(value: string): string {
  const map: Record<string, string> = {
    BUY_FIRST_BATCH: '买入首仓',
    SELL_ALL: '全部卖出',
    SELL_PARTIAL_50: '止盈一半',
    SELL_PARTIAL_20_30: '止盈20-30%',
    REDUCE_OR_HOLD_TIGHT: '减仓/收紧',
    HOLD: '持有',
    HOLD_WATCH: '持有观察',
    WAIT_BUY_ZONE: '等低吸区',
    WATCH_LOW_BUY: '低吸观察',
    WAIT_PULLBACK: '等回落',
    WAIT_DATA: '等数据',
    WAIT_CONFIRMATION: '价到待确认',
    AVOID: '回避',
    WAIT: '等待',
    WATCH: '观察',
    BUY: '买入',
    SELL: '卖出'
  };
  return map[value] ?? value;
}

export function actionColor(side: string): string {
  const map: Record<string, string> = { BUY: 'green', SELL: 'red', HOLD: 'blue', WAIT: 'orange', AVOID: 'red' };
  return map[side] ?? 'default';
}

export function evidenceLabel(value?: string): string {
  const map: Record<string, string> = { high: '高', medium: '中', 'medium-low': '中低', low: '低' };
  return value ? map[value] ?? value : '-';
}

export function evidenceColor(value?: string): string {
  if (value === 'high') return 'green';
  if (value === 'medium') return 'blue';
  if (value === 'medium-low') return 'orange';
  return 'red';
}

export function riskLabel(value?: string): string {
  const map: Record<string, string> = { low: '低风险', medium: '中风险', high: '高风险' };
  return value ? map[value] ?? value : '-';
}

export function riskColor(value?: string): string {
  if (value === 'high') return 'red';
  if (value === 'medium') return 'orange';
  if (value === 'low') return 'green';
  return 'default';
}

export function rebalanceLabel(value: string): string {
  const map: Record<string, string> = {
    open_first_batch: '首仓',
    wait_for_trigger: '等触发',
    watch_for_entry: '观察入场',
    hold_or_add_under_cap: '持有/限额加仓',
    exit: '离场',
    take_profit_reduce: '止盈减仓',
    take_profit_trim: '止盈兑现',
    risk_trim: '风险减仓',
    keep_existing_position: '保留持仓',
    avoid: '回避',
    wait_data: '等数据',
    watch: '观察'
  };
  return map[value] ?? value;
}

export function assetTypeLabel(value: string): string {
  const map: Record<string, string> = { direction: '方向', etf: 'ETF', etf_action: '动作' };
  return map[value] ?? value;
}

export function roleLabel(value: string): string {
  const map: Record<string, string> = { mainline_candidate: '主线候选', monitor: '监控', main: '主要', backup: '备选', watch: '观察', held_position: '持仓' };
  return map[value] ?? value;
}

export function insightTypeLabel(value: string): string {
  const map: Record<string, string> = { mainline_regime: '主线阶段', carrier_alpha: 'ETF Alpha', position_management: '持仓管理' };
  return map[value] ?? value;
}

export function directionColor(value: string): string {
  if (value === 'UP') return 'green';
  if (value === 'DOWN') return 'red';
  if (value === 'FLAT') return 'orange';
  return 'default';
}

export function scoreColor(value: number): string {
  if (value >= 75) return '#15803d';
  if (value >= 58) return '#2563eb';
  if (value >= 40) return '#d97706';
  return '#dc2626';
}

export function formatPercentNumber(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '-';
  return `${value.toFixed(1)}%`;
}

export function formatSignedPercent(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '-';
  return `${value > 0 ? '+' : ''}${value.toFixed(2)}%`;
}

export function formatDelta(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '-';
  return `${value > 0 ? '+' : ''}${value.toFixed(0)}%`;
}

export function priceRange(low: number | null | undefined, high: number | null | undefined): string {
  if (low == null && high == null) return '-';
  return `${formatPrice(low)} - ${formatPrice(high)}`;
}

export function formatPrice(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '-';
  return value.toFixed(3);
}

export function formatDateTime(value?: string | null): string {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false });
}

export function formatFeatureValue(value: unknown): string {
  if (typeof value === 'number') return Number.isInteger(value) ? value.toFixed(0) : value.toFixed(2);
  if (typeof value === 'string') return value;
  if (value == null) return '-';
  return String(value);
}
