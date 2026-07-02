import { useEffect, useMemo, useState, type ReactNode } from 'react';
import {
  Alert,
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
  ActionDecisionResponse,
  AiStatus,
  AiSummaryKind,
  AiSummaryReport,
  DataQualityResponse,
  HealthResponse,
  IntegrationStatus,
  MarketDirection,
  MarketFlowResponse,
  PoolRecommendationItem,
  PoolRecommendationResponse,
  Position,
  PositionInput,
  QuantDecisionResponse,
  QuantEtfDecision,
  WebSessionInfo
} from './types';

const { Header, Content } = Layout;
const { Text, Title } = Typography;

function invalidateTradingQueries(queryClient: QueryClient, token: string) {
  queryClient.invalidateQueries({ queryKey: ['market-flow', token] });
  queryClient.invalidateQueries({ queryKey: ['pool-recommendation', token] });
  queryClient.invalidateQueries({ queryKey: ['quant-decision', token] });
  queryClient.invalidateQueries({ queryKey: ['action-decisions', token] });
  queryClient.invalidateQueries({ queryKey: ['positions', token] });
  queryClient.invalidateQueries({ queryKey: ['data-quality', token] });
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
  const marketFlowQuery = useProtectedQuery(['market-flow', sessionToken], sessionToken, ({ signal }) => api.getMarketFlow(sessionToken, false, signal), autoRefresh ? 60_000 : false);
  const poolRecommendationQuery = useProtectedQuery(['pool-recommendation', sessionToken], sessionToken, ({ signal }) => api.getPoolRecommendation(sessionToken, signal), autoRefresh ? 60_000 : false);
  const quantDecisionQuery = useProtectedQuery(['quant-decision', sessionToken], sessionToken, ({ signal }) => api.getQuantDecision(sessionToken, signal), autoRefresh ? 30_000 : false);
  const actionDecisionQuery = useProtectedQuery(['action-decisions', sessionToken], sessionToken, ({ signal }) => api.getActionDecisions(sessionToken, signal), autoRefresh ? 30_000 : false);
  const positionsQuery = useProtectedQuery(['positions', sessionToken], sessionToken, ({ signal }) => api.getPositions(sessionToken, signal), autoRefresh ? 30_000 : false);
  const dataQualityQuery = useProtectedQuery(['data-quality', sessionToken], sessionToken, ({ signal }) => api.getDataQuality(sessionToken, signal), autoRefresh ? 30_000 : false);
  const integrationsQuery = useProtectedQuery(['integrations', sessionToken], sessionToken, ({ signal }) => api.getIntegrations(sessionToken, signal), autoRefresh ? 60_000 : false);
  const aiStatusQuery = useProtectedQuery(['ai-status', sessionToken], sessionToken, ({ signal }) => api.getAiStatus(sessionToken, signal), autoRefresh ? 60_000 : false);
  const aiSummariesQuery = useProtectedQuery(['ai-summaries', sessionToken], sessionToken, ({ signal }) => api.getAiSummaries(sessionToken, signal), autoRefresh ? 60_000 : false);

  const protectedErrors = [
    sessionQuery.error,
    marketFlowQuery.error,
    poolRecommendationQuery.error,
    quantDecisionQuery.error,
    actionDecisionQuery.error,
    positionsQuery.error,
    dataQualityQuery.error,
    integrationsQuery.error,
    aiStatusQuery.error,
    aiSummariesQuery.error
  ].filter(Boolean);
  const unauthorized = protectedErrors.some((error) => error instanceof ApiError && error.status === 401);
  const refreshing = [healthQuery, sessionQuery, marketFlowQuery, poolRecommendationQuery, quantDecisionQuery, actionDecisionQuery, positionsQuery, dataQualityQuery, integrationsQuery, aiStatusQuery, aiSummariesQuery].some((query) => query.isFetching);
  const firstLoad = Boolean(sessionToken) && [marketFlowQuery, quantDecisionQuery, actionDecisionQuery, positionsQuery].some((query) => query.isLoading);

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
    onSuccess: (data) => {
      queryClient.setQueryData(['market-flow', sessionToken], data);
      invalidateTradingQueries(queryClient, sessionToken);
      message.success('方向已刷新');
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

  const refreshAll = () => {
    queryClient.invalidateQueries();
  };

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
            <Text className="brand-subtitle">量化决策台</Text>
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

      <Content className="content">
        {!sessionToken ? (
          <section className="panel center-panel">
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="请先登录" />
          </section>
        ) : firstLoad ? (
          <section className="panel center-panel"><Spin tip="加载量化结论" /></section>
        ) : (
          <DecisionConsole
            health={healthQuery.data}
            session={sessionQuery.data}
            marketFlow={marketFlowQuery.data}
            poolRecommendation={poolRecommendationQuery.data}
            quantDecision={quantDecisionQuery.data}
            actionDecisions={actionDecisionQuery.data}
            positions={positionsQuery.data ?? []}
            dataQuality={dataQualityQuery.data}
            integrations={integrationsQuery.data ?? []}
            aiStatus={aiStatusQuery.data}
            aiSummaries={aiSummariesQuery.data}
            draft={positionDraft}
            setDraft={setPositionDraft}
            onSavePosition={savePosition}
            savingPosition={savePositionMutation.isPending}
            onDeletePosition={(code) => deletePositionMutation.mutate(code)}
            deletingPosition={deletePositionMutation.isPending}
            deletingCode={deletePositionMutation.variables ?? null}
            onRefreshDirection={() => forceRefreshMutation.mutate()}
            refreshingDirection={forceRefreshMutation.isPending}
            onToggleAi={(enabled) => aiToggleMutation.mutate(enabled)}
            togglingAi={aiToggleMutation.isPending}
            onGenerateAi={(kind) => aiGenerateMutation.mutate(kind)}
            generatingAi={aiGenerateMutation.isPending}
            generatingKind={aiGenerateMutation.variables ?? null}
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

interface DecisionConsoleProps {
  health?: HealthResponse;
  session?: WebSessionInfo;
  marketFlow?: MarketFlowResponse;
  poolRecommendation?: PoolRecommendationResponse;
  quantDecision?: QuantDecisionResponse;
  actionDecisions?: ActionDecisionResponse;
  positions: Position[];
  dataQuality?: DataQualityResponse;
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
  onRefreshDirection: () => void;
  refreshingDirection: boolean;
  onToggleAi: (enabled: boolean) => void;
  togglingAi: boolean;
  onGenerateAi: (kind: AiSummaryKind | string) => void;
  generatingAi: boolean;
  generatingKind: AiSummaryKind | string | null;
  errorMessage: string | null;
}

function DecisionConsole(props: DecisionConsoleProps) {
  const targetEtfs = useMemo(() => getTargetEtfs(props.quantDecision, props.poolRecommendation), [props.quantDecision, props.poolRecommendation]);
  const positionCodes = new Set(props.positions.map((item) => item.code));
  const positionActions = (props.actionDecisions?.items ?? []).filter((item) => item.has_position || positionCodes.has(item.code));
  const monitorActions = (props.actionDecisions?.items ?? []).filter((item) => !item.has_position && !positionCodes.has(item.code));
  const primaryAction = pickPrimaryAction(props.actionDecisions, props.positions);
  const topDirection = props.marketFlow?.directions?.[0];
  const warnings = [props.errorMessage, props.health?.last_warning, ...(props.quantDecision?.warnings ?? []), ...(props.marketFlow?.warnings ?? []), ...(props.poolRecommendation?.warnings ?? [])]
    .filter((item): item is string => Boolean(item))
    .slice(0, 4);

  return (
    <main className="decision-console">
      {warnings.map((warning) => <Alert key={warning} type="warning" showIcon message={warning} />)}
      <section className="hero-panel">
        <div className="hero-copy">
          <Text className="eyebrow">当前结论</Text>
          <h1>{props.quantDecision?.conclusion ?? '暂无量化结论，先不做主动交易动作'}</h1>
          <Space size={[6, 6]} wrap>
            <Tag color="blue">方向 {props.quantDecision?.direction.direction_label ?? topDirection?.direction_label ?? '-'}</Tag>
            <Tag color={phaseColor(props.quantDecision?.direction.phase ?? topDirection?.state)}>{props.quantDecision?.direction.phase_label ?? marketStateLabel(topDirection?.state)}</Tag>
            <Tag>置信 {confidenceLabel(props.quantDecision?.direction.confidence)}</Tag>
            <Tag color={qualityGate(props.dataQuality).color}>数据 {qualityGate(props.dataQuality).label}</Tag>
          </Space>
        </div>
        <div className="hero-command">
          <Text className="eyebrow">现在动作</Text>
          <div className="command-action"><ActionTag action={primaryAction.action} side={primaryAction.side} /></div>
          <Text>{primaryAction.note}</Text>
        </div>
      </section>

      <section className="grid two-columns">
        <MainlinePanel marketFlow={props.marketFlow} quantDecision={props.quantDecision} onRefresh={props.onRefreshDirection} loading={props.refreshingDirection} />
        <ActionPanel actionDecisions={props.actionDecisions} monitorActions={monitorActions} positions={props.positions} />
      </section>

      <section className="grid two-columns wide-left">
        <TargetPoolPanel items={targetEtfs} poolRecommendation={props.poolRecommendation} />
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
      </section>

      <section className="grid two-columns">
        <EvidencePanel marketFlow={props.marketFlow} quantDecision={props.quantDecision} />
        <AiPanel status={props.aiStatus} report={props.aiSummaries} onToggle={props.onToggleAi} toggling={props.togglingAi} onGenerate={props.onGenerateAi} generating={props.generatingAi} generatingKind={props.generatingKind} />
      </section>

      <SystemFooter health={props.health} session={props.session} dataQuality={props.dataQuality} integrations={props.integrations} actionDecisions={props.actionDecisions} />
    </main>
  );
}

function MainlinePanel({ marketFlow, quantDecision, onRefresh, loading }: { marketFlow?: MarketFlowResponse; quantDecision?: QuantDecisionResponse; onRefresh: () => void; loading: boolean }) {
  const top = marketFlow?.directions?.[0];
  const scores = [
    ['主线', quantDecision?.direction.mainline_probability ?? top?.mainline_probability],
    ['驻留', quantDecision?.direction.residency_score ?? top?.residency_score],
    ['承接', quantDecision?.direction.retention_score ?? top?.retention_score],
    ['低吸', quantDecision?.direction.low_buy_readiness_score ?? top?.low_buy_readiness_score]
  ];
  return (
    <Panel title="主线阶段" icon={<ThunderboltOutlined />} extra={<Button size="small" icon={<ReloadOutlined />} loading={loading} onClick={onRefresh}>刷新</Button>}>
      <div className="direction-title">{quantDecision?.direction.direction_label ?? top?.direction_label ?? '-'}</div>
      <Text className="muted">{quantDecision?.direction.operation ?? top?.capital_status ?? '等待方向确认'}</Text>
      <div className="score-grid">
        {scores.map(([label, value]) => <ScoreBox key={label} label={String(label)} value={typeof value === 'number' ? value : null} />)}
      </div>
      <div className="mini-list">
        {(marketFlow?.directions ?? []).slice(0, 3).map((direction) => <DirectionRow key={direction.direction_key} direction={direction} />)}
      </div>
    </Panel>
  );
}

function DirectionRow({ direction }: { direction: MarketDirection }) {
  return (
    <div className="row-card">
      <div>
        <Text strong>{direction.direction_label}</Text>
        <Text className="muted">{marketStateLabel(direction.state)} · {formatAmount(direction.total_amount)}</Text>
      </div>
      <Space size={4} wrap>
        <ScoreText value={direction.mainline_probability} />
        <PercentText value={direction.avg_change_pct} />
      </Space>
    </div>
  );
}

function ActionPanel({ actionDecisions, monitorActions, positions }: { actionDecisions?: ActionDecisionResponse; monitorActions: ActionDecisionItem[]; positions: Position[] }) {
  const items = monitorActions.slice(0, 4);
  return (
    <Panel title="动作" icon={<SafetyCertificateOutlined />} meta={actionDecisions ? actionStatusLabel(actionDecisions.status) : '-'}>
      <div className="rule-note">
        {positions.length ? '已有持仓先按持仓风控处理，目标池变化只作为换仓证据。' : '空仓只看目标池和低吸触发，不追当日热点。'}
      </div>
      <div className="mini-list">
        {items.map((item) => <ActionRow item={item} key={item.code} />)}
        {!items.length && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无监控动作" />}
      </div>
    </Panel>
  );
}

function ActionRow({ item }: { item: ActionDecisionItem }) {
  return (
    <div className="row-card">
      <div>
        <Text strong>{item.name}</Text>
        <Text className="muted">{item.code} · {item.execution_note}</Text>
      </div>
      <ActionTag action={item.action} side={item.side} />
    </div>
  );
}

function TargetPoolPanel({ items, poolRecommendation }: { items: TargetEtf[]; poolRecommendation?: PoolRecommendationResponse }) {
  return (
    <Panel title="目标池" icon={<LineChartOutlined />} meta={poolRecommendation ? poolStatusLabel(poolRecommendation.status) : '-'}>
      <div className="target-grid">
        {items.slice(0, 3).map((item) => <TargetEtfCard key={item.code} item={item} />)}
        {!items.length && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无目标ETF" />}
      </div>
    </Panel>
  );
}

function TargetEtfCard({ item }: { item: TargetEtf }) {
  return (
    <article className="target-card">
      <div className="card-head">
        <Space size={4} wrap>
          <Tag color={item.role === 'backup' ? 'gold' : 'blue'}>{item.role === 'backup' ? '备选' : '主要'}</Tag>
          <Tag>{item.directionLabel ?? '-'}</Tag>
        </Space>
        <ScoreText value={item.score} />
      </div>
      <div className="card-name">{item.name}</div>
      <Text className="muted">{item.code}</Text>
      <div className="metric-grid">
        <Metric label="现价" value={formatPrice(item.price)} />
        <Metric label="溢价" value={<PercentText value={item.premiumPct} neutral />} />
        <Metric label="低吸" value={item.buyLow != null || item.buyHigh != null ? `${formatPrice(item.buyLow)} - ${formatPrice(item.buyHigh)}` : entryBiasLabel(item.entryBias)} />
        <Metric label="动作" value={<ActionTag action={item.action} side={item.side} />} />
      </div>
      <TagList items={item.reasons.slice(0, 3)} />
      <TagList items={item.risks.slice(0, 2)} color="orange" />
    </article>
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
        {!positions.length && <Alert type="info" showIcon message="当前空仓：只等待目标ETF低吸触发。" />}
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

function EvidencePanel({ marketFlow, quantDecision }: { marketFlow?: MarketFlowResponse; quantDecision?: QuantDecisionResponse }) {
  const direction = marketFlow?.directions?.[0];
  const evidence = quantDecision?.direction.evidence?.length ? quantDecision.direction.evidence : direction?.evidence ?? [];
  const risks = quantDecision?.direction.risk_flags?.length ? quantDecision.direction.risk_flags : direction?.risk_flags ?? [];
  const stock = direction?.linked_stocks?.[0] ?? direction?.representative_stock;
  return (
    <Panel title="证据" icon={<CheckCircleOutlined />} meta={marketFlow ? formatDateTime(marketFlow.generated_at) : '-'}>
      <div className="evidence-columns">
        <div>
          <Text className="metric-label">确认</Text>
          <TagList items={evidence.slice(0, 6)} />
        </div>
        <div>
          <Text className="metric-label">风险</Text>
          <TagList items={risks.slice(0, 6)} color="orange" empty="暂无突出风险" />
        </div>
      </div>
      {stock && (
        <div className="strong-stock">
          <Text className="metric-label">强股验证</Text>
          <div className="row-card">
            <div>
              <Text strong>{stock.name}</Text>
              <Text className="muted">{stock.code} · {stock.board_name ?? direction?.direction_label ?? '-'}</Text>
            </div>
            <Space size={4}><ScoreText value={stock.score} /><PercentText value={stock.change_pct} /></Space>
          </div>
        </div>
      )}
    </Panel>
  );
}

function AiPanel({ status, report, onToggle, toggling, onGenerate, generating, generatingKind }: { status?: AiStatus; report?: AiSummaryReport; onToggle: (enabled: boolean) => void; toggling: boolean; onGenerate: (kind: AiSummaryKind | string) => void; generating: boolean; generatingKind: AiSummaryKind | string | null }) {
  const latest = report?.summaries?.[0];
  return (
    <Panel title="AI" icon={<BulbOutlined />} meta={status ? `${status.calls_used_today}/${status.daily_call_limit}` : '-'} extra={<Switch checked={Boolean(status?.enabled)} loading={toggling} onChange={onToggle} disabled={!status?.configured} checkedChildren="开" unCheckedChildren="关" />}>
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

function SystemFooter({ health, session, dataQuality, integrations, actionDecisions }: { health?: HealthResponse; session?: WebSessionInfo; dataQuality?: DataQualityResponse; integrations: IntegrationStatus[]; actionDecisions?: ActionDecisionResponse }) {
  const gate = qualityGate(dataQuality);
  const okIntegrations = integrations.filter((item) => item.ok).length;
  return (
    <section className="system-strip">
      <StatusMetric icon={<ApiOutlined />} label="服务" value={health?.ok ? '在线' : '异常'} color={health?.ok ? 'green' : 'red'} />
      <StatusMetric icon={<SafetyCertificateOutlined />} label="数据" value={gate.label} color={gate.color} />
      <StatusMetric icon={<ThunderboltOutlined />} label="动作域" value={actionDecisions?.scope === 'fixed_pool_plus_positions' ? '监控+持仓' : actionDecisions?.scope ?? '-'} />
      <StatusMetric icon={<CheckCircleOutlined />} label="基础设施" value={`${okIntegrations}/${integrations.length || 0}`} />
      <StatusMetric icon={<UserOutlined />} label="会话" value={session?.username ?? '-'} />
    </section>
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

function Metric({ label, value }: { label: string; value: ReactNode }) {
  return <div className="metric"><Text className="metric-label">{label}</Text><div className="metric-value">{value}</div></div>;
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

interface TargetEtf {
  code: string;
  name: string;
  role: string | null;
  action: string;
  side: string;
  score: number;
  directionLabel: string | null;
  price: number | null;
  premiumPct: number | null;
  entryBias: string | null;
  buyLow: number | null;
  buyHigh: number | null;
  reasons: string[];
  risks: string[];
}

function getTargetEtfs(quant?: QuantDecisionResponse, pool?: PoolRecommendationResponse): TargetEtf[] {
  const poolItems = (pool?.items ?? [])
    .filter((item) => item.recommended_role)
    .sort((a, b) => (a.rank ?? 99) - (b.rank ?? 99));
  if (poolItems.length) return poolItems.map(targetFromPoolItem);
  return (quant?.etfs ?? []).slice(0, 3).map(targetFromQuantEtf);
}

function targetFromPoolItem(item: PoolRecommendationItem): TargetEtf {
  return {
    code: item.code,
    name: item.name,
    role: item.recommended_role,
    action: item.action,
    side: item.action === 'promote' ? 'BUY' : item.action === 'replace_candidate' ? 'SELL' : 'WAIT',
    score: item.score,
    directionLabel: item.direction_label,
    price: item.price,
    premiumPct: item.premium_pct,
    entryBias: item.entry_bias,
    buyLow: null,
    buyHigh: null,
    reasons: item.reasons,
    risks: item.risk_flags
  };
}

function targetFromQuantEtf(item: QuantEtfDecision): TargetEtf {
  return {
    code: item.code,
    name: item.name,
    role: item.role,
    action: item.action,
    side: quantActionSide(item.action),
    score: item.score,
    directionLabel: item.direction_label,
    price: item.price,
    premiumPct: null,
    entryBias: null,
    buyLow: item.buy_zone_low,
    buyHigh: item.buy_zone_high,
    reasons: item.reasons,
    risks: item.risk_flags
  };
}

function pickPrimaryAction(decisions?: ActionDecisionResponse, positions: Position[] = []) {
  const items = decisions?.items ?? [];
  const executable = items.find((item) => item.side === 'SELL') ?? items.find((item) => item.side === 'BUY');
  if (executable) return { action: executable.action, side: executable.side, note: executable.execution_note };
  const held = items.find((item) => item.has_position || positions.some((position) => position.code === item.code));
  if (held) return { action: held.action, side: held.side, note: held.execution_note };
  const watch = items[0];
  if (watch) return { action: watch.action, side: watch.side, note: watch.execution_note };
  return { action: 'WAIT', side: 'WAIT', note: positions.length ? '等待持仓动作信号。' : '空仓等待目标ETF低吸触发。' };
}

function qualityGate(dataQuality?: DataQualityResponse) {
  if (!dataQuality) return { label: '无数据', color: 'default' };
  if (dataQuality.blocked_codes.length || dataQuality.overall_score < 70) return { label: '阻断', color: 'red' };
  if (dataQuality.warnings.length || dataQuality.overall_score < 90) return { label: '谨慎', color: 'orange' };
  return { label: '可信', color: 'green' };
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
    promote: '纳入目标',
    replace_candidate: '替换候选',
    watch: '观察',
    keep: '保留'
  };
  return map[value] ?? value;
}

function actionColor(side: string): string {
  const map: Record<string, string> = { BUY: 'green', SELL: 'red', HOLD: 'blue', WAIT: 'orange', AVOID: 'red' };
  return map[side] ?? 'default';
}

function actionStatusLabel(value: string): string {
  const map: Record<string, string> = { risk_exit: '风险离场', sell_or_reduce: '卖出/减仓', buy_available: '可买入', wait_low_buy: '等待低吸', wait: '等待' };
  return map[value] ?? value;
}

function poolStatusLabel(value: string): string {
  const map: Record<string, string> = { keep: '保持', partial_rotate: '部分更新', rotate: '需要更新', no_recommendation: '暂无建议' };
  return map[value] ?? value;
}

function marketStateLabel(value?: string): string {
  const map: Record<string, string> = { confirmed_mainline: '确认主线', candidate: '候选主线', hot_today: '当日热点', weakening: '弱化', watch_direction: '观察', weak_direction: '弱方向' };
  return value ? map[value] ?? value : '-';
}

function phaseColor(value?: string | null): string {
  if (!value) return 'default';
  if (value.includes('main_up') || value === 'confirmed_mainline') return 'green';
  if (value === 'candidate') return 'blue';
  if (value === 'hot_today' || value === 'overheated') return 'orange';
  if (value === 'weakening' || value === 'weak_direction') return 'red';
  return 'default';
}

function confidenceLabel(value?: string | null): string {
  const map: Record<string, string> = { high: '高', medium: '中', 'medium-low': '中低', low: '低' };
  return value ? map[value] ?? value : '-';
}

function entryBiasLabel(value?: string | null): string {
  const map: Record<string, string> = { watch_low_buy: '低吸观察', pullback_watch: '回踩观察', direction_hot_wait_pullback: '偏热等回落', avoid_premium: '溢价回避', wait: '等待' };
  return value ? map[value] ?? value : '-';
}

function quantActionSide(action: string): string {
  if (action.startsWith('SELL') || action === 'REDUCE_OR_HOLD_TIGHT' || action === 'replace_candidate') return 'SELL';
  if (action.startsWith('BUY') || action === 'promote') return 'BUY';
  if (action === 'AVOID') return 'AVOID';
  if (action === 'HOLD' || action === 'HOLD_WATCH') return 'HOLD';
  return 'WAIT';
}

function scoreColor(value: number): string {
  if (value >= 75) return '#15803d';
  if (value >= 58) return '#2563eb';
  if (value >= 40) return '#d97706';
  return '#dc2626';
}

function formatAmount(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '-';
  const abs = Math.abs(value);
  if (abs >= 100_000_000) return `${(value / 100_000_000).toFixed(2)}亿`;
  if (abs >= 10_000) return `${(value / 10_000).toFixed(1)}万`;
  return value.toFixed(0);
}

function formatPrice(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '-';
  return value.toFixed(3);
}

function formatDateTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false });
}

function getErrorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  return String(error);
}

export default App;
