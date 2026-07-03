import type { QuantDecisionResponse, QuantDirectionDecision, QuantStockDecision } from '../../types';
import { formatDateTime, formatScore } from './formatters';

interface QuantWorkbenchProps {
  decision?: QuantDecisionResponse;
  onRefresh: () => void;
  refreshing: boolean;
  onLogout: () => void;
  errorMessage: string | null;
}

export function QuantWorkbench({ decision, onRefresh, refreshing, onLogout, errorMessage }: QuantWorkbenchProps) {
  const direction = decision?.direction;
  const stocks = pickStocks(decision?.stocks ?? []);
  const status = capitalStatus(direction);
  const primaryAction = stocks[0]?.operation ?? decision?.conclusion ?? '等待数据';

  return (
    <main className="excel-page">
      <table className="excel-sheet" aria-label="A股主线个股表">
        <colgroup>
          <col className="row-index-col" />
          <col className="direction-col" />
          <col className="capital-col" />
          <col className="phase-col" />
          <col className="stock-col" />
          <col className="action-col" />
        </colgroup>
        <thead>
          <tr className="excel-letters">
            <th></th>
            <th>A</th>
            <th>B</th>
            <th>C</th>
            <th>D</th>
            <th>E</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <th className="row-index">1</th>
            <td className="sheet-title">A股主线个股表</td>
            <td className="sheet-meta">{formatDateTime(decision?.generated_at)}</td>
            <td className="sheet-meta">30 秒刷新</td>
            <td className="sheet-meta">{decision?.market_status ?? '-'}</td>
            <td className="sheet-actions">
              <button type="button" onClick={onRefresh} disabled={refreshing}>{refreshing ? '刷新中' : '刷新'}</button>
              <button type="button" onClick={onLogout}>退出</button>
            </td>
          </tr>
          <tr className="excel-header-row">
            <th className="row-index">2</th>
            <td>最近方向</td>
            <td>主力在不在</td>
            <td>目前阶段</td>
            <td>龙头/二龙头</td>
            <td>动作</td>
          </tr>
          <tr>
            <th className="row-index">3</th>
            <td>
              <strong>{direction?.direction_label ?? '暂无方向'}</strong>
              <span>{direction?.mainline_probability != null ? `主线 ${formatScore(direction.mainline_probability)}` : '-'}</span>
            </td>
            <td>
              <strong className={`capital-${status.kind}`}>{status.label}</strong>
              <span>驻留 {formatMaybeScore(direction?.residency_score)} / 承接 {formatMaybeScore(direction?.retention_score)}</span>
            </td>
            <td>
              <strong>{direction?.phase_label ?? '无数据'}</strong>
              <span>{direction?.confidence ? `置信 ${confidenceLabel(direction.confidence)}` : '-'}</span>
            </td>
            <td>{formatStocks(stocks)}</td>
            <td>
              <strong>{actionLabel(stocks[0]?.action)}</strong>
              <span>{primaryAction}</span>
            </td>
          </tr>
          {errorMessage && (
            <tr>
              <th className="row-index">4</th>
              <td className="sheet-error" colSpan={5}>{errorMessage}</td>
            </tr>
          )}
        </tbody>
      </table>
    </main>
  );
}

function pickStocks(items: QuantStockDecision[]): QuantStockDecision[] {
  return [...items]
    .filter((item) => item.code && item.name)
    .sort((a, b) => b.score - a.score)
    .slice(0, 5);
}

function formatStocks(items: QuantStockDecision[]): string {
  if (!items.length) return '暂无龙头/二龙头样本';
  return items.map((item) => {
    const change = item.change_pct == null ? '-' : `${item.change_pct.toFixed(2)}%`;
    const board = item.board_name ? `/${item.board_name}` : '';
    return `${stockRoleLabel(item.verifier_role)} ${item.code} ${item.name}${board} ${change} 分${formatScore(item.score)}`;
  }).join('；');
}

function stockRoleLabel(value: string | null | undefined): string {
  const map: Record<string, string> = {
    leader: '龙头',
    second_leader: '二龙',
    expansion: '扩散'
  };
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
  const map: Record<string, string> = {
    high: '高',
    medium: '中',
    'medium-low': '中低',
    low: '低'
  };
  return map[value] ?? value;
}

function actionLabel(value: string | null | undefined): string {
  const map: Record<string, string> = {
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
