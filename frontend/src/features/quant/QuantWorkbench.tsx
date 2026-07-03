import type { QuantDecisionResponse, QuantDirectionDecision, QuantEtfDecision } from '../../types';
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
  const etfs = pickEtfs(decision?.etfs ?? []);
  const status = capitalStatus(direction);

  return (
    <main className="excel-page">
      <table className="excel-sheet" aria-label="主线方向表">
        <colgroup>
          <col className="row-index-col" />
          <col className="direction-col" />
          <col className="capital-col" />
          <col className="phase-col" />
          <col className="etf-col" />
        </colgroup>
        <thead>
          <tr className="excel-letters">
            <th></th>
            <th>A</th>
            <th>B</th>
            <th>C</th>
            <th>D</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <th className="row-index">1</th>
            <td className="sheet-title">主线方向表</td>
            <td className="sheet-meta">{formatDateTime(decision?.generated_at)}</td>
            <td className="sheet-meta">30 秒刷新</td>
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
            <td>强关联 ETF</td>
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
            <td>{formatEtfs(etfs)}</td>
          </tr>
          {errorMessage && (
            <tr>
              <th className="row-index">4</th>
              <td className="sheet-error" colSpan={4}>{errorMessage}</td>
            </tr>
          )}
        </tbody>
      </table>
    </main>
  );
}

function pickEtfs(items: QuantEtfDecision[]): QuantEtfDecision[] {
  return [...items]
    .filter((item) => item.code && item.name)
    .sort((a, b) => b.score - a.score)
    .slice(0, 4);
}

function formatEtfs(items: QuantEtfDecision[]): string {
  if (!items.length) return '暂无强关联 ETF';
  return items.map((item) => `${item.code} ${item.name}(${roleLabel(item.role)})`).join('；');
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

function roleLabel(value: string | null): string {
  const map: Record<string, string> = {
    main: '主',
    backup: '备',
    watch: '看',
    held_position: '持',
    monitor: '监'
  };
  return value ? map[value] ?? value : '候';
}

function formatMaybeScore(value: number | null | undefined): string {
  return value == null ? '-' : formatScore(value);
}
