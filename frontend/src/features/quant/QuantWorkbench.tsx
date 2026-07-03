import { useMemo, type ReactNode } from 'react';
import { Button, Empty, Input, Space, Switch, Tag, Typography } from 'antd';
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  ExclamationCircleOutlined,
  ReloadOutlined
} from '@ant-design/icons';
import type {
  ActionDecisionItem,
  AiStatus,
  AiSummaryKind,
  AiSummaryReport,
  HealthResponse,
  IntegrationStatus,
  Position,
  PythonQuantStackReport,
  QuantAlgorithmReport,
  QuantExecutionAdvice,
  QuantFrameworkResponse,
  QuantMaturityReport,
  QuantSelfAuditReport,
  QuantValidationReport,
  WebSessionInfo
} from '../../types';
import {
  actionColor,
  actionLabel,
  decisionStateLabel,
  evidenceLabel,
  executionRank,
  executionShortText,
  formatDateTime,
  formatPercentNumber,
  formatPrice,
  formatScore,
  formatSignedPercent,
  frameworkConclusion,
  frameworkStageLabel,
  isPriceInLowBuyZone,
  lowBuyScoreText,
  marketStatusLabel,
  maturityGradeLabel,
  pickPrimaryExecution,
  priceRange
} from './formatters';

const { Text } = Typography;

export interface PositionDraft {
  code: string;
  entry: string;
  shares: string;
  note: string;
}

interface QuantWorkbenchProps {
  health?: HealthResponse;
  session?: WebSessionInfo;
  framework?: QuantFrameworkResponse;
  quantValidation?: QuantValidationReport;
  quantMaturity?: QuantMaturityReport;
  quantAlgorithms?: QuantAlgorithmReport;
  quantSelfAudit?: QuantSelfAuditReport;
  pythonQuantStack?: PythonQuantStackReport;
  positions: Position[];
  integrations: IntegrationStatus[];
  aiStatus?: AiStatus;
  aiSummaries?: AiSummaryReport;
  draft: PositionDraft;
  setDraft: (draft: PositionDraft) => void;
  onSavePosition: () => void;
  savingPosition: boolean;
  onDeletePosition: (code: string) => void;
  deletingPosition: boolean;
  deletingCode: string | null;
  onRefreshFramework: () => void;
  refreshingFramework: boolean;
  onToggleAi: (enabled: boolean) => void;
  togglingAi: boolean;
  onGenerateAi: (kind: AiSummaryKind | string) => void;
  generatingAi: boolean;
  generatingKind: AiSummaryKind | string | null;
  errorMessage: string | null;
}

export function QuantWorkbench(props: QuantWorkbenchProps) {
  const primary = useMemo(() => pickPrimaryExecution(props.framework, props.positions), [props.framework, props.positions]);
  const focusItems = useMemo(
    () => [...(props.framework?.execution_plan ?? [])].sort((a, b) => executionRank(a) - executionRank(b)).slice(0, 3),
    [props.framework]
  );
  const heldCodes = new Set(props.positions.map((item) => item.code));
  const positionActions = (props.framework?.final_actions ?? []).filter((item) => item.has_position || heldCodes.has(item.code));
  const topInsight = [...(props.framework?.insights ?? [])].sort((a, b) => b.confidence_score - a.confidence_score)[0];
  const topDirection = topInsight?.name ?? props.framework?.universe.find((item) => item.asset_type === 'direction' && item.selected)?.name ?? '暂无确认主线';
  const latestAi = props.aiSummaries?.summaries?.[0] ?? null;
  const liveReady = Boolean(props.framework?.validation.live_trading_ready);
  const evidenceStrength = props.framework?.validation.evidence_strength;
  const maturityScore = props.quantMaturity?.score ?? null;

  return (
    <main className="minimal-terminal">
      <section className={`decision-stage tone-${toneFromSide(primary.side)}`}>
        <div className="stage-copy">
          <div className="stage-kicker">
            <span>Quant Radar</span>
            <span>{marketStatusLabel(props.framework?.market_status)}</span>
            <span>{formatDateTime(props.framework?.generated_at)}</span>
          </div>
          <h1>{heroTitle(primary.side, primary.action)}</h1>
          <p>{frameworkConclusion(props.framework, primary)}</p>
          <div className="stage-tags">
            <ActionTag action={primary.action} side={primary.side} />
            <StatusPill tone={liveReady ? 'good' : 'warn'}>{frameworkStageLabel(props.framework)}</StatusPill>
            <StatusPill tone={evidenceStrength === 'high' ? 'good' : evidenceStrength === 'medium' ? 'neutral' : 'warn'}>
              证据 {evidenceLabel(evidenceStrength)}
            </StatusPill>
          </div>
        </div>
        <div className="stage-panel">
          <Text className="meta-label">当前方向</Text>
          <strong>{topDirection}</strong>
          <Text className="quiet-text">{primary.note}</Text>
        </div>
      </section>

      <section className="signal-row">
        <SignalTile label="模型成熟度" value={maturityScore == null ? '-' : maturityScore.toFixed(0)} meta={maturityGradeLabel(props.quantMaturity?.grade)} tone={scoreTone(maturityScore)} />
        <SignalTile label="实盘闸门" value={liveReady ? '可执行' : '未就绪'} meta={props.framework?.validation.blockers[0] ?? '研究级验证'} tone={liveReady ? 'good' : 'warn'} />
        <SignalTile label="验证样本" value={props.quantValidation ? props.quantValidation.actionable_records.toFixed(0) : '-'} meta={validationMeta(props.quantValidation)} />
        <SignalTile label="服务" value={props.health?.ok ? '在线' : '检查'} meta={props.errorMessage ?? props.health?.last_error ?? 'normal'} tone={props.health?.ok && !props.errorMessage ? 'good' : 'bad'} />
        <Button className="soft-button" icon={<ReloadOutlined />} loading={props.refreshingFramework} onClick={props.onRefreshFramework}>刷新</Button>
      </section>

      <section className="minimal-section">
        <div className="section-heading">
          <div>
            <Text className="meta-label">Trading Candidates</Text>
            <h2>2 个主 ETF + 1 个备选</h2>
          </div>
          <Text className="quiet-text">只显示当前最值得盯的交易载体</Text>
        </div>
        <div className="candidate-grid">
          {focusItems.map((item, index) => <CandidateCard key={item.code} item={item} index={index} primary={item.code === primary.code} />)}
          {!focusItems.length && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无交易候选" />}
        </div>
      </section>

      <section className="desk-grid">
        <PositionPanel
          positions={props.positions}
          actions={positionActions}
          draft={props.draft}
          setDraft={props.setDraft}
          onSave={props.onSavePosition}
          saving={props.savingPosition}
          onDelete={props.onDeletePosition}
          deleting={props.deletingPosition}
          deletingCode={props.deletingCode}
        />
        <AiBriefPanel
          status={props.aiStatus}
          latest={latestAi}
          onToggle={props.onToggleAi}
          toggling={props.togglingAi}
          onGenerate={props.onGenerateAi}
          generating={props.generatingAi}
          generatingKind={props.generatingKind}
        />
      </section>

      <details className="minimal-details">
        <summary>模型证据与系统状态</summary>
        <div className="evidence-grid">
          <EvidenceCard title="主线证据" items={(topInsight?.evidence ?? props.framework?.insights[0]?.evidence ?? []).slice(0, 4)} empty="暂无主线证据" />
          <EvidenceCard title="反方风险" items={[...(props.quantSelfAudit?.verdict.hard_no ?? []), ...(props.framework?.warnings ?? [])].slice(0, 4)} empty="暂无硬阻断" danger />
          <EvidenceCard title="下一步升级" items={[...(props.quantMaturity?.next_upgrades ?? []), ...(props.pythonQuantStack?.adoption_sequence ?? []), ...(props.quantAlgorithms?.recommended_next ?? [])].slice(0, 5)} empty="暂无升级项" />
          <SystemCard health={props.health} session={props.session} integrations={props.integrations} />
        </div>
      </details>
    </main>
  );
}

function CandidateCard({ item, index, primary }: { item: QuantExecutionAdvice; index: number; primary: boolean }) {
  const blocked = item.blockers.length > 0;
  const inZone = isPriceInLowBuyZone(item);
  const readiness = item.action_score ?? item.low_buy_score ?? null;
  return (
    <article className={`candidate-card tone-${toneFromSide(item.side)} ${primary ? 'is-primary' : ''}`}>
      <div className="candidate-top">
        <Text className="meta-label">{candidateRole(index)}</Text>
        <div className="candidate-tags">
          {primary && <StatusPill tone="neutral">焦点</StatusPill>}
          <ActionTag action={item.action} side={item.side} />
        </div>
      </div>
      <div className="candidate-name">
        <strong>{item.name}</strong>
        <Text className="quiet-text">{item.code} · {decisionStateLabel(item.decision_state)}</Text>
      </div>
      <div className="price-band">
        <div>
          <Text className="meta-label">当前价</Text>
          <strong>{formatPrice(item.current_price)}</strong>
        </div>
        <div>
          <Text className="meta-label">低吸区</Text>
          <strong>{priceRange(item.trigger_price_low, item.trigger_price_high)}</strong>
        </div>
      </div>
      <div className="mini-metrics">
        <Metric label="动作分" value={formatScore(readiness)} tone={scoreTone(readiness)} />
        <Metric label="低吸分" value={lowBuyScoreText(item.low_buy_score)} tone={scoreTone(item.low_buy_score)} />
        <Metric label="止盈" value={formatPrice(item.take_profit_price)} />
        <Metric label="止损" value={formatPrice(item.stop_price)} tone={item.stop_price ? 'warn' : 'neutral'} />
      </div>
      <div className="condition-line">
        <StatusPill tone={inZone ? 'good' : 'neutral'}>{inZone ? '价格到位' : '等价格'}</StatusPill>
        <StatusPill tone={blocked ? 'bad' : item.blockers.length ? 'warn' : 'good'}>{blocked ? '有阻断' : '风控通过'}</StatusPill>
      </div>
      <p className={blocked ? 'reason danger-text' : 'reason'}>{item.blockers[0] ?? item.decision_reason ?? executionShortText(item)}</p>
    </article>
  );
}

function PositionPanel({ positions, actions, draft, setDraft, onSave, saving, onDelete, deleting, deletingCode }: { positions: Position[]; actions: ActionDecisionItem[]; draft: PositionDraft; setDraft: (draft: PositionDraft) => void; onSave: () => void; saving: boolean; onDelete: (code: string) => void; deleting: boolean; deletingCode: string | null }) {
  return (
    <section className="minimal-section position-section">
      <div className="section-heading compact">
        <div>
          <Text className="meta-label">Portfolio</Text>
          <h2>{positions.length ? '持仓动作' : '当前空仓'}</h2>
        </div>
        <StatusPill tone={positions.length ? 'neutral' : 'warn'}>{positions.length ? `${positions.length} 个持仓` : '等待触发'}</StatusPill>
      </div>
      <div className="position-form minimal-form">
        <Input value={draft.code} onChange={(event) => setDraft({ ...draft, code: event.target.value })} placeholder="代码" maxLength={6} />
        <Input value={draft.entry} onChange={(event) => setDraft({ ...draft, entry: event.target.value })} placeholder="成本价" type="number" inputMode="decimal" />
        <Input value={draft.shares} onChange={(event) => setDraft({ ...draft, shares: event.target.value })} placeholder="份额" type="number" inputMode="decimal" />
        <Button type="primary" loading={saving} onClick={onSave}>保存</Button>
      </div>
      <Input value={draft.note} onChange={(event) => setDraft({ ...draft, note: event.target.value })} placeholder="备注" />
      <div className="position-list minimal-list">
        {positions.map((position) => <PositionRow key={position.code} position={position} action={actions.find((item) => item.code === position.code)} onDelete={onDelete} deleting={deleting && deletingCode === position.code} />)}
        {!positions.length && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="空仓，等待候选 ETF 满足契约" />}
      </div>
    </section>
  );
}

function PositionRow({ position, action, onDelete, deleting }: { position: Position; action?: ActionDecisionItem; onDelete: (code: string) => void; deleting: boolean }) {
  return (
    <div className="position-row-minimal">
      <div>
        <Text strong>{action?.name ?? position.code}</Text>
        <Text className="quiet-text">成本 {formatPrice(position.entry_price)} · 当前 {formatPrice(action?.current_price)} · 浮盈 <PercentText value={action?.floating_profit_pct} /></Text>
        <Text className="quiet-text">止盈 {formatPrice(action?.first_take_profit_price)} · 防守 {formatPrice(action?.effective_exit_price)}</Text>
      </div>
      <Space size={6} wrap>
        {action && <ActionTag action={action.action} side={action.side} />}
        <Button danger size="small" loading={deleting} onClick={() => onDelete(position.code)}>删除</Button>
      </Space>
    </div>
  );
}

function AiBriefPanel({ status, latest, onToggle, toggling, onGenerate, generating, generatingKind }: { status?: AiStatus; latest: AiSummaryReport['summaries'][number] | null; onToggle: (enabled: boolean) => void; toggling: boolean; onGenerate: (kind: AiSummaryKind | string) => void; generating: boolean; generatingKind: AiSummaryKind | string | null }) {
  return (
    <section className="minimal-section ai-section">
      <div className="section-heading compact">
        <div>
          <Text className="meta-label">AI</Text>
          <h2>{latest?.title ?? '等待窗口总结'}</h2>
        </div>
        <Switch checked={Boolean(status?.enabled)} loading={toggling} onChange={onToggle} disabled={!status?.configured} checkedChildren="开" unCheckedChildren="关" />
      </div>
      <p className="ai-summary-text">{latest?.summary ?? 'AI 只在开盘竞价、午间、尾盘等关键窗口调用，实时信号由规则引擎负责。'}</p>
      <div className="ai-actions">
        <Text className="quiet-text">{status ? `${status.calls_used_today}/${status.daily_call_limit} calls` : '-'}</Text>
        <Space size={[6, 6]} wrap>
          {(status?.windows ?? []).map((item) => (
            <Button key={item.kind} size="small" onClick={() => onGenerate(item.kind)} loading={generating && generatingKind === item.kind} disabled={!status?.enabled || !status.configured}>
              {item.title}
            </Button>
          ))}
        </Space>
      </div>
    </section>
  );
}

function EvidenceCard({ title, items, empty, danger = false }: { title: string; items: string[]; empty: string; danger?: boolean }) {
  return (
    <section className="evidence-card">
      <Text className="meta-label">{title}</Text>
      <div className="minimal-list small">
        {items.map((item, index) => <Text key={`${title}-${index}`} className={danger ? 'danger-text' : 'quiet-text'}>{item}</Text>)}
        {!items.length && <Text className="quiet-text">{empty}</Text>}
      </div>
    </section>
  );
}

function SystemCard({ health, session, integrations }: { health?: HealthResponse; session?: WebSessionInfo; integrations: IntegrationStatus[] }) {
  const okCount = integrations.filter((item) => item.ok).length;
  return (
    <section className="evidence-card">
      <Text className="meta-label">系统</Text>
      <div className="system-grid-minimal">
        <Metric label="后端" value={health?.ok ? 'online' : 'check'} tone={health?.ok ? 'good' : 'bad'} />
        <Metric label="会话" value={session?.username ?? '-'} />
        <Metric label="基础设施" value={`${okCount}/${integrations.length || 0}`} tone={okCount === integrations.length ? 'good' : 'warn'} />
      </div>
    </section>
  );
}

function SignalTile({ label, value, meta, tone = 'neutral' }: { label: string; value: ReactNode; meta?: ReactNode; tone?: Tone }) {
  return (
    <div className={`signal-tile tone-${tone}`}>
      <Text className="meta-label">{label}</Text>
      <strong>{value}</strong>
      {meta && <Text className="quiet-text">{meta}</Text>}
    </div>
  );
}

function Metric({ label, value, tone = 'neutral' }: { label: string; value: ReactNode; tone?: Tone }) {
  return (
    <div className={`metric-mini tone-${tone}`}>
      <Text className="meta-label">{label}</Text>
      <strong>{value}</strong>
    </div>
  );
}

function StatusPill({ children, tone = 'neutral' }: { children: ReactNode; tone?: Tone }) {
  const icon = tone === 'good' ? <CheckCircleOutlined /> : tone === 'bad' ? <CloseCircleOutlined /> : tone === 'warn' ? <ExclamationCircleOutlined /> : null;
  return <span className={`status-pill tone-${tone}`}>{icon}{children}</span>;
}

function ActionTag({ action, side }: { action: string; side: string }) {
  return <Tag color={actionColor(side)}>{actionLabel(action)}</Tag>;
}

function PercentText({ value }: { value: number | null | undefined }) {
  if (value == null) return <Text className="quiet-text">-</Text>;
  return <Text className={value >= 0 ? 'num-up' : 'num-down'}>{formatSignedPercent(value)}</Text>;
}

type Tone = 'good' | 'warn' | 'bad' | 'neutral';

function scoreTone(value: number | null | undefined): Tone {
  if (value == null) return 'neutral';
  if (value >= 75) return 'good';
  if (value >= 55) return 'neutral';
  if (value >= 35) return 'warn';
  return 'bad';
}

function toneFromSide(side: string): Tone {
  if (side === 'BUY' || side === 'HOLD') return 'good';
  if (side === 'SELL' || side === 'AVOID') return 'bad';
  return 'neutral';
}

function heroTitle(side: string, action: string): string {
  if (side === 'BUY') return '可以低吸，但只按仓位契约执行';
  if (side === 'SELL') return '先处理卖出、止盈或风控';
  if (side === 'HOLD') return '继续持有，跟踪退出条件';
  if (action === 'AVOID') return '当前回避，不开新仓';
  return '当前等待，不抢跑';
}

function candidateRole(index: number): string {
  if (index === 0) return '主 ETF 1';
  if (index === 1) return '主 ETF 2';
  return '备选 ETF';
}

function validationMeta(report?: QuantValidationReport): string {
  if (!report) return '-';
  const t3 = report.horizon_metrics.find((item) => item.horizon_days === 3);
  if (!t3) return evidenceLabel(report.evidence_strength);
  return `T+3 ${formatPercentNumber(t3.win_rate_pct)}`;
}
