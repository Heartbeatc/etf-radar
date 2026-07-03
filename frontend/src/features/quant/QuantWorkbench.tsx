import { useState } from 'react';
import type { PositionInput, QuantDecisionResponse, QuantDirectionDecision, QuantHoldingDecision, QuantStockDecision } from '../../types';
import { formatDateTime, formatScore } from './formatters';

interface QuantWorkbenchProps {
  decision?: QuantDecisionResponse;
  onRefresh: () => void;
  refreshing: boolean;
  onLogout: () => void;
  onSavePosition: (code: string, input: PositionInput) => void;
  onDeletePosition: (code: string) => void;
  savingPosition: boolean;
  deletingPosition: boolean;
  errorMessage: string | null;
}

export function QuantWorkbench({
  decision,
  onRefresh,
  refreshing,
  onLogout,
  onSavePosition,
  onDeletePosition,
  savingPosition,
  deletingPosition,
  errorMessage
}: QuantWorkbenchProps) {
  const direction = decision?.direction;
  const holdings = decision?.holdings ?? [];
  const stocks = pickStocks(decision?.bottom_candidates ?? []);
  const candidateRows = stocks.length ? stocks : [null];
  const status = capitalStatus(direction);
  const [code, setCode] = useState('');
  const [entryPrice, setEntryPrice] = useState('');
  const [shares, setShares] = useState('');
  const [entryDate, setEntryDate] = useState(todayText());
  const [note, setNote] = useState('');

  const save = () => {
    const normalized = code.trim();
    const parsedEntry = Number(entryPrice);
    const parsedShares = shares.trim() ? Number(shares) : null;
    if (!/^\d{6}$/.test(normalized)) {
      window.alert('请输入6位A股代码');
      return;
    }
    if (!Number.isFinite(parsedEntry) || parsedEntry <= 0) {
      window.alert('请输入有效成本价');
      return;
    }
    if (parsedShares !== null && (!Number.isFinite(parsedShares) || parsedShares <= 0)) {
      window.alert('数量必须大于0，或留空');
      return;
    }
    onSavePosition(normalized, {
      entry_price: parsedEntry,
      shares: parsedShares,
      entry_date: entryDate || null,
      note: note.trim()
    });
  };

  return (
    <main className="excel-page">
      <table className="excel-sheet" aria-label="A股主线执行表">
        <colgroup>
          <col className="row-index-col" />
          <col className="direction-col" />
          <col className="capital-col" />
          <col className="phase-col" />
          <col className="stock-col" />
          <col className="price-col" />
          <col className="zone-col" />
          <col className="trigger-col" />
          <col className="risk-col" />
          <col className="exit-col" />
          <col className="action-col" />
        </colgroup>
        <thead>
          <tr className="excel-letters">
            <th></th><th>A</th><th>B</th><th>C</th><th>D</th><th>E</th><th>F</th><th>G</th><th>H</th><th>I</th><th>J</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <th className="row-index">1</th>
            <td className="sheet-title">A股主线执行表</td>
            <td className="sheet-meta">{formatDateTime(decision?.generated_at)}</td>
            <td className="sheet-meta">30 秒刷新</td>
            <td className="sheet-meta">{decision?.market_status ?? '-'}</td>
            <td className="sheet-meta" colSpan={5}>
              <span>{decision?.conclusion ?? '等待数据'}</span>
              {formatAiDirectionSummary(decision)}
            </td>
            <td className="sheet-actions">
              <button type="button" onClick={onRefresh} disabled={refreshing}>{refreshing ? '刷新中' : '刷新'}</button>
              <button type="button" onClick={onLogout}>退出</button>
            </td>
          </tr>
          <tr className="position-entry-row">
            <th className="row-index">2</th>
            <td className="sheet-title">录入持仓</td>
            <td><input value={code} onChange={(event) => setCode(event.target.value)} placeholder="代码" maxLength={6} /></td>
            <td><input value={entryPrice} onChange={(event) => setEntryPrice(event.target.value)} placeholder="成本" inputMode="decimal" /></td>
            <td><input value={shares} onChange={(event) => setShares(event.target.value)} placeholder="数量可空" inputMode="decimal" /></td>
            <td><input value={entryDate} onChange={(event) => setEntryDate(event.target.value)} type="date" /></td>
            <td colSpan={3}><input value={note} onChange={(event) => setNote(event.target.value)} placeholder="备注可空" /></td>
            <td className="sheet-meta">保存后加入30秒监控</td>
            <td className="sheet-actions"><button type="button" onClick={save} disabled={savingPosition}>{savingPosition ? '保存中' : '保存'}</button></td>
          </tr>
          <tr className="excel-header-row">
            <th className="row-index">3</th>
            <td>最近方向</td>
            <td>主力在不在</td>
            <td>阶段</td>
            <td>持仓/候选</td>
            <td>现价/盈亏</td>
            <td>低吸/反抽</td>
            <td>触发信号</td>
            <td>防守/止盈</td>
            <td>撤退规则</td>
            <td>动作</td>
          </tr>
          {holdings.map((holding, index) => (
            <tr key={`holding-${holding.code}`} className="holding-row">
              <th className="row-index">{index + 4}</th>
              <td>{index === 0 ? formatDirection(direction) : ''}</td>
              <td>{index === 0 ? formatCapital(status, direction) : ''}</td>
              <td>{index === 0 ? formatPhase(direction) : ''}</td>
              <td>{formatHoldingName(holding)}</td>
              <td>{formatHoldingPrice(holding)}</td>
              <td>{formatHoldingRebound(holding)}</td>
              <td>{formatHoldingMainForce(holding)}</td>
              <td>{formatHoldingRisk(holding)}</td>
              <td>{holding.exit_plan}</td>
              <td>{formatHoldingAction(holding, onDeletePosition, deletingPosition)}</td>
            </tr>
          ))}
          <tr className="excel-header-row subtle-header">
            <th className="row-index">{holdings.length + 4}</th>
            <td colSpan={10}>空仓候选：只有价格、方向、承接同时满足才考虑小仓试错</td>
          </tr>
          {candidateRows.map((stock, index) => (
            <tr key={stock?.code ?? `empty-${index}`}>
              <th className="row-index">{holdings.length + index + 5}</th>
              <td>{holdings.length === 0 && index === 0 ? formatDirection(direction) : ''}</td>
              <td>{holdings.length === 0 && index === 0 ? formatCapital(status, direction) : ''}</td>
              <td>{holdings.length === 0 && index === 0 ? formatPhase(direction) : ''}</td>
              <td>{stock ? formatStock(stock) : '暂无可抄底股票'}</td>
              <td>{stock ? formatPriceCell(stock) : '-'}</td>
              <td>{stock ? formatZone(stock) : '-'}</td>
              <td>{stock?.execution?.trigger_signal ?? '-'}</td>
              <td>{stock ? formatRiskCell(stock) : '-'}</td>
              <td>{stock ? formatExitCell(stock) : '-'}</td>
              <td>{stock ? formatActionCell(stock) : '等待'}</td>
            </tr>
          ))}
          {errorMessage && (
            <tr>
              <th className="row-index">{holdings.length + candidateRows.length + 5}</th>
              <td className="sheet-error" colSpan={10}>{errorMessage}</td>
            </tr>
          )}
        </tbody>
      </table>
    </main>
  );
}

function formatAiDirectionSummary(decision?: QuantDecisionResponse) {
  const summary = decision?.ai_direction_summaries?.[0];
  if (!summary) return null;
  return <span className="ai-direction-summary">AI {summary.title}：{summary.summary}</span>;
}

function pickStocks(items: QuantStockDecision[]): QuantStockDecision[] {
  const actionRank: Record<string, number> = {
    BUY_PROBE: 0,
    WAIT_CONFIRMATION: 1,
    WAIT_BUY_ZONE: 2,
    WAIT_PULLBACK: 3,
    DO_NOT_CHASE: 4,
    OBSERVE_NEXT_DAY: 5,
    VERIFY_ONLY: 6,
    VERIFY_DIRECTION: 7,
    AVOID: 8,
    WATCH: 9
  };
  return [...items]
    .filter((item) => item.code && item.name)
    .sort((a, b) => (actionRank[a.action] ?? 50) - (actionRank[b.action] ?? 50) || b.bottom_score - a.bottom_score || b.score - a.score)
    .slice(0, 6);
}

function formatDirection(direction?: QuantDirectionDecision) {
  return (
    <>
      <strong>{direction?.direction_label ?? '暂无方向'}</strong>
      <span>{direction ? `7日 ${formatMaybeScore(direction.seven_day_score)} / 主线 ${formatMaybeScore(direction.mainline_probability)}` : '-'}</span>
    </>
  );
}

function formatCapital(status: { label: string; kind: string }, direction?: QuantDirectionDecision) {
  return (
    <>
      <strong className={`capital-${status.kind}`}>{status.label}</strong>
      <span>驻留 {formatMaybeScore(direction?.residency_score)} / 承接 {formatMaybeScore(direction?.retention_score)}</span>
    </>
  );
}

function formatPhase(direction?: QuantDirectionDecision) {
  return (
    <>
      <strong>{direction?.phase_label ?? '无数据'}</strong>
      <span>{direction?.confidence ? `置信 ${confidenceLabel(direction.confidence)}` : '-'}</span>
    </>
  );
}

function formatHoldingName(item: QuantHoldingDecision) {
  return (
    <>
      <strong>持仓 {item.code} {item.name}</strong>
      <span>成本 {formatPrice(item.entry_price)} / 买入日 {item.entry_date ?? '-'}</span>
    </>
  );
}

function formatHoldingPrice(item: QuantHoldingDecision) {
  const pnl = item.floating_profit_pct == null ? '-' : `${item.floating_profit_pct.toFixed(2)}%`;
  const amount = item.floating_profit_amount == null ? null : ` / 盈亏 ${item.floating_profit_amount.toFixed(2)}`;
  return (
    <>
      <strong>{formatPrice(item.current_price)}</strong>
      <span className={pnl.startsWith('-') ? 'loss-text' : 'profit-text'}>浮盈亏 {pnl}{amount}</span>
    </>
  );
}

function formatHoldingRebound(item: QuantHoldingDecision) {
  return (
    <>
      <strong>反抽 {formatPrice(item.rebound_reduce_price)}</strong>
      <span>{item.can_add_position ? '允许极小幅滚动' : '不补仓'}</span>
    </>
  );
}

function formatHoldingMainForce(item: QuantHoldingDecision) {
  return (
    <>
      <strong>{mainForceLabel(item.main_force_state)}</strong>
      <span>{directionMatchLabel(item.direction_match)} {item.related_direction_label ?? ''}</span>
    </>
  );
}

function formatHoldingRisk(item: QuantHoldingDecision) {
  return (
    <>
      <strong>弱防 {formatPrice(item.weak_exit_price)}</strong>
      <span>止损 {formatPrice(item.stop_price)} / 止盈 {formatPrice(item.take_profit_price)}</span>
    </>
  );
}

function formatHoldingAction(item: QuantHoldingDecision, onDelete: (code: string) => void, deleting: boolean) {
  return (
    <>
      <strong className={`holding-action holding-${item.risk_level}`}>{item.action_label}</strong>
      <span>{item.position_plan}</span>
      {item.ai_risk_review ? <span className={`ai-risk ai-risk-${item.ai_risk_review.risk_level}`}>AI风险 {riskLevelLabel(item.ai_risk_review.risk_level)}：{item.ai_risk_review.conclusion}</span> : null}
      <button type="button" className="link-button" onClick={() => onDelete(item.code)} disabled={deleting}>删除持仓</button>
    </>
  );
}

function formatStock(item: QuantStockDecision) {
  const board = item.board_name ? ` / ${item.board_name}` : '';
  return (
    <>
      <strong>{item.bottom_label} {item.code} {item.name}</strong>
      <span>{stockRoleLabel(item.verifier_role)} / 抄底 {formatScore(item.bottom_score)} / 强度 {formatScore(item.score)}{board}</span>
    </>
  );
}

function formatPriceCell(item: QuantStockDecision) {
  const change = item.change_pct == null ? '-' : `${item.change_pct.toFixed(2)}%`;
  const inflow = item.main_net_inflow_pct == null ? '-' : `${item.main_net_inflow_pct.toFixed(2)}%`;
  return (
    <>
      <strong>{formatPrice(item.price)}</strong>
      <span>涨跌 {change} / 净流 {inflow}</span>
    </>
  );
}

function formatZone(item: QuantStockDecision) {
  const execution = item.execution;
  return (
    <>
      <strong>{formatRange(execution?.buy_zone_low, execution?.buy_zone_high)}</strong>
      <span>超过 {formatPrice(execution?.avoid_above)} 不买</span>
    </>
  );
}

function formatRiskCell(item: QuantStockDecision) {
  const execution = item.execution;
  return (
    <>
      <strong>防守 {formatPrice(execution?.stop_price)}</strong>
      <span>止盈 {formatPrice(execution?.take_profit_price)}</span>
    </>
  );
}

function formatExitCell(item: QuantStockDecision) {
  const execution = item.execution;
  return (
    <>
      <strong>主力走弱先减仓</strong>
      <span>{execution?.reduce_signal ?? '-'}</span>
      <span>{execution?.hard_exit_signal ?? execution?.invalidation_signal ?? '-'}</span>
    </>
  );
}

function formatActionCell(item: QuantStockDecision) {
  const execution = item.execution;
  return (
    <>
      <strong className={`action-${execution?.decision_state ?? 'monitor'}`}>{execution?.decision_label ?? actionLabel(item.action)}</strong>
      <span>{execution?.decision_reason ?? item.operation}</span>
      {execution?.position_plan ? <span>{execution.position_plan}</span> : null}
      {execution?.ai_risk_review ? <span className={`ai-risk ai-risk-${execution.ai_risk_review.risk_level}`}>AI风险 {riskLevelLabel(execution.ai_risk_review.risk_level)}：{execution.ai_risk_review.conclusion}</span> : null}
    </>
  );
}

function mainForceLabel(value: string) {
  const map: Record<string, string> = { present: '主力在', watch: '试探', weak: '走弱', left: '疑似撤退', unknown: '未知' };
  return map[value] ?? value;
}

function directionMatchLabel(value: string) {
  const map: Record<string, string> = { frontline: '前排方向', related: '相关方向', not_frontline: '非前排', unknown: '未知' };
  return map[value] ?? value;
}

function riskLevelLabel(value: string | null | undefined): string {
  const map: Record<string, string> = { low: '低', medium: '中', high: '高', unknown: '未知' };
  return value ? map[value] ?? value : '未知';
}

function stockRoleLabel(value: string | null | undefined): string {
  const map: Record<string, string> = { leader: '龙头', second_leader: '二龙', expansion: '扩散' };
  return value ? map[value] ?? value : '候选';
}

function capitalStatus(direction?: QuantDirectionDecision): { label: string; kind: string } {
  if (!direction || direction.phase === 'no_direction') return { label: '不在', kind: 'off' };
  const probability = direction.mainline_probability ?? direction.phase_score ?? 0;
  const residency = direction.residency_score ?? 0;
  const retention = direction.retention_score ?? 0;
  if (probability >= 70 && residency >= 60 && retention >= 55) return { label: '在', kind: 'on' };
  if (probability >= 55 && (residency >= 45 || retention >= 45)) return { label: '试探', kind: 'test' };
  if (probability >= 40) return { label: '观察', kind: 'watch' };
  return { label: '不在', kind: 'off' };
}

function confidenceLabel(value: string): string {
  const map: Record<string, string> = { high: '高', medium: '中', 'medium-low': '中低', low: '低' };
  return map[value] ?? value;
}

function actionLabel(value: string | null | undefined): string {
  const map: Record<string, string> = {
    BUY_PROBE: '可试仓',
    WAIT_CONFIRMATION: '等承接',
    WAIT_BUY_ZONE: '等低吸区',
    WATCH_LOW_BUY: '等低吸',
    WAIT_PULLBACK: '等回踩',
    DO_NOT_CHASE: '不追高',
    OBSERVE_NEXT_DAY: '看次日',
    VERIFY_ONLY: '只验证',
    VERIFY_DIRECTION: '验证方向',
    AVOID: '回避',
    WATCH: '观察'
  };
  return value ? map[value] ?? value : '等待';
}

function formatMaybeScore(value: number | null | undefined): string {
  return value == null ? '-' : formatScore(value);
}

function formatPrice(value: number | null | undefined): string {
  return value == null ? '-' : value.toFixed(2);
}

function formatRange(low: number | null | undefined, high: number | null | undefined): string {
  if (low == null || high == null) return '-';
  return `${low.toFixed(2)} - ${high.toFixed(2)}`;
}

function todayText() {
  return new Date().toISOString().slice(0, 10);
}
