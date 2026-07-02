import { useMemo, type ReactNode } from 'react';
import { Button, Empty, Input, Space, Switch, Tag, Tooltip, Typography } from 'antd';
import {
  ApiOutlined,
  BulbOutlined,
  CheckCircleOutlined,
  LineChartOutlined,
  ReloadOutlined,
  SafetyCertificateOutlined,
  ThunderboltOutlined,
  UserOutlined
} from '@ant-design/icons';
import type {
  ActionDecisionItem,
  AiStatus,
  AiSummaryKind,
  AiSummaryReport,
  HealthResponse,
  IntegrationStatus,
  Position,
  PythonQuantCapability,
  PythonQuantStackReport,
  QuantAlgorithmCandidate,
  QuantAlgorithmReport,
  QuantAuditFinding,
  QuantExecutionAdvice,
  QuantExecutionCondition,
  QuantFeatureRow,
  QuantFrameworkResponse,
  QuantInsight,
  QuantMaturityReport,
  QuantProductionGate,
  QuantSelfAuditReport,
  QuantPortfolioTarget,
  QuantRiskAdjustment,
  QuantUniverseAsset,
  QuantValidationReport,
  WebSessionInfo
} from '../../types';
import {
  actionColor,
  actionLabel,
  assetTypeLabel,
  conditionStatusClass,
  conditionStatusLabel,
  decisionStateLabel,
  directionColor,
  etfRegionLabel,
  evidenceColor,
  evidenceLabel,
  executionRank,
  executionShortText,
  formatDateTime,
  formatDelta,
  formatPercentNumber,
  formatPrice,
  formatScore,
  formatSignedPercent,
  frameworkConclusion,
  frameworkStageLabel,
  insightTypeLabel,
  isPriceInLowBuyZone,
  lowBuyScoreText,
  marketStatusLabel,
  maturityGradeLabel,
  maturityStatusClass,
  maturityStatusLabel,
  pickPrimaryExecution,
  priceRange,
  rebalanceLabel,
  riskColor,
  riskLabel,
  roleLabel,
  scoreColor
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
  const focusItems = useMemo(() => [...(props.framework?.execution_plan ?? [])].sort((a, b) => executionRank(a) - executionRank(b)).slice(0, 3), [props.framework]);
  const selectedUniverse = (props.framework?.universe ?? []).filter((item) => item.selected);
  const heldCodes = new Set(props.positions.map((item) => item.code));
  const positionActions = (props.framework?.final_actions ?? []).filter((item) => item.has_position || heldCodes.has(item.code));

  return (
    <main className="quant-terminal">
      <QuantCommandBar
        health={props.health}
        framework={props.framework}
        quantValidation={props.quantValidation}
        quantMaturity={props.quantMaturity}
        errorMessage={props.errorMessage}
        refreshing={props.refreshingFramework}
        onRefresh={props.onRefreshFramework}
      />

      <section className={`quant-decision-strip side-${primary.side.toLowerCase()}`}>
        <div className="decision-copy">
          <Text className="eyebrow">Decision Engine</Text>
          <h1>{frameworkConclusion(props.framework, primary)}</h1>
          <div className="status-line">
            <ActionTag action={primary.action} side={primary.side} />
            <Tag color={evidenceColor(props.framework?.validation.evidence_strength)}>证据 {evidenceLabel(props.framework?.validation.evidence_strength)}</Tag>
            <Tag color={props.quantSelfAudit?.verdict.mature ? 'green' : 'red'}>{props.quantSelfAudit?.verdict.mature ? '资金级候选' : '资金级未过'}</Tag>
            <Text className="muted">{frameworkStageLabel(props.framework)} · {formatDateTime(props.framework?.generated_at)}</Text>
          </div>
        </div>
        <div className="decision-ticket quant-ticket">
          <Text className="ticket-label">执行焦点</Text>
          <strong>{primary.code ?? '-'}</strong>
          <Text>{primary.note}</Text>
        </div>
      </section>

      <section className="quant-workbench">
        <div className="execution-stack">
          <section className="panel execution-panel">
            <div className="section-title-row">
              <div>
                <Text className="eyebrow">Execution Contract</Text>
                <h2>2 主 ETF + 1 备选，只在契约通过时行动</h2>
              </div>
              <Button size="small" icon={<ReloadOutlined />} loading={props.refreshingFramework} onClick={props.onRefreshFramework}>刷新链路</Button>
            </div>
            <div className="trade-grid quant-trade-grid">
              {focusItems.map((item, index) => <TradeFocusCard key={item.code} item={item} index={index} primary={item.code === primary.code} />)}
              {!focusItems.length && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无交易候选" />}
            </div>
            <SignalValidationStrip report={props.quantValidation} />
          </section>

          <PortfolioRiskPanel targets={props.framework?.portfolio_targets ?? []} risks={props.framework?.risk_adjustments ?? []} />
        </div>

        <div className="model-stack">
          <MaturityPanel report={props.quantMaturity} />
          <ProductionReadinessPanel report={props.quantMaturity} />
          <SelfAuditPanel report={props.quantSelfAudit} />
          <PythonQuantStackPanel report={props.pythonQuantStack} />
          <AlgorithmResearchPanel report={props.quantAlgorithms} />
          <ModelPipelinePanel framework={props.framework} report={props.quantMaturity} />
          <AiPanel status={props.aiStatus} report={props.aiSummaries} onToggle={props.onToggleAi} toggling={props.togglingAi} onGenerate={props.onGenerateAi} generating={props.generatingAi} generatingKind={props.generatingKind} />
        </div>
      </section>

      <section className="operator-grid">
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
        <EvidencePanel features={props.framework?.features ?? []} insights={props.framework?.insights ?? []} />
      </section>

      <details className="detail-drawer audit-drawer">
        <summary>审计区：资产池、验证样本、系统状态</summary>
        <div className="detail-grid">
          <UniversePanel items={selectedUniverse} allItems={props.framework?.universe ?? []} />
          <ValidationPanel framework={props.framework} onRefresh={props.onRefreshFramework} loading={props.refreshingFramework} />
          <SystemPanel health={props.health} session={props.session} framework={props.framework} integrations={props.integrations} />
        </div>
      </details>
    </main>
  );
}

function TradeFocusCard({ item, index, primary }: { item: QuantExecutionAdvice; index: number; primary: boolean }) {
  const role = index === 0 ? '主 ETF 1' : index === 1 ? '主 ETF 2' : '备选 ETF';
  const blocked = item.blockers.length > 0;
  const inZone = isPriceInLowBuyZone(item);
  return (
    <article className={`trade-card side-${item.side.toLowerCase()} ${primary ? 'primary' : ''}`}>
      <div className="trade-card-head">
        <Text className="ticket-label">{role}</Text>
        <Space size={4} wrap>
          {primary && <Tag color="blue">焦点</Tag>}
          <ActionTag action={item.action} side={item.side} />
        </Space>
      </div>
      <div className="trade-identity">
        <strong>{item.name}</strong>
        <Text className="muted">{item.code} · {etfRegionLabel(item.name)} · {decisionStateLabel(item.decision_state)}</Text>
      </div>
      <div className="trade-metrics">
        <DecisionMetric label="当前价" value={formatPrice(item.current_price)} />
        <DecisionMetric label="低吸区" value={priceRange(item.trigger_price_low, item.trigger_price_high)} />
        <DecisionMetric label="低吸分" value={lowBuyScoreText(item.low_buy_score)} />
        <DecisionMetric label="风险分" value={formatScore(item.risk_score)} />
        <DecisionMetric label="目标仓位" value={formatPercentNumber(item.target_weight_pct)} />
        <DecisionMetric label="止盈/防守" value={`${formatPrice(item.take_profit_price)} / ${formatPrice(item.stop_price)}`} />
      </div>
      <ExecutionGateStrip conditions={item.conditions} inZone={inZone} />
      <p className={blocked ? 'trade-reason risk-text' : 'trade-reason'}>{item.decision_reason || executionShortText(item)}</p>
    </article>
  );
}

function QuantCommandBar({ health, framework, quantValidation, quantMaturity, errorMessage, refreshing, onRefresh }: { health?: HealthResponse; framework?: QuantFrameworkResponse; quantValidation?: QuantValidationReport; quantMaturity?: QuantMaturityReport; errorMessage: string | null; refreshing: boolean; onRefresh: () => void }) {
  return (
    <section className="quant-command">
      <CommandCell label="系统等级" value={quantMaturity ? `${quantMaturity.score.toFixed(0)}/100` : '-'} meta={maturityGradeLabel(quantMaturity?.grade)} tone={quantMaturity && quantMaturity.score >= 70 ? 'good' : 'warn'} />
      <CommandCell label="市场状态" value={marketStatusLabel(framework?.market_status)} meta={formatDateTime(framework?.generated_at)} />
      <CommandCell label="证据强度" value={evidenceLabel(framework?.validation.evidence_strength)} meta={framework?.validation.live_trading_ready ? 'live ready' : 'research'} tone={framework?.validation.live_trading_ready ? 'good' : 'warn'} />
      <CommandCell label="验证样本" value={quantValidation ? quantValidation.actionable_records.toFixed(0) : '-'} meta={quantValidation ? `${quantValidation.total_records.toFixed(0)} records` : '-'} />
      <CommandCell label="服务" value={health?.ok ? 'online' : 'check'} meta={health?.last_error || errorMessage || 'normal'} tone={health?.ok && !errorMessage ? 'good' : 'bad'} />
      <Button icon={<ReloadOutlined />} loading={refreshing} onClick={onRefresh}>刷新</Button>
    </section>
  );
}

function CommandCell({ label, value, meta, tone = 'neutral' }: { label: string; value: ReactNode; meta?: ReactNode; tone?: 'good' | 'warn' | 'bad' | 'neutral' }) {
  return (
    <div className={`command-cell tone-${tone}`}>
      <Text className="metric-label">{label}</Text>
      <strong>{value}</strong>
      {meta && <Text className="muted">{meta}</Text>}
    </div>
  );
}

function MaturityPanel({ report }: { report?: QuantMaturityReport }) {
  const modules = report?.modules ?? [];
  return (
    <Panel title="模型成熟度" icon={<SafetyCertificateOutlined />} meta={maturityGradeLabel(report?.grade)}>
      <div className="maturity-head">
        <strong>{report ? report.score.toFixed(0) : '-'}</strong>
        <Text>{report?.verdict ?? '等待成熟度报告'}</Text>
      </div>
      <div className="maturity-modules">
        {modules.map((item) => (
          <div className={`maturity-module status-${maturityStatusClass(item.status)}`} key={item.key}>
            <Text className="metric-label">{item.label}</Text>
            <strong>{item.score.toFixed(0)}</strong>
            <Text className="muted">{maturityStatusLabel(item.status)}</Text>
          </div>
        ))}
        {!modules.length && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无成熟度模块" />}
      </div>
    </Panel>
  );
}

function ProductionReadinessPanel({ report }: { report?: QuantMaturityReport }) {
  const gates = report?.gates ?? [];
  const failed = gates.filter((item) => item.status !== 'pass');
  return (
    <Panel
      title="生产闸门"
      icon={<ThunderboltOutlined />}
      meta={report?.auto_trade_allowed ? '允许自动交易' : '自动交易关闭'}
    >
      <div className={`production-verdict ${report?.production_ready ? 'ready' : 'blocked'}`}>
        <strong>{report?.auto_trade_allowed ? 'AUTO ON' : 'AUTO OFF'}</strong>
        <Text>{report?.verdict ?? '等待生产闸门报告'}</Text>
      </div>
      <div className="gate-list">
        {gates.map((gate) => <ProductionGateRow key={gate.key} gate={gate} />)}
        {!gates.length && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无生产闸门" />}
      </div>
      {!!failed.length && (
        <div className="next-upgrades">
          <Text className="metric-label">优先补齐</Text>
          <TagList items={(report?.next_upgrades ?? []).slice(0, 4)} color="orange" empty="暂无" />
        </div>
      )}
    </Panel>
  );
}

function ProductionGateRow({ gate }: { gate: QuantProductionGate }) {
  return (
    <div className={`gate-row status-${conditionStatusClass(gate.status)}`}>
      <div>
        <Text strong>{gate.label}</Text>
        <Text className="muted">{gate.blockers[0] ?? gate.evidence[0] ?? '通过'}</Text>
      </div>
      <div className="gate-score">
        <span>{conditionStatusLabel(gate.status)}</span>
        <strong>{gate.score.toFixed(0)}</strong>
      </div>
    </div>
  );
}

function SelfAuditPanel({ report }: { report?: QuantSelfAuditReport }) {
  const failed = report?.findings.filter((item) => !item.passed) ?? [];
  const visible = (failed.length ? failed : report?.findings ?? []).slice(0, 4);
  return (
    <Panel title="反方审计" icon={<SafetyCertificateOutlined />} meta={report?.verdict.maturity_label ?? '等待报告'}>
      <div className={`self-audit-verdict ${report?.verdict.mature ? 'ready' : 'blocked'}`}>
        <strong>{report?.verdict.mature ? 'MATURE' : 'NOT MATURE'}</strong>
        <Text>{report?.verdict.summary ?? '等待资金级自我审计'}</Text>
      </div>
      <div className="self-audit-action">
        <Text className="metric-label">最大允许动作</Text>
        <Text strong>{report?.verdict.max_allowed_action ?? '-'}</Text>
      </div>
      <div className="self-audit-stack">
        {visible.map((item) => <SelfAuditRow key={item.key} item={item} />)}
        {!visible.length && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无反方审计" />}
      </div>
    </Panel>
  );
}

function SelfAuditRow({ item }: { item: QuantAuditFinding }) {
  const blocker = item.blockers[0] ?? item.counterargument;
  return (
    <div className={`self-audit-row status-${item.passed ? 'pass' : 'fail'} severity-${item.severity}`}>
      <div>
        <Space size={4} wrap>
          <Text strong>{item.label}</Text>
          <Tag color={auditSeverityColor(item.severity)}>{auditSeverityLabel(item.severity)}</Tag>
          <Tag color={item.passed ? 'green' : 'red'}>{item.passed ? '通过' : '未过'}</Tag>
        </Space>
        <Text className="muted">{blocker}</Text>
        <Text className="audit-counter">反证：{item.counterargument}</Text>
      </div>
      <div className="self-audit-score">
        <span>分数</span>
        <strong>{item.score.toFixed(0)}</strong>
      </div>
    </div>
  );
}

function auditSeverityLabel(severity: string) {
  const labels: Record<string, string> = { critical: '硬阻断', high: '高风险', medium: '中风险' };
  return labels[severity] ?? severity;
}

function auditSeverityColor(severity: string) {
  const colors: Record<string, string> = { critical: 'red', high: 'orange', medium: 'gold' };
  return colors[severity] ?? 'default';
}

function PythonQuantStackPanel({ report }: { report?: PythonQuantStackReport }) {
  const weak = report?.capabilities.filter((item) => item.score < 65).slice(0, 4) ?? [];
  const visible = weak.length ? weak : report?.capabilities.slice(0, 4) ?? [];
  return (
    <Panel title="Python量化体系" icon={<ApiOutlined />} meta={report?.current_level ?? '等待报告'}>
      <div className="python-quant-head">
        <strong>{report ? report.readiness_score.toFixed(0) : '-'}</strong>
        <Text>{report?.verdict ?? '等待Python量化体系对照'}</Text>
      </div>
      <div className="python-quant-stack">
        {visible.map((item) => <PythonQuantCapabilityRow key={item.key} item={item} />)}
        {!visible.length && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无体系对照" />}
      </div>
      <div className="next-upgrades">
        <Text className="metric-label">改造顺序</Text>
        <TagList items={(report?.adoption_sequence ?? []).slice(0, 3)} color="blue" empty="暂无" />
      </div>
    </Panel>
  );
}

function PythonQuantCapabilityRow({ item }: { item: PythonQuantCapability }) {
  return (
    <div className={`python-quant-row state-${item.adoption_state}`}>
      <div>
        <Space size={4} wrap>
          <Text strong>{item.label}</Text>
          <Tag color={pythonQuantStateColor(item.adoption_state)}>{pythonQuantStateLabel(item.adoption_state)}</Tag>
        </Space>
        <Text className="muted">{item.reference_stack.join(' / ')}</Text>
        <Text className="python-quant-note">短板：{item.blockers[0] ?? item.current_state}</Text>
      </div>
      <div className="python-quant-score">
        <span>成熟度</span>
        <strong>{item.score.toFixed(0)}</strong>
      </div>
    </div>
  );
}

function pythonQuantStateLabel(state: string) {
  const labels: Record<string, string> = {
    research_only: '研究级',
    missing_core: '缺核心',
    prototype: '原型',
    partial: '部分',
    guarded_partial: '受限',
    required_before_capital: '资金前必补',
    blocked: '阻断'
  };
  return labels[state] ?? state;
}

function pythonQuantStateColor(state: string) {
  const colors: Record<string, string> = {
    research_only: 'orange',
    missing_core: 'red',
    prototype: 'orange',
    partial: 'blue',
    guarded_partial: 'gold',
    required_before_capital: 'red',
    blocked: 'red'
  };
  return colors[state] ?? 'default';
}

function AlgorithmResearchPanel({ report }: { report?: QuantAlgorithmReport }) {
  const candidates = report?.candidates.slice(0, 4) ?? [];
  return (
    <Panel title="算法研究栈" icon={<BulbOutlined />} meta={report ? formatDateTime(report.generated_at) : '等待报告'}>
      <div className="algo-recommendations">
        <Text className="metric-label">落地顺序</Text>
        <TagList items={(report?.recommended_next ?? []).slice(0, 3)} color="blue" empty="暂无算法建议" />
      </div>
      <div className="algorithm-stack">
        {candidates.map((item) => <AlgorithmCandidateRow key={item.key} item={item} />)}
        {!candidates.length && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无算法研究报告" />}
      </div>
    </Panel>
  );
}

function AlgorithmCandidateRow({ item }: { item: QuantAlgorithmCandidate }) {
  return (
    <div className={`algorithm-row status-${item.status}`}>
      <div>
        <Space size={4} wrap>
          <Text strong>{item.label}</Text>
          <Tag color={algorithmStatusColor(item.status)}>{algorithmStatusLabel(item.status)}</Tag>
        </Space>
        <Text className="muted">{item.family} · {item.implementation_state}</Text>
        <Text className="algo-note">下一步：{item.next_actions[0] ?? item.gaps[0] ?? '等待验证'}</Text>
      </div>
      <div className="algo-score">
        <span>适配</span>
        <strong>{item.fit_score.toFixed(0)}</strong>
      </div>
    </div>
  );
}

function algorithmStatusLabel(status: string) {
  const labels: Record<string, string> = {
    recommended: '优先',
    required_validation: '必补',
    later: '以后',
    not_now: '暂不',
    blocked: '阻断'
  };
  return labels[status] ?? status;
}

function algorithmStatusColor(status: string) {
  const colors: Record<string, string> = {
    recommended: 'green',
    required_validation: 'orange',
    later: 'blue',
    not_now: 'default',
    blocked: 'red'
  };
  return colors[status] ?? 'default';
}

function ModelPipelinePanel({ framework, report }: { framework?: QuantFrameworkResponse; report?: QuantMaturityReport }) {
  const moduleScore = (key: string) => report?.modules.find((item) => item.key === key)?.score ?? null;
  const steps = [
    { key: 'universe', label: 'Universe', name: '资产池筛选', metric: `${framework?.universe.length ?? 0} assets`, score: moduleScore('data') },
    { key: 'alpha', label: 'Alpha', name: '方向与强度信号', metric: `${framework?.insights.length ?? 0} insights`, score: moduleScore('research') },
    { key: 'portfolio', label: 'Portfolio', name: '仓位目标', metric: `${framework?.portfolio_targets.length ?? 0} targets`, score: moduleScore('portfolio_risk') },
    { key: 'risk', label: 'Risk', name: '风控覆盖', metric: `${framework?.risk_adjustments.length ?? 0} checks`, score: moduleScore('portfolio_risk') },
    { key: 'execution', label: 'Execution', name: '低吸高抛契约', metric: `${framework?.execution_plan.length ?? 0} orders`, score: moduleScore('execution') },
    { key: 'validation', label: 'Validation', name: '回测/前向验证', metric: framework?.validation.research_grade ? 'research grade' : 'pending', score: moduleScore('backtest') }
  ];
  return (
    <Panel title="量化流水线" icon={<LineChartOutlined />} meta="Universe → Alpha → Portfolio → Risk → Execution">
      <div className="pipeline-rail">
        {steps.map((step) => (
          <div className="pipeline-node" key={step.key}>
            <div>
              <Text className="metric-label">{step.label}</Text>
              <Text strong>{step.name}</Text>
              <Text className="muted">{step.metric}</Text>
            </div>
            <ScoreText value={step.score} />
          </div>
        ))}
      </div>
    </Panel>
  );
}

function ExecutionGateStrip({ conditions, inZone }: { conditions: QuantExecutionCondition[]; inZone: boolean }) {
  const visible = conditions.length ? conditions : [{ key: 'price', label: '价格区间', status: inZone ? 'pass' : 'wait', value: null, threshold: null, reason: inZone ? '价格已进入低吸区' : '等待价格进入低吸区' }];
  return (
    <div className="condition-strip">
      {visible.map((item) => (
        <Tooltip key={item.key} title={`${item.reason}${item.value ? ` · 当前 ${item.value}` : ''}${item.threshold ? ` · 阈值 ${item.threshold}` : ''}`}>
          <span className={`condition-pill status-${conditionStatusClass(item.status)}`}>{conditionStatusLabel(item.status)} {item.label}</span>
        </Tooltip>
      ))}
    </div>
  );
}

function DecisionMetric({ label, value }: { label: string; value: ReactNode }) {
  return <div className="decision-metric"><Text>{label}</Text><strong>{value}</strong></div>;
}

function SignalValidationStrip({ report }: { report?: QuantValidationReport }) {
  const t3 = report?.horizon_metrics.find((item) => item.horizon_days === 3);
  return (
    <div className="validation-strip">
      <DecisionMetric label="账本记录" value={report ? report.total_records.toFixed(0) : '-'} />
      <DecisionMetric label="验证假设" value={report ? report.actionable_records.toFixed(0) : '-'} />
      <DecisionMetric label="T+3已验证" value={t3 ? `${t3.resolved_count}/${t3.sample_count}` : '-'} />
      <DecisionMetric label="T+3胜率" value={formatPercentNumber(t3?.win_rate_pct)} />
      <DecisionMetric label="T+3均值" value={formatSignedPercent(t3?.avg_forward_return_pct)} />
      <DecisionMetric label="样本等级" value={report ? evidenceLabel(report.evidence_strength) : '-'} />
    </div>
  );
}

function ValidationPanel({ framework, onRefresh, loading }: { framework?: QuantFrameworkResponse; onRefresh: () => void; loading: boolean }) {
  const counts = framework ? [
    ['Universe', framework.universe.length],
    ['Features', framework.features.length],
    ['Alpha', framework.insights.length],
    ['Targets', framework.portfolio_targets.length],
    ['Risk', framework.risk_adjustments.length],
    ['Exec', framework.execution_plan.length]
  ] : [];
  return (
    <Panel title="框架状态" icon={<CheckCircleOutlined />} meta={framework?.validation.research_grade ? '研究级' : '-'} extra={<Button size="small" icon={<ReloadOutlined />} loading={loading} onClick={onRefresh}>刷新链路</Button>}>
      <div className="score-grid framework-counts">
        {counts.map(([label, value]) => <ScoreBox key={String(label)} label={String(label)} value={Number(value)} />)}
      </div>
    </Panel>
  );
}

function PortfolioRiskPanel({ targets, risks }: { targets: QuantPortfolioTarget[]; risks: QuantRiskAdjustment[] }) {
  const riskByCode = new Map(risks.map((item) => [item.code, item]));
  return (
    <Panel title="组合与风控" icon={<SafetyCertificateOutlined />} meta="Portfolio + Risk">
      <div className="mini-list">
        {targets.map((target) => <PortfolioRiskRow key={target.code} target={target} risk={riskByCode.get(target.code)} />)}
        {!targets.length && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无组合目标" />}
      </div>
    </Panel>
  );
}

function PortfolioRiskRow({ target, risk }: { target: QuantPortfolioTarget; risk?: QuantRiskAdjustment }) {
  return (
    <div className="row-card quant-row">
      <div>
        <Text strong>{target.name}</Text>
        <Text className="muted">{target.code} · {rebalanceLabel(target.rebalance_action)}</Text>
      </div>
      <Space size={4} wrap className="row-actions">
        <Tag color={riskColor(risk?.risk_level)}>{risk?.blocked ? '阻断' : riskLabel(risk?.risk_level)}</Tag>
        <Tag>{formatPercentNumber(risk?.adjusted_target_weight_pct ?? target.target_weight_pct)}</Tag>
        {risk?.position_delta_pct != null && <Tag color={risk.position_delta_pct < 0 ? 'red' : 'green'}>{formatDelta(risk.position_delta_pct)}</Tag>}
      </Space>
    </div>
  );
}

function UniversePanel({ items, allItems }: { items: QuantUniverseAsset[]; allItems: QuantUniverseAsset[] }) {
  const visible = items.length ? items : allItems.slice(0, 6);
  return (
    <Panel title="资产池" icon={<LineChartOutlined />} meta={`${visible.length}/${allItems.length}`}>
      <div className="mini-list">
        {visible.slice(0, 8).map((item, index) => <UniverseRow key={`${item.asset_type}-${item.code ?? item.name}-${index}`} item={item} />)}
        {!visible.length && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无资产池" />}
      </div>
    </Panel>
  );
}

function UniverseRow({ item }: { item: QuantUniverseAsset }) {
  return (
    <div className="row-card quant-row">
      <div>
        <Text strong>{item.name}</Text>
        <Text className="muted">{item.code ?? item.direction_key ?? '-'} · {assetTypeLabel(item.asset_type)} · {roleLabel(item.role)}</Text>
      </div>
      <Space size={4} wrap>
        {item.rank != null && <Tag>#{item.rank}</Tag>}
        <Tag color={item.selected ? 'green' : 'default'}>{item.selected ? '入池' : '观察'}</Tag>
      </Space>
    </div>
  );
}

function EvidencePanel({ features, insights }: { features: QuantFeatureRow[]; insights: QuantInsight[] }) {
  const topFeatures = [...features].sort((a, b) => b.score - a.score).slice(0, 5);
  const topInsights = [...insights].sort((a, b) => b.confidence_score - a.confidence_score).slice(0, 5);
  return (
    <Panel title="证据链" icon={<CheckCircleOutlined />} meta="Features + Alpha">
      <div className="evidence-columns">
        <div>
          <Text className="metric-label">Alpha</Text>
          <div className="mini-list">
            {topInsights.map((item, index) => <InsightRow key={`${item.code ?? item.name}-${index}`} item={item} />)}
          </div>
        </div>
        <div>
          <Text className="metric-label">特征</Text>
          <div className="mini-list">
            {topFeatures.map((item, index) => <FeatureRow key={`${item.code ?? item.name}-${index}`} item={item} />)}
          </div>
        </div>
      </div>
    </Panel>
  );
}

function InsightRow({ item }: { item: QuantInsight }) {
  return (
    <div className="row-card compact-row">
      <div>
        <Text strong>{item.name}</Text>
        <Text className="muted">{insightTypeLabel(item.insight_type)} · {item.horizon}</Text>
      </div>
      <Space size={4} wrap>
        <Tag color={directionColor(item.direction)}>{item.direction}</Tag>
        <ScoreText value={item.confidence_score} />
      </Space>
    </div>
  );
}

function FeatureRow({ item }: { item: QuantFeatureRow }) {
  return (
    <div className="row-card compact-row">
      <div>
        <Text strong>{item.name}</Text>
        <Text className="muted">{item.feature_set}</Text>
      </div>
      <ScoreText value={item.score} />
    </div>
  );
}

function PositionPanel({ positions, actions, draft, setDraft, onSave, saving, onDelete, deleting, deletingCode }: { positions: Position[]; actions: ActionDecisionItem[]; draft: PositionDraft; setDraft: (draft: PositionDraft) => void; onSave: () => void; saving: boolean; onDelete: (code: string) => void; deleting: boolean; deletingCode: string | null }) {
  return (
    <Panel title="持仓" icon={<SafetyCertificateOutlined />} meta={positions.length ? `${positions.length} 个` : '空仓'}>
      <div className="position-form">
        <Input value={draft.code} onChange={(event) => setDraft({ ...draft, code: event.target.value })} placeholder="代码" maxLength={6} />
        <Input value={draft.entry} onChange={(event) => setDraft({ ...draft, entry: event.target.value })} placeholder="成本价" type="number" inputMode="decimal" />
        <Input value={draft.shares} onChange={(event) => setDraft({ ...draft, shares: event.target.value })} placeholder="份额" type="number" inputMode="decimal" />
        <Button type="primary" loading={saving} onClick={onSave}>保存</Button>
      </div>
      <Input className="position-note" value={draft.note} onChange={(event) => setDraft({ ...draft, note: event.target.value })} placeholder="备注，可不填" />
      <div className="mini-list position-list">
        {positions.map((position) => <PositionRow key={position.code} position={position} action={actions.find((item) => item.code === position.code)} onDelete={onDelete} deleting={deleting && deletingCode === position.code} />)}
        {!positions.length && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="空仓" />}
      </div>
    </Panel>
  );
}

function PositionRow({ position, action, onDelete, deleting }: { position: Position; action?: ActionDecisionItem; onDelete: (code: string) => void; deleting: boolean }) {
  return (
    <div className="row-card position-row">
      <div>
        <Text strong>{action?.name ?? position.code}</Text>
        <Text className="muted">成本 {formatPrice(position.entry_price)} · 浮盈 <PercentText value={action?.floating_profit_pct ?? null} /> · 防守 {formatPrice(action?.effective_exit_price)}</Text>
        {action?.execution_note && <Text className="muted">{action.execution_note}</Text>}
      </div>
      <Space size={4} wrap>
        {action && <ActionTag action={action.action} side={action.side} />}
        <Button danger size="small" loading={deleting} onClick={() => onDelete(position.code)}>删</Button>
      </Space>
    </div>
  );
}

function AiPanel({ status, report, onToggle, toggling, onGenerate, generating, generatingKind }: { status?: AiStatus; report?: AiSummaryReport; onToggle: (enabled: boolean) => void; toggling: boolean; onGenerate: (kind: AiSummaryKind | string) => void; generating: boolean; generatingKind: AiSummaryKind | string | null }) {
  const latest = report?.summaries?.[0];
  return (
    <Panel title="AI 总结" icon={<BulbOutlined />} meta={status ? `${status.calls_used_today}/${status.daily_call_limit}` : '-'} extra={<Switch checked={Boolean(status?.enabled)} loading={toggling} onChange={onToggle} disabled={!status?.configured} checkedChildren="开" unCheckedChildren="关" />}>
      {latest ? (
        <div className="ai-card">
          <Text strong>{latest.title}</Text>
          <Text className="muted">{latest.trading_date} · {formatDateTime(latest.generated_at)}</Text>
          <p>{latest.summary}</p>
        </div>
      ) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无AI总结" />}
      <Space size={[6, 6]} wrap>
        {(status?.windows ?? []).map((item) => <Button key={item.kind} size="small" onClick={() => onGenerate(item.kind)} loading={generating && generatingKind === item.kind} disabled={!status?.enabled || !status.configured}>{item.title}</Button>)}
      </Space>
    </Panel>
  );
}

function SystemPanel({ health, session, framework, integrations }: { health?: HealthResponse; session?: WebSessionInfo; framework?: QuantFrameworkResponse; integrations: IntegrationStatus[] }) {
  const okIntegrations = integrations.filter((item) => item.ok).length;
  return (
    <Panel title="系统" icon={<ApiOutlined />} meta="运行状态">
      <div className="system-strip embedded">
        <StatusMetric icon={<ApiOutlined />} label="服务" value={health?.ok ? '在线' : '异常'} color={health?.ok ? 'green' : 'red'} />
        <StatusMetric icon={<SafetyCertificateOutlined />} label="等级" value={framework?.validation.research_grade ? '研究级' : '-'} color="orange" />
        <StatusMetric icon={<ThunderboltOutlined />} label="实盘" value={framework?.validation.live_trading_ready ? '可用' : '未就绪'} color={framework?.validation.live_trading_ready ? 'green' : 'red'} />
        <StatusMetric icon={<CheckCircleOutlined />} label="基础设施" value={`${okIntegrations}/${integrations.length || 0}`} />
        <StatusMetric icon={<UserOutlined />} label="会话" value={session?.username ?? '-'} />
      </div>
    </Panel>
  );
}

function Panel({ title, icon, meta, extra, children }: { title: string; icon: ReactNode; meta?: string; extra?: ReactNode; children: ReactNode }) {
  return (
    <section className="panel">
      <div className="panel-head">
        <Space size={8} wrap>
          <span className="panel-icon">{icon}</span>
          <Text strong>{title}</Text>
          {meta && <Text className="muted">{meta}</Text>}
        </Space>
        {extra}
      </div>
      {children}
    </section>
  );
}

function ScoreBox({ label, value }: { label: string; value: number | null }) {
  return <div className="score-box"><Text className="metric-label">{label}</Text><strong style={{ color: value == null ? '#667085' : scoreColor(value) }}>{value == null ? '-' : value.toFixed(0)}</strong></div>;
}

function StatusMetric({ icon, label, value, color = 'default' }: { icon: ReactNode; label: string; value: string; color?: string }) {
  return <div className="status-metric"><span>{icon}</span><Text className="metric-label">{label}</Text><Tag color={color}>{value}</Tag></div>;
}

function TagList({ items, color = 'blue', empty = '暂无' }: { items: string[]; color?: string; empty?: string }) {
  if (!items.length) return <Text className="muted">{empty}</Text>;
  return <Space size={[4, 4]} wrap>{items.map((item) => <Tag color={color} key={item}>{item}</Tag>)}</Space>;
}

function ActionTag({ action, side }: { action: string; side: string }) {
  return <Tag color={actionColor(side)}>{actionLabel(action)}</Tag>;
}

function ScoreText({ value }: { value: number | null | undefined }) {
  if (value == null) return <Text className="muted">-</Text>;
  return <Text strong style={{ color: scoreColor(value) }}>{value.toFixed(0)}</Text>;
}

function PercentText({ value, neutral = false }: { value: number | null | undefined; neutral?: boolean }) {
  if (value == null) return <Text className="muted">-</Text>;
  return <Text className={neutral ? undefined : value >= 0 ? 'num-up' : 'num-down'}>{value.toFixed(2)}%</Text>;
}

