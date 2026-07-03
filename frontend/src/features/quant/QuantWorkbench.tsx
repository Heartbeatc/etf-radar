import { Button, Empty, Tag, Typography } from 'antd';
import { LogoutOutlined, ReloadOutlined } from '@ant-design/icons';
import type { QuantDecisionResponse, QuantDirectionDecision, QuantEtfDecision } from '../../types';
import { formatDateTime, formatScore } from './formatters';

const { Text } = Typography;

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

  return (
    <main className="decision-table-page">
      <section className="decision-table-wrap">
        <div className="decision-caption">
          <div>
            <Text className="caption-title">主线方向表</Text>
            <Text className="caption-time">{formatDateTime(decision?.generated_at)}</Text>
          </div>
          <div className="decision-actions">
            <Button size="small" icon={<ReloadOutlined />} loading={refreshing} onClick={onRefresh} aria-label="刷新" />
            <Button size="small" icon={<LogoutOutlined />} onClick={onLogout} aria-label="退出" />
          </div>
        </div>

        <table className="direction-table">
          <thead>
            <tr>
              <th>最近方向</th>
              <th>主力在不在</th>
              <th>目前阶段</th>
              <th>强关联 ETF</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td data-label="最近方向">
                <strong>{direction?.direction_label ?? '暂无方向'}</strong>
                {direction?.mainline_probability != null && <span className="subline">主线 {formatScore(direction.mainline_probability)}</span>}
              </td>
              <td data-label="主力在不在">
                <CapitalStatus direction={direction} />
              </td>
              <td data-label="目前阶段">
                <strong>{direction?.phase_label ?? '无数据'}</strong>
                {direction?.confidence && <span className="subline">置信 {confidenceLabel(direction.confidence)}</span>}
              </td>
              <td data-label="强关联 ETF">
                <EtfList etfs={etfs} />
              </td>
            </tr>
          </tbody>
        </table>

        {errorMessage && <div className="table-error">{errorMessage}</div>}
        {!decision && !errorMessage && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无量化决策" />}
      </section>
    </main>
  );
}

function CapitalStatus({ direction }: { direction?: QuantDirectionDecision }) {
  const status = capitalStatus(direction);
  return (
    <div className="capital-cell">
      <Tag color={status.color}>{status.label}</Tag>
      <span className="subline">驻留 {formatMaybeScore(direction?.residency_score)} / 承接 {formatMaybeScore(direction?.retention_score)}</span>
    </div>
  );
}

function EtfList({ etfs }: { etfs: QuantEtfDecision[] }) {
  if (!etfs.length) return <span className="muted">暂无强关联 ETF</span>;
  return (
    <div className="etf-list">
      {etfs.map((item) => (
        <span className="etf-pill" key={item.code}>
          <b>{item.code}</b>
          <span>{item.name}</span>
          <em>{roleLabel(item.role)}</em>
        </span>
      ))}
    </div>
  );
}

function pickEtfs(items: QuantEtfDecision[]): QuantEtfDecision[] {
  return [...items]
    .filter((item) => item.code && item.name)
    .sort((a, b) => b.score - a.score)
    .slice(0, 4);
}

function capitalStatus(direction?: QuantDirectionDecision): { label: string; color: string } {
  if (!direction || direction.phase === 'no_direction') return { label: '不在', color: 'default' };
  const probability = direction.mainline_probability ?? direction.phase_score ?? 0;
  const residency = direction.residency_score ?? 0;
  const retention = direction.retention_score ?? 0;
  if (probability >= 70 && residency >= 60 && retention >= 55) return { label: '在', color: 'green' };
  if (probability >= 55 && (residency >= 45 || retention >= 45)) return { label: '试探', color: 'blue' };
  if (probability >= 40) return { label: '观察', color: 'orange' };
  return { label: '不在', color: 'default' };
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
