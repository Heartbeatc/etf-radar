import { useEffect, useMemo, useState, type ReactNode } from 'react';
import {
  App as AntdApp,
  Badge,
  Button,
  Empty,
  Input,
  Layout,
  Modal,
  Space,
  Spin,
  Switch,
  Tag,
  Tooltip,
  Typography
} from 'antd';
import {
  ApiOutlined,
  BulbOutlined,
  CheckCircleOutlined,
  LineChartOutlined,
  LockOutlined,
  LogoutOutlined,
  ReloadOutlined,
  SafetyCertificateOutlined,
  ThunderboltOutlined,
  UserOutlined
} from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query';
import { ApiError, SESSION_STORAGE_KEY, api } from './api';
import type {
  ActionDecisionItem,
  AiStatus,
  AiSummaryKind,
  AiSummaryReport,
  HealthResponse,
  IntegrationStatus,
  Position,
  PositionInput,
  QuantExecutionAdvice,
  QuantFeatureRow,
  QuantFrameworkResponse,
  QuantInsight,
  QuantValidationReport,
  QuantPortfolioTarget,
  QuantRiskAdjustment,
  QuantUniverseAsset,
  WebSessionInfo
} from './types';

const { Header, Content } = Layout;
const { Text, Title } = Typography;

function invalidateTradingQueries(queryClient: QueryClient, token: string) {
  queryClient.invalidateQueries({ queryKey: ['quant-framework', token] });
  queryClient.invalidateQueries({ queryKey: ['positions', token] });
  queryClient.invalidateQueries({ queryKey: ['health'] });
}

function App() {
  const queryClient = useQueryClient();
  const { message } = AntdApp.useApp();
  const [sessionToken, setSessionToken] = useState(() => window.localStorage.getItem(SESSION_STORAGE_KEY) ?? '');
  const [loginOpen, setLoginOpen] = useState(!sessionToken);
  const [loginUsername, setLoginUsername] = useState('admin');
  const [loginPassword, setLoginPassword] = useState('');
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [positionDraft, setPositionDraft] = useState<PositionDraft>({ code: '', entry: '', shares: '', note: '' });

  const healthQuery = useQuery({
    queryKey: ['health'],
    queryFn: ({ signal }) => api.getHealth(signal),
    refetchInterval: autoRefresh ? 30_000 : false
  });
  const sessionQuery = useProtectedQuery(['auth-session', sessionToken], sessionToken, ({ signal }) => api.getSession(sessionToken, signal), autoRefresh ? 60_000 : false);
  const frameworkQuery = useProtectedQuery(['quant-framework', sessionToken], sessionToken, ({ signal }) => api.getQuantFramework(sessionToken, signal), autoRefresh ? 30_000 : false);
  const quantValidationQuery = useProtectedQuery(['quant-validation', sessionToken], sessionToken, ({ signal }) => api.getQuantValidation(sessionToken, signal), autoRefresh ? 60_000 : false);
  const positionsQuery = useProtectedQuery(['positions', sessionToken], sessionToken, ({ signal }) => api.getPositions(sessionToken, signal), autoRefresh ? 30_000 : false);
  const integrationsQuery = useProtectedQuery(['integrations', sessionToken], sessionToken, ({ signal }) => api.getIntegrations(sessionToken, signal), autoRefresh ? 60_000 : false);
  const aiStatusQuery = useProtectedQuery(['ai-status', sessionToken], sessionToken, ({ signal }) => api.getAiStatus(sessionToken, signal), autoRefresh ? 60_000 : false);
  const aiSummariesQuery = useProtectedQuery(['ai-summaries', sessionToken], sessionToken, ({ signal }) => api.getAiSummaries(sessionToken, signal), autoRefresh ? 60_000 : false);

  const protectedErrors = [sessionQuery.error, frameworkQuery.error, quantValidationQuery.error, positionsQuery.error, integrationsQuery.error, aiStatusQuery.error, aiSummariesQuery.error].filter(Boolean);
  const unauthorized = protectedErrors.some((error) => error instanceof ApiError && error.status === 401);
  const refreshing = [healthQuery, sessionQuery, frameworkQuery, quantValidationQuery, positionsQuery, integrationsQuery, aiStatusQuery, aiSummariesQuery].some((query) => query.isFetching);
  const firstLoad = Boolean(sessionToken) && [frameworkQuery, positionsQuery].some((query) => query.isLoading);

  const clearSession = (openLogin = true) => {
    window.localStorage.removeItem(SESSION_STORAGE_KEY);
    setSessionToken('');
    setLoginPassword('');
    queryClient.clear();
    if (openLogin) setLoginOpen(true);
  };

  useEffect(() => {
    if (unauthorized && sessionToken) {
      clearSession(true);
      message.warning('登录已过期，请重新登录');
    }
  }, [unauthorized, sessionToken]);

  const loginMutation = useMutation({
    mutationFn: () => api.login(loginUsername.trim(), loginPassword),
    onSuccess: (data) => {
      window.localStorage.setItem(SESSION_STORAGE_KEY, data.access_token);
      setSessionToken(data.access_token);
      setLoginPassword('');
      setLoginOpen(false);
      queryClient.invalidateQueries();
      message.success('登录成功');
    },
    onError: (error) => message.error(getErrorMessage(error))
  });

  const forceRefreshMutation = useMutation({
    mutationFn: () => api.getMarketFlow(sessionToken, true),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['quant-framework', sessionToken] });
      message.success('量化链路已刷新');
    },
    onError: (error) => message.error(getErrorMessage(error))
  });

  const savePositionMutation = useMutation({
    mutationFn: ({ code, input }: { code: string; input: PositionInput }) => api.upsertPosition(sessionToken, code, input),
    onSuccess: () => {
      setPositionDraft({ code: '', entry: '', shares: '', note: '' });
      invalidateTradingQueries(queryClient, sessionToken);
      message.success('持仓已保存');
    },
    onError: (error) => message.error(getErrorMessage(error))
  });

  const deletePositionMutation = useMutation({
    mutationFn: (code: string) => api.deletePosition(sessionToken, code),
    onSuccess: () => {
      invalidateTradingQueries(queryClient, sessionToken);
      message.success('持仓已删除');
    },
    onError: (error) => message.error(getErrorMessage(error))
  });

  const aiToggleMutation = useMutation({
    mutationFn: (enabled: boolean) => api.setAiEnabled(sessionToken, enabled),
    onSuccess: (data) => {
      queryClient.setQueryData(['ai-status', sessionToken], data);
      queryClient.invalidateQueries({ queryKey: ['ai-summaries', sessionToken] });
      message.success(data.enabled ? 'AI已开启' : 'AI已关闭');
    },
    onError: (error) => message.error(getErrorMessage(error))
  });

  const aiGenerateMutation = useMutation({
    mutationFn: (kind: AiSummaryKind | string) => api.generateAiSummary(sessionToken, kind, true),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['ai-status', sessionToken] });
      queryClient.invalidateQueries({ queryKey: ['ai-summaries', sessionToken] });
      message.success('AI总结已更新');
    },
    onError: (error) => message.error(getErrorMessage(error))
  });

  const submitLogin = () => {
    if (!loginUsername.trim() || !loginPassword) {
      message.warning('用户名和密码不能为空');
      return;
    }
    loginMutation.mutate();
  };

  const logout = () => {
    const token = sessionToken;
    clearSession(true);
    if (token) api.logout(token).catch(() => undefined);
    message.success('已退出');
  };

  const refreshAll = () => queryClient.invalidateQueries();

  const savePosition = () => {
    const code = positionDraft.code.trim();
    const entry = Number(positionDraft.entry);
    const shares = positionDraft.shares.trim() ? Number(positionDraft.shares) : null;
    if (!/^\d{6}$/.test(code)) {
      message.warning('请输入6位场内代码');
      return;
    }
    if (!Number.isFinite(entry) || entry <= 0) {
      message.warning('请输入有效成本价');
      return;
    }
    if (shares != null && (!Number.isFinite(shares) || shares <= 0)) {
      message.warning('份额必须大于0');
      return;
    }
    savePositionMutation.mutate({ code, input: { entry_price: entry, shares, note: positionDraft.note.trim() } });
  };

  return (
    <Layout className="app-shell">
      <Header className="topbar">
        <div className="brand">
          <span className="brand-mark"><LineChartOutlined /></span>
          <div>
            <Title level={4} className="brand-title">ETF Radar</Title>
            <Text className="brand-subtitle">交易决策台</Text>
          </div>
        </div>
        <Space size="small" wrap className="top-actions">
          <StatusBadge health={healthQuery.data} loading={healthQuery.isFetching} />
          <SessionBadge session={sessionQuery.data} loading={sessionQuery.isFetching} hasToken={Boolean(sessionToken)} />
          <Switch checked={autoRefresh} onChange={setAutoRefresh} checkedChildren="自动" unCheckedChildren="手动" />
          <Tooltip title="刷新">
            <Button icon={<ReloadOutlined />} loading={refreshing} onClick={refreshAll} />
          </Tooltip>
          <Tooltip title={sessionToken ? '退出' : '登录'}>
            <Button icon={sessionToken ? <LogoutOutlined /> : <UserOutlined />} onClick={sessionToken ? logout : () => setLoginOpen(true)} />
          </Tooltip>
        </Space>
      </Header>

      <Content className="content quant-content">
        {!sessionToken ? (
          <section className="panel center-panel"><Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="请先登录" /></section>
        ) : firstLoad ? (
          <section className="panel center-panel"><Spin tip="加载量化链路" /></section>
        ) : (
          <QuantConsole
            health={healthQuery.data}
            session={sessionQuery.data}
            framework={frameworkQuery.data}
            quantValidation={quantValidationQuery.data}
            positions={positionsQuery.data ?? []}
            integrations={integrationsQuery.data ?? []}
            aiStatus={aiStatusQuery.data}
            aiSummaries={aiSummariesQuery.data}
            draft={positionDraft}
            setDraft={setPositionDraft}
            onSavePosition={savePosition}
            savingPosition={savePositionMutation.isPending}
            onDeletePosition={(code) => deletePositionMutation.mutate(code)}
            deletingPosition={deletePositionMutation.isPending}
            deletingCode={typeof deletePositionMutation.variables === 'string' ? deletePositionMutation.variables : null}
            onRefreshFramework={() => forceRefreshMutation.mutate()}
            refreshingFramework={forceRefreshMutation.isPending || frameworkQuery.isFetching}
            onToggleAi={(enabled) => aiToggleMutation.mutate(enabled)}
            togglingAi={aiToggleMutation.isPending}
            onGenerateAi={(kind) => aiGenerateMutation.mutate(kind)}
            generatingAi={aiGenerateMutation.isPending}
            generatingKind={typeof aiGenerateMutation.variables === 'string' ? aiGenerateMutation.variables : null}
            errorMessage={protectedErrors.length ? getErrorMessage(protectedErrors[0]) : null}
          />
        )}
      </Content>

      <Modal
        title="网页登录"
        open={loginOpen}
        width={420}
        onOk={submitLogin}
        onCancel={() => sessionToken && setLoginOpen(false)}
        okText="登录"
        cancelText="关闭"
        closable={Boolean(sessionToken)}
        maskClosable={Boolean(sessionToken)}
        okButtonProps={{ loading: loginMutation.isPending }}
        cancelButtonProps={!sessionToken ? { style: { display: 'none' } } : undefined}
      >
        <Space direction="vertical" size="middle" className="modal-body">
          <Input prefix={<UserOutlined />} value={loginUsername} onChange={(event) => setLoginUsername(event.target.value)} onPressEnter={submitLogin} placeholder="用户名" autoFocus />
          <Input.Password prefix={<LockOutlined />} value={loginPassword} onChange={(event) => setLoginPassword(event.target.value)} onPressEnter={submitLogin} placeholder="密码" />
        </Space>
      </Modal>
    </Layout>
  );
}

function useProtectedQuery<T>(queryKey: readonly unknown[], token: string, queryFn: (context: { signal?: AbortSignal }) => Promise<T>, refetchInterval: number | false) {
  return useQuery({ queryKey, queryFn, enabled: Boolean(token), refetchInterval, retry: false });
}

interface PositionDraft {
  code: string;
  entry: string;
  shares: string;
  note: string;
}

interface QuantConsoleProps {
  health?: HealthResponse;
  session?: WebSessionInfo;
  framework?: QuantFrameworkResponse;
  quantValidation?: QuantValidationReport;
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

function QuantConsole(props: QuantConsoleProps) {
  const primary = useMemo(() => pickPrimaryExecution(props.framework, props.positions), [props.framework, props.positions]);
  const focusItems = useMemo(() => [...(props.framework?.execution_plan ?? [])].sort((a, b) => executionRank(a) - executionRank(b)).slice(0, 3), [props.framework]);
  const selectedUniverse = (props.framework?.universe ?? []).filter((item) => item.selected);
  const heldCodes = new Set(props.positions.map((item) => item.code));
  const positionActions = (props.framework?.final_actions ?? []).filter((item) => item.has_position || heldCodes.has(item.code));
  return (
    <main className="trading-console">
      <section className={`decision-hero side-${primary.side.toLowerCase()}`}>
        <div className="decision-copy">
          <Text className="eyebrow">当前动作</Text>
          <h1>{frameworkConclusion(props.framework, primary)}</h1>
          <div className="status-line">
            <ActionTag action={primary.action} side={primary.side} />
            <Tag color={evidenceColor(props.framework?.validation.evidence_strength)}>证据 {evidenceLabel(props.framework?.validation.evidence_strength)}</Tag>
            <Tag color={props.framework?.validation.live_trading_ready ? 'green' : 'orange'}>{props.framework?.validation.live_trading_ready ? '可实盘' : '研究级'}</Tag>
            <Text className="muted">{frameworkStageLabel(props.framework)} · {formatDateTime(props.framework?.generated_at)}</Text>
          </div>
        </div>
        <div className="decision-ticket">
          <Text className="ticket-label">核心标的</Text>
          <strong>{primary.code ?? '-'}</strong>
          <Text>{primary.note}</Text>
        </div>
      </section>

      <section className="focus-board">
        <div className="section-title-row">
          <div>
            <Text className="eyebrow">交易候选</Text>
            <h2>今天只看这 3 个</h2>
          </div>
          <Button size="small" icon={<ReloadOutlined />} loading={props.refreshingFramework} onClick={props.onRefreshFramework}>刷新</Button>
        </div>
        <div className="trade-grid">
          {focusItems.map((item, index) => <TradeFocusCard key={item.code} item={item} index={index} primary={item.code === primary.code} />)}
          {!focusItems.length && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无交易候选" />}
        </div>
        <SignalValidationStrip report={props.quantValidation} />
      </section>

      <section className="support-grid">
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
        <AiPanel status={props.aiStatus} report={props.aiSummaries} onToggle={props.onToggleAi} toggling={props.togglingAi} onGenerate={props.onGenerateAi} generating={props.generatingAi} generatingKind={props.generatingKind} />
      </section>

      <details className="detail-drawer">
        <summary>展开证据、资产池和系统状态</summary>
        <div className="detail-grid">
          <EvidencePanel features={props.framework?.features ?? []} insights={props.framework?.insights ?? []} />
          <PortfolioRiskPanel targets={props.framework?.portfolio_targets ?? []} risks={props.framework?.risk_adjustments ?? []} />
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
  return (
    <article className={`trade-card side-${item.side.toLowerCase()} ${primary ? 'primary' : ''}`}>
      <div className="trade-card-head">
        <Text className="ticket-label">{role}</Text>
        <ActionTag action={item.action} side={item.side} />
      </div>
      <div className="trade-identity">
        <strong>{item.name}</strong>
        <Text className="muted">{item.code} · {etfRegionLabel(item.name)}</Text>
      </div>
      <div className="trade-metrics">
        <DecisionMetric label="低吸区" value={priceRange(item.trigger_price_low, item.trigger_price_high)} />
        <DecisionMetric label="目标仓位" value={formatPercentNumber(item.target_weight_pct)} />
        <DecisionMetric label="止盈" value={formatPrice(item.take_profit_price)} />
        <DecisionMetric label="防守" value={formatPrice(item.stop_price)} />
      </div>
      <p className={blocked ? 'trade-reason risk-text' : 'trade-reason'}>{executionShortText(item)}</p>
    </article>
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

function executionShortText(item: QuantExecutionAdvice): string {
  if (item.blockers.length) return '风控阻断';
  if (item.side === 'BUY') return '低吸触发';
  if (item.side === 'SELL') return '卖出/减仓';
  if (item.side === 'HOLD') return '持有跟踪';
  if (item.action === 'AVOID') return '回避';
  if (item.action === 'WAIT_PULLBACK') return '等回落';
  if (item.action === 'WAIT_BUY_ZONE' || item.action === 'WATCH_LOW_BUY') return '等低吸区';
  return '等待';
}

function etfRegionLabel(name: string): string {
  return /港股|港股通|恒生|中概|H股|香港/.test(name) ? '港股载体' : 'A股载体';
}

function ScoreText({ value }: { value: number | null | undefined }) {
  if (value == null) return <Text className="muted">-</Text>;
  return <Text strong style={{ color: scoreColor(value) }}>{value.toFixed(0)}</Text>;
}

function PercentText({ value, neutral = false }: { value: number | null | undefined; neutral?: boolean }) {
  if (value == null) return <Text className="muted">-</Text>;
  return <Text className={neutral ? undefined : value >= 0 ? 'num-up' : 'num-down'}>{value.toFixed(2)}%</Text>;
}

function StatusBadge({ health, loading }: { health?: HealthResponse; loading: boolean }) {
  if (loading && !health) return <Badge status="processing" text="检查中" />;
  if (!health) return <Badge status="default" text="未连接" />;
  return <Badge status={health.ok ? 'success' : 'error'} text={health.ok ? '后端在线' : '后端异常'} />;
}

function SessionBadge({ session, loading, hasToken }: { session?: WebSessionInfo; loading: boolean; hasToken: boolean }) {
  if (!hasToken) return <Badge status="default" text="未登录" />;
  if (loading && !session) return <Badge status="processing" text="验证中" />;
  if (!session) return <Badge status="warning" text="待验证" />;
  return <Badge status="success" text={session.username} />;
}

function pickPrimaryExecution(framework?: QuantFrameworkResponse, positions: Position[] = []) {
  const items = framework?.execution_plan ?? [];
  const priority = items.find((item) => item.side === 'SELL') ?? items.find((item) => item.side === 'BUY') ?? items.find((item) => item.side === 'HOLD') ?? items[0];
  if (priority) {
    return {
      code: priority.code,
      action: priority.action,
      side: priority.side,
      note: priority.blockers[0] ?? priority.notes[0] ?? executionShortText(priority)
    };
  }
  return { code: null, action: 'WAIT', side: 'WAIT', note: positions.length ? '等待持仓风控信号。' : '空仓等待低吸触发。' };
}

function frameworkStageLabel(framework?: QuantFrameworkResponse): string {
  if (!framework) return '无数据';
  if (framework.validation.live_trading_ready) return '可执行';
  if (framework.validation.blockers.length) return '验证未通过';
  if (framework.validation.evidence_strength === 'medium-low') return '研究级验证中';
  return '观察中';
}

function frameworkConclusion(framework: QuantFrameworkResponse | undefined, primary: ReturnType<typeof pickPrimaryExecution>): string {
  if (!framework) return '暂无量化链路，先不做交易动作';
  if (!framework.validation.live_trading_ready) {
    if (primary.side === 'SELL') return `研究级信号触发风控优先：${primary.note}`;
    if (primary.side === 'BUY') return `研究级信号出现买入触发：${primary.note}`;
    if (primary.side === 'HOLD') return `研究级信号建议持有跟踪：${primary.note}`;
    return `当前无买入触发，系统保持等待：${primary.note}`;
  }
  return primary.note;
}

function executionRank(item: QuantExecutionAdvice): number {
  if (item.side === 'SELL') return 0;
  if (item.side === 'BUY') return 1;
  if (item.side === 'HOLD') return 2;
  if (item.blockers.length) return 3;
  return 4;
}

function actionLabel(value: string): string {
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
    AVOID: '回避',
    WAIT: '等待',
    WATCH: '观察',
    BUY: '买入',
    SELL: '卖出'
  };
  return map[value] ?? value;
}

function actionColor(side: string): string {
  const map: Record<string, string> = { BUY: 'green', SELL: 'red', HOLD: 'blue', WAIT: 'orange', AVOID: 'red' };
  return map[side] ?? 'default';
}

function evidenceLabel(value?: string): string {
  const map: Record<string, string> = { high: '高', medium: '中', 'medium-low': '中低', low: '低' };
  return value ? map[value] ?? value : '-';
}

function evidenceColor(value?: string): string {
  if (value === 'high') return 'green';
  if (value === 'medium') return 'blue';
  if (value === 'medium-low') return 'orange';
  return 'red';
}

function riskLabel(value?: string): string {
  const map: Record<string, string> = { low: '低风险', medium: '中风险', high: '高风险' };
  return value ? map[value] ?? value : '-';
}

function riskColor(value?: string): string {
  if (value === 'high') return 'red';
  if (value === 'medium') return 'orange';
  if (value === 'low') return 'green';
  return 'default';
}

function rebalanceLabel(value: string): string {
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

function assetTypeLabel(value: string): string {
  const map: Record<string, string> = { direction: '方向', etf: 'ETF', etf_action: '动作' };
  return map[value] ?? value;
}

function roleLabel(value: string): string {
  const map: Record<string, string> = { mainline_candidate: '主线候选', monitor: '监控', main: '主要', backup: '备选', watch: '观察', held_position: '持仓' };
  return map[value] ?? value;
}

function insightTypeLabel(value: string): string {
  const map: Record<string, string> = { mainline_regime: '主线阶段', carrier_alpha: 'ETF Alpha', position_management: '持仓管理' };
  return map[value] ?? value;
}

function directionColor(value: string): string {
  if (value === 'UP') return 'green';
  if (value === 'DOWN') return 'red';
  if (value === 'FLAT') return 'orange';
  return 'default';
}

function scoreColor(value: number): string {
  if (value >= 75) return '#15803d';
  if (value >= 58) return '#2563eb';
  if (value >= 40) return '#d97706';
  return '#dc2626';
}

function formatPercentNumber(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '-';
  return `${value.toFixed(1)}%`;
}

function formatSignedPercent(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '-';
  return `${value > 0 ? '+' : ''}${value.toFixed(2)}%`;
}

function formatDelta(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '-';
  return `${value > 0 ? '+' : ''}${value.toFixed(0)}%`;
}

function priceRange(low: number | null | undefined, high: number | null | undefined): string {
  if (low == null && high == null) return '-';
  return `${formatPrice(low)} - ${formatPrice(high)}`;
}

function formatPrice(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '-';
  return value.toFixed(3);
}

function formatDateTime(value?: string | null): string {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false });
}

function formatFeatureValue(value: unknown): string {
  if (typeof value === 'number') return Number.isInteger(value) ? value.toFixed(0) : value.toFixed(2);
  if (typeof value === 'string') return value;
  if (value == null) return '-';
  return String(value);
}

function getErrorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  return String(error);
}

export default App;
