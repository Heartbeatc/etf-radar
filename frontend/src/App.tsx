import { type ReactNode, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  App as AntdApp,
  Badge,
  Button,
  Card,
  Col,
  Empty,
  Grid,
  Input,
  Layout,
  Modal,
  Progress,
  Row,
  Space,
  Spin,
  Statistic,
  Switch,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Typography
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import {
  ApiOutlined,
  BarChartOutlined,
  CheckCircleOutlined,
  DashboardOutlined,
  DatabaseOutlined,
  LineChartOutlined,
  LockOutlined,
  LogoutOutlined,
  ReloadOutlined,
  SafetyCertificateOutlined,
  ThunderboltOutlined,
  UserOutlined,
  WarningOutlined,
  BulbOutlined
} from '@ant-design/icons';
import ReactECharts from 'echarts-for-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ApiError, SESSION_STORAGE_KEY, api } from './api';
import type {
  ActionDecisionItem,
  ActionDecisionResponse,
  AiStatus,
  AiSummaryItem,
  AiSummaryKind,
  AiSummaryReport,
  DataQualityItem,
  DataQualityResponse,
  DiscoveryDirection,
  DiscoveryEtfCandidate,
  DiscoveryResponse,
  HealthResponse,
  IntegrationStatus,
  LatestResponse,
  MarketDirection,
  MarketFlowResponse,
  PoolRecommendationItem,
  PoolRecommendationResponse,
  RiskItem,
  RiskResponse,
  TradingPlan,
  WebSessionInfo
} from './types';

const { Header, Content } = Layout;
const { Text, Title } = Typography;
const { useBreakpoint } = Grid;

function App() {
  const queryClient = useQueryClient();
  const { message } = AntdApp.useApp();
  const [sessionToken, setSessionToken] = useState(() => window.localStorage.getItem(SESSION_STORAGE_KEY) ?? '');
  const [loginOpen, setLoginOpen] = useState(!sessionToken);
  const [loginUsername, setLoginUsername] = useState('admin');
  const [loginPassword, setLoginPassword] = useState('');
  const [autoRefresh, setAutoRefresh] = useState(true);
  const isMobile = useIsMobileLayout();

  const healthQuery = useQuery({
    queryKey: ['health'],
    queryFn: ({ signal }) => api.getHealth(signal),
    refetchInterval: autoRefresh ? 30_000 : false
  });

  const sessionQuery = useProtectedQuery(
    ['auth-session', sessionToken],
    sessionToken,
    ({ signal }) => api.getSession(sessionToken, signal),
    autoRefresh ? 60_000 : false
  );
  const latestQuery = useProtectedQuery(['latest', sessionToken], sessionToken, ({ signal }) => api.getLatest(sessionToken, signal), autoRefresh ? 30_000 : false);
  const discoveryQuery = useProtectedQuery(
    ['discovery', sessionToken],
    sessionToken,
    ({ signal }) => api.getDiscovery(sessionToken, false, signal),
    autoRefresh ? 60_000 : false
  );
  const marketFlowQuery = useProtectedQuery(
    ['market-flow', sessionToken],
    sessionToken,
    ({ signal }) => api.getMarketFlow(sessionToken, false, signal),
    autoRefresh ? 60_000 : false
  );
  const poolRecommendationQuery = useProtectedQuery(
    ['pool-recommendation', sessionToken],
    sessionToken,
    ({ signal }) => api.getPoolRecommendation(sessionToken, signal),
    autoRefresh ? 60_000 : false
  );
  const actionDecisionQuery = useProtectedQuery(['action-decisions', sessionToken], sessionToken, ({ signal }) => api.getActionDecisions(sessionToken, signal), autoRefresh ? 30_000 : false);
  const riskQuery = useProtectedQuery(['risk', sessionToken], sessionToken, ({ signal }) => api.getRisk(sessionToken, signal), autoRefresh ? 30_000 : false);
  const dataQualityQuery = useProtectedQuery(
    ['data-quality', sessionToken],
    sessionToken,
    ({ signal }) => api.getDataQuality(sessionToken, signal),
    autoRefresh ? 30_000 : false
  );
  const integrationsQuery = useProtectedQuery(
    ['integrations', sessionToken],
    sessionToken,
    ({ signal }) => api.getIntegrations(sessionToken, signal),
    autoRefresh ? 30_000 : false
  );
  const aiStatusQuery = useProtectedQuery(
    ['ai-status', sessionToken],
    sessionToken,
    ({ signal }) => api.getAiStatus(sessionToken, signal),
    autoRefresh ? 60_000 : false
  );
  const aiSummariesQuery = useProtectedQuery(
    ['ai-summaries', sessionToken],
    sessionToken,
    ({ signal }) => api.getAiSummaries(sessionToken, signal),
    autoRefresh ? 60_000 : false
  );

  const clearSession = (openLogin = true) => {
    window.localStorage.removeItem(SESSION_STORAGE_KEY);
    setSessionToken('');
    setLoginPassword('');
    queryClient.clear();
    if (openLogin) {
      setLoginOpen(true);
    }
  };

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

  const forceDiscoveryMutation = useMutation({
    mutationFn: () => api.getDiscovery(sessionToken, true),
    onSuccess: (data) => {
      queryClient.setQueryData(['discovery', sessionToken], data);
      message.success('方向已刷新');
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

  const protectedErrors = [sessionQuery.error, latestQuery.error, discoveryQuery.error, marketFlowQuery.error, poolRecommendationQuery.error, actionDecisionQuery.error, riskQuery.error, dataQualityQuery.error, integrationsQuery.error, aiStatusQuery.error, aiSummariesQuery.error].filter(Boolean);
  const unauthorized = protectedErrors.some((error) => error instanceof ApiError && error.status === 401);
  const refreshing = [healthQuery, sessionQuery, latestQuery, discoveryQuery, marketFlowQuery, poolRecommendationQuery, actionDecisionQuery, riskQuery, dataQualityQuery, integrationsQuery, aiStatusQuery, aiSummariesQuery].some((query) => query.isFetching);
  const firstLoad = Boolean(sessionToken) && [sessionQuery, latestQuery, discoveryQuery, marketFlowQuery, riskQuery, dataQualityQuery].some((query) => query.isLoading);

  useEffect(() => {
    if (unauthorized && sessionToken) {
      clearSession(true);
      message.warning('登录已过期，请重新登录');
    }
  }, [unauthorized, sessionToken]);

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
    if (token) {
      api.logout(token).catch(() => undefined);
    }
    message.success('已退出');
  };

  const refreshAll = () => {
    queryClient.invalidateQueries();
  };

  return (
    <Layout className="app-shell">
      <Header className="topbar">
        <div className="brand">
          <span className="brand-mark"><LineChartOutlined /></span>
          <div>
            <Title level={4} className="brand-title">ETF Radar</Title>
            <Text className="brand-subtitle">A股场内ETF交易工作台</Text>
          </div>
        </div>
        <Space size="middle" wrap className="top-actions">
          <BackendBadge health={healthQuery.data} loading={healthQuery.isFetching} />
          <SessionBadge session={sessionQuery.data} loading={sessionQuery.isFetching} hasToken={Boolean(sessionToken)} compact={isMobile} />
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
        <Alert className="boundary-alert" type="info" showIcon message="仅作研究和纪律提醒，不自动下单。" />
        {!sessionToken ? (
          <section className="panel empty-panel">
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="请先登录" />
          </section>
        ) : (
          <>
            {unauthorized && <Alert className="stack-alert" type="error" showIcon message="登录已过期或无效" />}
            {healthQuery.data?.last_warning && <Alert className="stack-alert" type="warning" showIcon message={healthQuery.data.last_warning} />}
            {firstLoad && !latestQuery.data && !discoveryQuery.data ? (
              <div className="loading-box"><Spin tip="加载中" /></div>
            ) : (
              <Dashboard
                latest={latestQuery.data}
                discovery={discoveryQuery.data}
                marketFlow={marketFlowQuery.data}
                poolRecommendation={poolRecommendationQuery.data}
                actionDecisions={actionDecisionQuery.data}
                risk={riskQuery.data}
                dataQuality={dataQualityQuery.data}
                integrations={integrationsQuery.data ?? []}
                aiStatus={aiStatusQuery.data}
                aiSummaries={aiSummariesQuery.data}
                onToggleAi={(enabled) => aiToggleMutation.mutate(enabled)}
                togglingAi={aiToggleMutation.isPending}
                onGenerateAi={(kind) => aiGenerateMutation.mutate(kind)}
                generatingAiKind={aiGenerateMutation.variables ?? null}
                generatingAi={aiGenerateMutation.isPending}
                onForceDiscovery={() => forceDiscoveryMutation.mutate()}
                forcingDiscovery={forceDiscoveryMutation.isPending}
                errorMessage={protectedErrors.length ? getErrorMessage(protectedErrors[0]) : null}
              />
            )}
          </>
        )}
      </Content>

      <Modal
        title="网页登录"
        open={loginOpen}
        width={isMobile ? 'calc(100vw - 24px)' : 520}
        onOk={submitLogin}
        onCancel={() => sessionToken && setLoginOpen(false)}
        okText="登录"
        cancelText="关闭"
        closable={Boolean(sessionToken)}
        maskClosable={Boolean(sessionToken)}
        destroyOnClose={false}
        okButtonProps={{ loading: loginMutation.isPending }}
        cancelButtonProps={!sessionToken ? { style: { display: 'none' } } : undefined}
      >
        <Space direction="vertical" size="middle" className="modal-body">
          <Input
            prefix={<UserOutlined />}
            value={loginUsername}
            onChange={(event) => setLoginUsername(event.target.value)}
            onPressEnter={submitLogin}
            placeholder="用户名"
            autoFocus
          />
          <Input.Password
            prefix={<LockOutlined />}
            value={loginPassword}
            onChange={(event) => setLoginPassword(event.target.value)}
            onPressEnter={submitLogin}
            placeholder="密码"
          />
          {sessionQuery.data?.expires_at && <Text className="muted">当前会话到期：{formatDateTime(sessionQuery.data.expires_at)}</Text>}
        </Space>
      </Modal>
    </Layout>
  );
}

function useProtectedQuery<T>(
  queryKey: readonly unknown[],
  token: string,
  queryFn: (context: { signal?: AbortSignal }) => Promise<T>,
  refetchInterval: number | false
) {
  return useQuery({
    queryKey,
    queryFn,
    enabled: Boolean(token),
    refetchInterval,
    retry: false
  });
}

function useIsMobileLayout() {
  const screens = useBreakpoint();
  return !screens.md;
}

interface DashboardProps {
  latest?: LatestResponse;
  discovery?: DiscoveryResponse;
  marketFlow?: MarketFlowResponse;
  poolRecommendation?: PoolRecommendationResponse;
  actionDecisions?: ActionDecisionResponse;
  risk?: RiskResponse;
  dataQuality?: DataQualityResponse;
  integrations: IntegrationStatus[];
  aiStatus?: AiStatus;
  aiSummaries?: AiSummaryReport;
  onToggleAi: (enabled: boolean) => void;
  togglingAi: boolean;
  onGenerateAi: (kind: AiSummaryKind | string) => void;
  generatingAiKind: AiSummaryKind | string | null;
  generatingAi: boolean;
  onForceDiscovery: () => void;
  forcingDiscovery: boolean;
  errorMessage: string | null;
}

function Dashboard(props: DashboardProps) {
  const { latest, discovery, marketFlow, poolRecommendation, actionDecisions, risk, dataQuality, integrations, aiStatus, aiSummaries, onToggleAi, togglingAi, onGenerateAi, generatingAiKind, generatingAi, onForceDiscovery, forcingDiscovery, errorMessage } = props;
  const isMobile = useIsMobileLayout();

  const tabItems = [
    {
      key: 'overview',
      label: <span><DashboardOutlined /> 总览</span>,
      children: <OverviewTab latest={latest} discovery={discovery} marketFlow={marketFlow} actionDecisions={actionDecisions} risk={risk} dataQuality={dataQuality} onForceDiscovery={onForceDiscovery} forcingDiscovery={forcingDiscovery} />
    },
    {
      key: 'market-flow',
      label: <span><ThunderboltOutlined /> 市场流向</span>,
      children: <MarketFlowTab marketFlow={marketFlow} />
    },
    {
      key: 'discovery',
      label: <span><LineChartOutlined /> ETF载体</span>,
      children: <DiscoveryTab latest={latest} discovery={discovery} marketFlow={marketFlow} poolRecommendation={poolRecommendation} onForceDiscovery={onForceDiscovery} forcingDiscovery={forcingDiscovery} />
    },
    {
      key: 'actions',
      label: <span><SafetyCertificateOutlined /> 动作决策</span>,
      children: <ActionDecisionTab decisions={actionDecisions} />
    },
    {
      key: 'signals',
      label: <span><BarChartOutlined /> 交易信号</span>,
      children: <SignalsTab latest={latest} />
    },
    {
      key: 'risk',
      label: <span><SafetyCertificateOutlined /> 风控</span>,
      children: <RiskTab risk={risk} />
    },
    {
      key: 'ai',
      label: <span><BulbOutlined /> AI总结</span>,
      children: <AiSummaryTab status={aiStatus} report={aiSummaries} onToggle={onToggleAi} toggling={togglingAi} onGenerate={onGenerateAi} generatingKind={generatingAiKind} generating={generatingAi} />
    },
    {
      key: 'quality',
      label: <span><DatabaseOutlined /> 数据质量</span>,
      children: <QualityTab dataQuality={dataQuality} integrations={integrations} />
    }
  ];

  return (
    <>
      {errorMessage && <Alert className="stack-alert" type="error" showIcon message={errorMessage} />}
      <MetricStrip latest={latest} discovery={discovery} marketFlow={marketFlow} risk={risk} dataQuality={dataQuality} integrations={integrations} />
      <Tabs className="work-tabs" items={tabItems} destroyInactiveTabPane={false} size={isMobile ? 'small' : 'middle'} tabBarGutter={isMobile ? 12 : 24} />
    </>
  );
}

interface OverviewTabProps {
  latest?: LatestResponse;
  discovery?: DiscoveryResponse;
  marketFlow?: MarketFlowResponse;
  actionDecisions?: ActionDecisionResponse;
  risk?: RiskResponse;
  dataQuality?: DataQualityResponse;
  onForceDiscovery: () => void;
  forcingDiscovery: boolean;
}

function OverviewTab({ latest, discovery, marketFlow, actionDecisions, risk, dataQuality, onForceDiscovery, forcingDiscovery }: OverviewTabProps) {
  return (
    <Space direction="vertical" size="large" className="wide-stack">
      <ActionDecisionSummary decisions={actionDecisions} />
      <MarketFlowSummary marketFlow={marketFlow} compact />
      <CandidateCards latest={latest} discovery={discovery} marketFlow={marketFlow} onForceDiscovery={onForceDiscovery} forcingDiscovery={forcingDiscovery} compact />
      <Row gutter={[16, 16]}>
        <Col xs={24} xl={14}>
          <section className="panel">
            <SectionHeader icon={<BarChartOutlined />} title="固定池信号" meta={latest ? latestDataTimeMeta(latest) : '-'} />
            <SignalTable data={latest?.plans ?? []} compact />
          </section>
        </Col>
        <Col xs={24} xl={10}>
          <section className="panel">
            <SectionHeader icon={<SafetyCertificateOutlined />} title="风险状态" meta={risk ? formatDateTime(risk.generated_at) : '-'} />
            <RiskList risk={risk} />
          </section>
        </Col>
      </Row>
      <Row gutter={[16, 16]}>
        <Col xs={24} xl={14}>
          <section className="panel chart-panel">
            <SectionHeader icon={<ThunderboltOutlined />} title="方向强度" meta={discovery ? `${discovery.filtered_count}/${discovery.universe_count}` : '-'} />
            <DirectionChart directions={discovery?.directions ?? []} />
          </section>
        </Col>
        <Col xs={24} xl={10}>
          <section className="panel">
            <SectionHeader icon={<DatabaseOutlined />} title="数据质量" meta={qualityGateMeta(dataQuality)} />
            <QualitySummary dataQuality={dataQuality} />
          </section>
        </Col>
      </Row>
    </Space>
  );
}


function MarketFlowTab({ marketFlow }: { marketFlow?: MarketFlowResponse }) {
  return (
    <Space direction="vertical" size="large" className="wide-stack">
      {marketFlow?.warnings.map((warning) => <Alert key={warning} type="warning" showIcon message={warning} />)}
      <MarketFlowSummary marketFlow={marketFlow} />
      <section className="panel">
        <SectionHeader icon={<ThunderboltOutlined />} title="方向明细" meta={marketFlow ? `${marketFlow.board_count} 个板块 · ${marketFlow.stock_sample_count} 个成分股样本` : '-'} />
        <MarketDirectionTable data={marketFlow?.directions ?? []} />
      </section>
    </Space>
  );
}

function MarketFlowSummary({ marketFlow, compact = false }: { marketFlow?: MarketFlowResponse; compact?: boolean }) {
  const data = marketFlow?.directions.slice(0, compact ? 3 : 5) ?? [];
  return (
    <section className="panel">
      <SectionHeader icon={<ThunderboltOutlined />} title="市场资金流向" meta={marketFlow ? `${marketFlow.source} · ${formatDateTime(marketFlow.generated_at)}` : '-'} />
      {data.length ? <MarketDirectionTable data={data} compact={compact} /> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无市场流向" />}
    </section>
  );
}

function MarketDirectionTable({ data, compact = false }: { data: MarketDirection[]; compact?: boolean }) {
  const isMobile = useIsMobileLayout();
  if (isMobile) {
    return <MarketDirectionCards data={data} compact={compact} />;
  }

  const columns: ColumnsType<MarketDirection> = [
    {
      title: '方向',
      key: 'direction',
      fixed: 'left',
      width: 210,
      render: (_, record) => (
        <Space direction="vertical" size={2}>
          <Text strong>{record.direction_label}</Text>
          <Space size={4} wrap>
            <MarketStateTag value={record.state} />
            <Tag>{record.capital_status}</Tag>
          </Space>
        </Space>
      )
    },
    { title: '主线概率', dataIndex: 'mainline_probability', key: 'mainline_probability', width: 130, render: (value: number) => <ScoreCell value={value} /> },
    {
      title: '驻留/承接',
      key: 'residency',
      width: 150,
      render: (_, record) => (
        <Space direction="vertical" size={0} className="compact-score-stack">
          <MetricLabel label="驻留" value={<ScoreText value={record.residency_score} />} />
          <MetricLabel label="承接" value={<ScoreText value={record.retention_score} />} />
        </Space>
      )
    },
    {
      title: '低吸/动作',
      key: 'action',
      width: 150,
      render: (_, record) => (
        <Space direction="vertical" size={4}>
          <ScoreText value={record.low_buy_readiness_score} />
          <TradeActionTag value={record.trade_action} />
        </Space>
      )
    },
    { title: '资金占比', dataIndex: 'capital_concentration_pct', key: 'capital_concentration_pct', width: 105, render: (value: number | null) => <PercentValue value={value} neutral /> },
    { title: '均涨幅', dataIndex: 'avg_change_pct', key: 'avg_change_pct', width: 100, render: (value: number | null) => <PercentValue value={value} /> },
    { title: '扩散度', dataIndex: 'breadth_pct', key: 'breadth_pct', width: 100, render: (value: number | null) => <PercentValue value={value} neutral /> },
    { title: '成交额', dataIndex: 'total_amount', key: 'total_amount', width: 120, render: formatAmount },
    { title: '资金流代理', dataIndex: 'main_net_inflow', key: 'main_net_inflow', width: 120, render: (value: number | null) => <MoneyValue value={value} /> },
    {
      title: '强股验证',
      key: 'stock',
      width: compact ? 190 : 240,
      render: (_, record) => <StrongStockCell direction={record} />
    },
    {
      title: '2主1备ETF',
      key: 'etfs',
      width: compact ? 170 : 240,
      render: (_, record) => <LinkedEtfsCell direction={record} />
    },
    {
      title: '因子',
      key: 'factors',
      width: compact ? 180 : 240,
      render: (_, record) => <FactorScoresCell direction={record} />
    },
    {
      title: '强板块',
      key: 'boards',
      width: compact ? 190 : 260,
      render: (_, record) => <BoardTags direction={record} />
    }
  ];
  return <Table rowKey="direction_key" columns={columns} dataSource={data} size="middle" pagination={false} scroll={{ x: compact ? 1800 : 2060 }} />;
}

function ScoreText({ value }: { value: number }) {
  return <Text strong style={{ color: scoreColor(value) }}>{value.toFixed(0)}</Text>;
}

function StrongStockCell({ direction }: { direction: MarketDirection }) {
  const stocks = direction.linked_stocks?.length ? direction.linked_stocks : direction.representative_stock ? [direction.representative_stock] : [];
  if (!stocks.length) {
    return <Text className="muted">-</Text>;
  }
  return (
    <Space direction="vertical" size={4}>
      {stocks.slice(0, 3).map((stock) => (
        <Tooltip key={stock.code} title={`${stock.name} · ${stock.score}分 · ${stock.verifier_role}`}>
          <Tag color={stock.verifier_role === 'leader' ? 'blue' : 'default'}>
            {stock.name} {stock.change_pct != null ? formatPct(stock.change_pct) : ''}
          </Tag>
        </Tooltip>
      ))}
    </Space>
  );
}

function LinkedEtfsCell({ direction }: { direction: MarketDirection }) {
  const items = getDirectionCarrierEtfs(direction);
  if (!items.length) {
    return <Text className="muted">-</Text>;
  }
  return (
    <Space size={[0, 4]} wrap>
      {items.map((item) => (
        <Tooltip key={`${item.role}-${item.code}`} title={`${item.name} · ETF分 ${item.score} · 映射分 ${item.mapping_score ?? '-'}`}>
          <Tag color={item.role === 'backup' ? 'gold' : item.role === 'main' ? 'blue' : 'default'}>{item.role === 'backup' ? '备' : item.role === 'main' ? '主' : '观'} {item.code}</Tag>
        </Tooltip>
      ))}
    </Space>
  );
}

function FactorScoresCell({ direction }: { direction: MarketDirection }) {
  const factors = direction.factor_scores ?? {};
  const entries = [
    ['资金', factors.capital_weight],
    ['流入', factors.flow_proxy],
    ['扩散', factors.breadth],
    ['龙头', factors.leadership],
    ['ETF', factors.etf_confirmation]
  ].filter(([, value]) => typeof value === 'number') as [string, number][];
  if (!entries.length) {
    return <Text className="muted">-</Text>;
  }
  return (
    <Space size={[0, 4]} wrap>
      {entries.map(([label, value]) => (
        <Tag key={label} color={value >= 70 ? 'green' : value >= 55 ? 'blue' : value >= 40 ? 'orange' : 'red'}>{label} {value}</Tag>
      ))}
    </Space>
  );
}


function BoardTags({ direction }: { direction: MarketDirection }) {
  if (!direction.top_boards.length) {
    return <Text className="muted">-</Text>;
  }
  return (
    <Space size={[0, 4]} wrap>
      {direction.top_boards.slice(0, 3).map((board) => (
        <Tooltip key={board.code} title={`成交 ${formatAmount(board.amount)} · 净流 ${formatAmount(board.main_net_inflow)}`}>
          <Tag color={board.score >= 80 ? 'blue' : 'default'}>{board.name}</Tag>
        </Tooltip>
      ))}
    </Space>
  );
}

function DiscoveryTab({ latest, discovery, marketFlow, poolRecommendation, onForceDiscovery, forcingDiscovery }: { latest?: LatestResponse; discovery?: DiscoveryResponse; marketFlow?: MarketFlowResponse; poolRecommendation?: PoolRecommendationResponse; onForceDiscovery: () => void; forcingDiscovery: boolean }) {
  const candidates = useMemo(() => getDiscoveryCandidates(discovery), [discovery]);

  return (
    <Space direction="vertical" size="large" className="wide-stack">
      <CandidateCards latest={latest} discovery={discovery} marketFlow={marketFlow} onForceDiscovery={onForceDiscovery} forcingDiscovery={forcingDiscovery} />
      <PoolRecommendationPanel recommendation={poolRecommendation} />
      <section className="panel">
        <SectionHeader icon={<ThunderboltOutlined />} title="ETF方向库" meta={discovery ? formatDateTime(discovery.generated_at) : '-'} />
        <DirectionTable data={discovery?.directions ?? []} />
      </section>
      <section className="panel">
        <SectionHeader icon={<BarChartOutlined />} title="全市场ETF候选库" meta={`${candidates.length} 个`} />
        <CandidateTable data={candidates} />
      </section>
    </Space>
  );
}

function SignalsTab({ latest }: { latest?: LatestResponse }) {
  return (
    <section className="panel">
      <SectionHeader icon={<BarChartOutlined />} title="交易信号" meta={latest ? latestDataTimeMeta(latest) : '-'} />
      <SignalTable data={latest?.plans ?? []} />
    </section>
  );
}

function ActionDecisionTab({ decisions }: { decisions?: ActionDecisionResponse }) {
  return (
    <Space direction="vertical" size="large" className="wide-stack">
      <ActionDecisionSummary decisions={decisions} />
      <section className="panel">
        <SectionHeader icon={<SafetyCertificateOutlined />} title="固定池动作明细" meta={decisions ? `${actionPortfolioStatusLabel(decisions.status)} · ${formatDateTime(decisions.generated_at)}` : '-'} />
        {decisions ? <ActionDecisionTable data={decisions.items} /> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无动作决策" />}
      </section>
      {decisions?.warnings.map((warning) => <Alert key={warning} type="warning" showIcon message={warning} />)}
    </Space>
  );
}

function ActionDecisionSummary({ decisions }: { decisions?: ActionDecisionResponse }) {
  const items = decisions?.items ?? [];
  const immediate = items.filter((item) => item.side === 'BUY' || item.side === 'SELL');
  return (
    <section className="panel">
      <SectionHeader icon={<SafetyCertificateOutlined />} title="当下动作" meta={decisions ? `${actionPortfolioStatusLabel(decisions.status)} · ${decisions.market_status}` : '-'} />
      {decisions ? (
        <div className="action-card-grid">
          {items.map((item) => (
            <article className="action-card" key={item.code}>
              <Space direction="vertical" size="small" className="card-stack">
                <Space wrap>
                  <ActionTag action={item.action} side={item.side} />
                  <Tag color={item.has_position ? 'green' : 'default'}>{item.has_position ? '有持仓' : '无持仓'}</Tag>
                  <Tag>{urgencyLabel(item.urgency)}</Tag>
                </Space>
                <div>
                  <div className="candidate-name">{item.name}</div>
                  <Text className="muted">{item.code} · {roleLabel(item.role)}</Text>
                </div>
                <Progress percent={clamp(item.action_score)} size="small" strokeColor={actionColor(item.side)} />
                <div className="candidate-metrics">
                  <MetricLabel label="现价" value={formatPrice(item.current_price)} />
                  <MetricLabel label="买区" value={`${formatPrice(item.buy_zone_low)} - ${formatPrice(item.buy_zone_high)}`} />
                  <MetricLabel label="止盈一" value={formatPrice(item.first_take_profit_price)} />
                  <MetricLabel label="防守" value={formatPrice(item.effective_exit_price)} />
                </div>
              </Space>
            </article>
          ))}
          {!items.length && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无动作" />}
        </div>
      ) : (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无动作决策" />
      )}
      {decisions && <Text className="metric-foot">可执行动作 {immediate.length}/{items.length}；动态ETF载体未进入固定池前不生成买卖动作。</Text>}
    </section>
  );
}

function ActionDecisionTable({ data }: { data: ActionDecisionItem[] }) {
  const columns: ColumnsType<ActionDecisionItem> = [
    { title: '动作', key: 'action', fixed: 'left', width: 140, render: (_, record) => <ActionTag action={record.action} side={record.side} /> },
    {
      title: 'ETF',
      key: 'etf',
      fixed: 'left',
      width: 210,
      render: (_, record) => (
        <Space direction="vertical" size={0}>
          <Text strong>{record.name}</Text>
          <Text className="muted">{record.code} · {record.has_position ? '有持仓' : '无持仓'}</Text>
        </Space>
      )
    },
    { title: '动作分', dataIndex: 'action_score', key: 'action_score', width: 110, render: (value: number) => <ScoreCell value={value} /> },
    { title: '置信', dataIndex: 'confidence', key: 'confidence', width: 90 },
    { title: '现价', dataIndex: 'current_price', key: 'current_price', width: 90, render: formatPrice },
    { title: '低吸区间', key: 'buy_zone', width: 150, render: (_, record) => `${formatPrice(record.buy_zone_low)} - ${formatPrice(record.buy_zone_high)}` },
    { title: '回避价', dataIndex: 'avoid_above', key: 'avoid_above', width: 90, render: formatPrice },
    { title: '止盈一', dataIndex: 'first_take_profit_price', key: 'first_take_profit_price', width: 90, render: formatPrice },
    { title: '止盈二', dataIndex: 'second_take_profit_price', key: 'second_take_profit_price', width: 90, render: formatPrice },
    { title: '防守线', dataIndex: 'effective_exit_price', key: 'effective_exit_price', width: 90, render: formatPrice },
    { title: '低吸分', dataIndex: 'low_buy_score', key: 'low_buy_score', width: 90, render: (value: number) => <ScoreText value={value} /> },
    { title: '持有分', dataIndex: 'hold_score', key: 'hold_score', width: 90, render: (value: number) => <ScoreText value={value} /> },
    { title: '止盈分', dataIndex: 'take_profit_score', key: 'take_profit_score', width: 90, render: (value: number) => <ScoreText value={value} /> },
    { title: '风险分', dataIndex: 'risk_score', key: 'risk_score', width: 90, render: (value: number) => <Text strong style={{ color: riskScoreColor(value) }}>{value}</Text> },
    { title: '理由', dataIndex: 'reasons', key: 'reasons', width: 260, render: (items: string[]) => <PoolReasonTags items={items} /> },
    { title: '风险', dataIndex: 'risk_flags', key: 'risk_flags', width: 260, render: (items: string[]) => <PoolReasonTags items={items} color="orange" /> }
  ];
  return <Table rowKey="code" columns={columns} dataSource={data} size="middle" pagination={false} scroll={{ x: 1900 }} />;
}

function ActionTag({ action, side }: { action: string; side: string }) {
  return <Tag color={actionColor(side)}>{actionLabel(action)}</Tag>;
}

function RiskTab({ risk }: { risk?: RiskResponse }) {
  return (
    <Space direction="vertical" size="large" className="wide-stack">
      <section className="panel">
        <SectionHeader icon={<SafetyCertificateOutlined />} title="风险表" meta={risk ? risk.risk_budget_state : '-'} />
        <RiskTable data={risk?.items ?? []} />
      </section>
      <section className="panel">
        <SectionHeader icon={<WarningOutlined />} title="规则" meta={`${risk?.rules.length ?? 0} 条`} />
        <div className="rule-list">
          {(risk?.rules ?? []).map((rule) => <Tag key={rule}>{rule}</Tag>)}
        </div>
      </section>
    </Space>
  );
}

function AiSummaryTab({ status, report, onToggle, toggling, onGenerate, generatingKind, generating }: { status?: AiStatus; report?: AiSummaryReport; onToggle: (enabled: boolean) => void; toggling: boolean; onGenerate: (kind: AiSummaryKind | string) => void; generatingKind: AiSummaryKind | string | null; generating: boolean }) {
  const windows = status?.windows ?? [];
  const summaries = report?.summaries ?? [];
  return (
    <Space direction="vertical" size="large" className="wide-stack">
      <section className="panel">
        <SectionHeader icon={<BulbOutlined />} title="AI状态" meta={status ? `${status.model} · ${status.calls_used_today}/${status.daily_call_limit}` : '-'} />
        <div className="ai-control-row">
          <Space wrap>
            <Switch checked={Boolean(status?.enabled)} disabled={!status || toggling} loading={toggling} onChange={onToggle} checkedChildren="开启" unCheckedChildren="关闭" />
            <Tag color={status?.configured ? 'green' : 'red'}>{status?.configured ? 'DeepSeek已配置' : '未配置Key'}</Tag>
            <Tag>每日上限 {status?.daily_call_limit ?? '-'}</Tag>
            <Tag>强制冷却 {status ? Math.round(status.force_cooldown_seconds / 60) : '-'} 分钟</Tag>
          </Space>
        </div>
        {report?.warnings.map((warning) => <Alert key={warning} className="stack-alert" type="warning" showIcon message={warning} />)}
        <div className="ai-window-grid">
          {windows.map((window) => (
            <article className="ai-window" key={window.kind}>
              <div>
                <Text strong>{window.title}</Text>
                <Text className="muted">{window.start} - {window.end}</Text>
              </div>
              <Button size="small" onClick={() => onGenerate(window.kind)} loading={generating && generatingKind === window.kind} disabled={!status?.enabled || !status.configured}>生成</Button>
            </article>
          ))}
        </div>
      </section>
      <section className="panel">
        <SectionHeader icon={<BulbOutlined />} title="时段总结" meta={report ? formatDateTime(report.generated_at) : '-'} />
        {summaries.length ? (
          <div className="ai-summary-list">
            {summaries.map((item) => <AiSummaryCard key={`${item.kind}-${item.trading_date}`} item={item} />)}
          </div>
        ) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无AI总结" />}
      </section>
    </Space>
  );
}

function AiSummaryCard({ item }: { item: AiSummaryItem }) {
  return (
    <article className="ai-summary-card">
      <div className="ai-summary-head">
        <div>
          <Text strong>{item.title}</Text>
          <Text className="muted">{item.trading_date} · {item.source_data_time ? `行情 ${formatDateTime(item.source_data_time)}` : `生成 ${formatDateTime(item.generated_at)}`}</Text>
        </div>
        <Tag color={item.status === 'ok' ? 'blue' : 'red'}>{item.status === 'ok' ? '已生成' : '异常'}</Tag>
      </div>
      <p className="ai-summary-text">{item.summary}</p>
      {item.error && <Text className="muted">{item.error}</Text>}
    </article>
  );
}

function QualityTab({ dataQuality, integrations }: { dataQuality?: DataQualityResponse; integrations: IntegrationStatus[] }) {
  return (
    <Row gutter={[16, 16]}>
      <Col xs={24} xl={16}>
        <section className="panel">
          <SectionHeader icon={<DatabaseOutlined />} title="数据质量闸门" meta={qualityGateMeta(dataQuality)} />
          <QualityGatePanel dataQuality={dataQuality} />
        </section>
      </Col>
      <Col xs={24} xl={8}>
        <section className="panel">
          <SectionHeader icon={<ApiOutlined />} title="基础设施" meta={`${integrations.length} 项`} />
          <IntegrationTable data={integrations} />
        </section>
      </Col>
    </Row>
  );
}

function MetricStrip({ latest, discovery, marketFlow, risk, dataQuality, integrations }: Pick<DashboardProps, 'latest' | 'discovery' | 'marketFlow' | 'risk' | 'dataQuality' | 'integrations'>) {
  const topDirection = marketFlow?.directions?.[0] ?? discovery?.directions?.[0];
  const carrierSet = getCarrierCandidateSet(marketFlow, discovery);
  const firstMain = carrierSet.candidates[0];
  const secondMain = carrierSet.candidates[1];
  const integrationOk = integrations.filter((item) => item.ok).length;
  const qualityGate = getQualityGate(dataQuality);

  return (
    <Row gutter={[12, 12]} className="metric-row">
      <Col xs={24} sm={12} lg={6}>
        <Card className="metric-card">
          <Statistic title="当前主线" value={topDirection?.direction_label ?? '-'} prefix={<ThunderboltOutlined />} valueStyle={{ fontSize: 20 }} />
          {topDirection && <Text className="metric-foot">强度 {topDirection.score} · 成交 {formatAmount(topDirection.total_amount)}</Text>}
        </Card>
      </Col>
      <Col xs={24} sm={12} lg={6}>
        <Card className="metric-card">
          <Statistic title="载体一" value={firstMain?.code ?? latest?.top_low_buy ?? '-'} prefix={<LineChartOutlined />} valueStyle={{ fontSize: 20 }} />
          {firstMain && <Text className="metric-foot">{firstMain.name}</Text>}
        </Card>
      </Col>
      <Col xs={24} sm={12} lg={6}>
        <Card className="metric-card">
          <Statistic title="载体二" value={secondMain?.code ?? latest?.top_hold ?? '-'} prefix={<BarChartOutlined />} valueStyle={{ fontSize: 20 }} />
          {secondMain && <Text className="metric-foot">{secondMain.name}</Text>}
        </Card>
      </Col>
      <Col xs={24} sm={12} lg={6}>
        <Card className="metric-card">
          <Statistic title="风险/数据" value={`${risk?.risk_budget_state ?? '-'} / ${qualityGate.label}`} prefix={<SafetyCertificateOutlined />} valueStyle={{ fontSize: 20 }} />
          <Text className="metric-foot">数据状态 {qualityGate.label} · 基础设施 {integrationOk}/{integrations.length || 0}</Text>
        </Card>
      </Col>
    </Row>
  );
}

function CandidateCards({ latest, discovery, marketFlow, onForceDiscovery, forcingDiscovery, compact = false }: { latest?: LatestResponse; discovery?: DiscoveryResponse; marketFlow?: MarketFlowResponse; onForceDiscovery: () => void; forcingDiscovery: boolean; compact?: boolean }) {
  const carrierSet = getCarrierCandidateSet(marketFlow, discovery);
  const candidates = carrierSet.candidates;
  const fixedPoolCodes = getFixedPoolCodes(latest);
  const matchedCount = candidates.filter((candidate) => fixedPoolCodes.has(candidate.code)).length;
  const hasPoolMismatch = fixedPoolCodes.size > 0 && candidates.length > 0 && matchedCount < candidates.length;

  return (
    <section className="panel">
      <SectionHeader
        icon={<ThunderboltOutlined />}
        title="ETF载体候选"
        meta={carrierCandidateMeta(carrierSet)}
        extra={<Button icon={<ReloadOutlined />} onClick={onForceDiscovery} loading={forcingDiscovery}>刷新ETF库</Button>}
      />
      {carrierSet.direction && (
        <div className="carrier-context">
          <Space size={[0, 4]} wrap>
            <Tag color="blue">方向 {carrierSet.direction.direction_label}</Tag>
            <MarketStateTag value={carrierSet.direction.state} />
            <TradeActionTag value={carrierSet.direction.trade_action} />
            <Tag>主线 {carrierSet.direction.mainline_probability}</Tag>
            <Tag>低吸 {carrierSet.direction.low_buy_readiness_score}</Tag>
          </Space>
        </div>
      )}
      {carrierSet.source === 'discovery' && candidates.length > 0 && (
        <div className="carrier-context">
          <Tag color="orange">ETF库兜底</Tag>
        </div>
      )}
      {candidates.length > 0 && fixedPoolCodes.size > 0 && (
        <div className="carrier-context">
          <Tag color={hasPoolMismatch ? 'orange' : 'green'}>固定池匹配 {matchedCount}/{candidates.length}</Tag>
          {hasPoolMismatch && <Text className="muted">未入固定池的载体只代表方向机会，暂无低吸/止盈/风控信号。</Text>}
        </div>
      )}
      {candidates.length ? (
        <div className={compact ? 'candidate-grid compact' : 'candidate-grid'}>
          {candidates.map((candidate) => {
            const score = carrierScore(candidate);
            return (
              <article key={`${candidate.role}-${candidate.code}`} className="candidate-card">
                <Space direction="vertical" size="small" className="card-stack">
                  <Space wrap>
                    <Tag color={candidate.role === 'backup' ? 'gold' : 'blue'}>{roleLabel(candidate.role)}</Tag>
                    <Tag color={fixedPoolCodes.has(candidate.code) ? 'green' : 'orange'}>{fixedPoolCodes.has(candidate.code) ? '固定池内' : '未入固定池'}</Tag>
                    <EntryBiasTag value={candidate.entry_bias} />
                    {candidate.risk_flags.map((flag) => <Tag color="red" key={flag}>{flag}</Tag>)}
                  </Space>
                  <div>
                    <div className="candidate-name">{candidate.name}</div>
                    <Text className="muted">{candidate.code} · {candidate.direction_label}</Text>
                  </div>
                  <Progress percent={clamp(score)} size="small" strokeColor={scoreColor(score)} />
                  <div className="candidate-metrics">
                    <MetricLabel label="适配" value={<ScoreText value={score} />} />
                    <MetricLabel label="成交" value={formatAmount(candidate.amount)} />
                    <MetricLabel label="净流" value={<MoneyValue value={candidate.main_net_inflow} />} />
                    <MetricLabel label="溢价" value={<PercentValue value={candidate.premium_pct} neutral />} />
                  </div>
                </Space>
              </article>
            );
          })}
        </div>
      ) : (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无ETF载体" />
      )}
    </section>
  );
}

function PoolRecommendationPanel({ recommendation }: { recommendation?: PoolRecommendationResponse }) {
  return (
    <section className="panel">
      <SectionHeader icon={<SafetyCertificateOutlined />} title="固定池量化建议" meta={recommendation ? `${poolStatusLabel(recommendation.status)} · ${formatDateTime(recommendation.generated_at)}` : '-'} />
      {!recommendation ? (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无固定池建议" />
      ) : (
        <Space direction="vertical" size="middle" className="wide-stack">
          <div className="pool-summary-grid">
            <MetricLabel label="当前主要" value={recommendation.current_main_codes.join(', ') || '-'} />
            <MetricLabel label="当前备选" value={recommendation.current_backup_codes.join(', ') || '-'} />
            <MetricLabel label="建议主要" value={recommendation.recommended_main_codes.join(', ') || '-'} />
            <MetricLabel label="建议备选" value={recommendation.recommended_backup_codes.join(', ') || '-'} />
          </div>
          {recommendation.warnings.map((warning) => <Alert key={warning} type="warning" showIcon message={warning} />)}
          <PoolRecommendationTable data={recommendation.items} />
        </Space>
      )}
    </section>
  );
}

function PoolRecommendationTable({ data }: { data: PoolRecommendationItem[] }) {
  const columns: ColumnsType<PoolRecommendationItem> = [
    { title: '动作', dataIndex: 'action', key: 'action', width: 110, render: (value: string) => <Tag color={poolActionColor(value)}>{poolActionLabel(value)}</Tag> },
    {
      title: 'ETF',
      key: 'etf',
      fixed: 'left',
      width: 210,
      render: (_, record) => (
        <Space direction="vertical" size={0}>
          <Text strong>{record.name}</Text>
          <Text className="muted">{record.code}</Text>
        </Space>
      )
    },
    { title: '角色', key: 'role', width: 130, render: (_, record) => `${roleLabel(record.current_role ?? '-') } -> ${roleLabel(record.recommended_role ?? '-')}` },
    { title: '量化分', dataIndex: 'score', key: 'score', width: 110, render: (value: number) => <ScoreCell value={value} /> },
    { title: '方向', dataIndex: 'direction_label', key: 'direction_label', width: 130, render: (value: string | null) => value ?? '-' },
    { title: '状态', dataIndex: 'direction_state', key: 'direction_state', width: 110, render: (value: string | null) => value ? <MarketStateTag value={value} /> : '-' },
    { title: '主线', dataIndex: 'mainline_probability', key: 'mainline_probability', width: 90, render: (value: number | null) => value == null ? '-' : value },
    { title: '低吸', dataIndex: 'low_buy_readiness_score', key: 'low_buy_readiness_score', width: 90, render: (value: number | null) => value == null ? '-' : value },
    { title: '成交额', dataIndex: 'amount', key: 'amount', width: 120, render: formatAmount },
    { title: '溢价', dataIndex: 'premium_pct', key: 'premium_pct', width: 90, render: (value: number | null) => <PercentValue value={value} neutral /> },
    { title: '理由', dataIndex: 'reasons', key: 'reasons', width: 260, render: (reasons: string[]) => <PoolReasonTags items={reasons} /> },
    { title: '风险', dataIndex: 'risk_flags', key: 'risk_flags', width: 240, render: (flags: string[]) => <PoolReasonTags items={flags} color="orange" /> }
  ];
  return <Table rowKey={(record) => `${record.action}-${record.code}`} columns={columns} dataSource={data} size="middle" pagination={false} scroll={{ x: 1640 }} />;
}

function PoolReasonTags({ items, color = 'blue' }: { items: string[]; color?: string }) {
  if (!items.length) {
    return <Text className="muted">-</Text>;
  }
  return (
    <Space size={[0, 4]} wrap>
      {items.slice(0, 4).map((item) => <Tag color={color} key={item}>{item}</Tag>)}
    </Space>
  );
}

function DirectionChart({ directions }: { directions: DiscoveryDirection[] }) {
  const isMobile = useIsMobileLayout();
  const option = useMemo(() => {
    const top = directions.slice(0, isMobile ? 6 : 8);
    return {
      color: ['#1677ff'],
      tooltip: { trigger: 'axis' },
      grid: { left: isMobile ? 30 : 36, right: 12, top: 24, bottom: isMobile ? 82 : 72 },
      xAxis: { type: 'category', data: top.map((item) => item.direction_label), axisLabel: { interval: 0, rotate: isMobile ? 42 : 28, fontSize: isMobile ? 10 : 12 } },
      yAxis: { type: 'value', min: 0, max: 100 },
      series: [
        {
          type: 'bar',
          data: top.map((item) => item.score),
          barMaxWidth: 28,
          itemStyle: { borderRadius: [4, 4, 0, 0] }
        }
      ]
    };
  }, [directions, isMobile]);

  if (!directions.length) {
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无方向" />;
  }

  return <ReactECharts option={option} style={{ height: isMobile ? 260 : 310 }} notMerge lazyUpdate />;
}

function DirectionTable({ data }: { data: DiscoveryDirection[] }) {
  const isMobile = useIsMobileLayout();
  if (isMobile) {
    return <DirectionCards data={data} />;
  }

  const columns: ColumnsType<DiscoveryDirection> = [
    { title: '方向', dataIndex: 'direction_label', key: 'direction_label', fixed: 'left', width: 150 },
    { title: '强度', dataIndex: 'score', key: 'score', width: 140, render: (value: number) => <ScoreCell value={value} /> },
    { title: 'ETF数', dataIndex: 'etf_count', key: 'etf_count', width: 90 },
    { title: '上涨数', dataIndex: 'positive_count', key: 'positive_count', width: 90 },
    { title: '均涨幅', dataIndex: 'avg_change_pct', key: 'avg_change_pct', width: 110, render: (value: number | null) => <PercentValue value={value} /> },
    { title: '成交额', dataIndex: 'total_amount', key: 'total_amount', width: 130, render: formatAmount },
    { title: '正向成交', dataIndex: 'positive_amount_pct', key: 'positive_amount_pct', width: 120, render: (value: number | null) => <PercentValue value={value} neutral /> },
    { title: '主力净流', dataIndex: 'main_net_inflow', key: 'main_net_inflow', width: 130, render: (value: number | null) => <MoneyValue value={value} /> }
  ];
  return <Table rowKey="direction_key" columns={columns} dataSource={data} size="middle" pagination={false} scroll={{ x: 900 }} />;
}

function CandidateTable({ data }: { data: DiscoveryEtfCandidate[] }) {
  const isMobile = useIsMobileLayout();
  if (isMobile) {
    return <CandidateTableCards data={data} />;
  }

  const columns: ColumnsType<DiscoveryEtfCandidate> = [
    { title: '角色', dataIndex: 'role', key: 'role', width: 90, render: (value: string) => <Tag color={value === 'backup' ? 'gold' : 'blue'}>{roleLabel(value)}</Tag> },
    {
      title: 'ETF',
      key: 'etf',
      fixed: 'left',
      width: 220,
      render: (_, record) => (
        <Space direction="vertical" size={0}>
          <Text strong>{record.name}</Text>
          <Text className="muted">{record.code}</Text>
        </Space>
      )
    },
    { title: '方向', dataIndex: 'direction_label', key: 'direction_label', width: 130 },
    { title: '评分', dataIndex: 'score', key: 'score', width: 140, render: (value: number) => <ScoreCell value={value} /> },
    { title: '价格', dataIndex: 'price', key: 'price', width: 90, render: formatPrice },
    { title: '涨跌', dataIndex: 'change_pct', key: 'change_pct', width: 100, render: (value: number | null) => <PercentValue value={value} /> },
    { title: '成交额', dataIndex: 'amount', key: 'amount', width: 120, render: formatAmount },
    { title: '量比', dataIndex: 'volume_ratio', key: 'volume_ratio', width: 90, render: formatNumber },
    { title: '换手', dataIndex: 'turnover_pct', key: 'turnover_pct', width: 100, render: (value: number | null) => <PercentValue value={value} neutral /> },
    { title: '净流', dataIndex: 'main_net_inflow', key: 'main_net_inflow', width: 120, render: (value: number | null) => <MoneyValue value={value} /> },
    { title: '净流占比', dataIndex: 'main_net_inflow_pct', key: 'main_net_inflow_pct', width: 110, render: (value: number | null) => <PercentValue value={value} /> },
    { title: '溢价', dataIndex: 'premium_pct', key: 'premium_pct', width: 100, render: (value: number | null) => <PercentValue value={value} neutral /> },
    { title: '偏向', dataIndex: 'entry_bias', key: 'entry_bias', width: 130, render: (value: string) => <EntryBiasTag value={value} /> }
  ];
  return <Table rowKey={(record) => `${record.role}-${record.code}`} columns={columns} dataSource={data} size="middle" pagination={false} scroll={{ x: 1420 }} />;
}

function SignalTable({ data, compact = false }: { data: TradingPlan[]; compact?: boolean }) {
  const isMobile = useIsMobileLayout();
  if (isMobile) {
    return <SignalCards data={data} compact={compact} />;
  }

  const columns: ColumnsType<TradingPlan> = [
    {
      title: 'ETF',
      key: 'etf',
      fixed: 'left',
      width: 210,
      render: (_, record) => (
        <Space direction="vertical" size={0}>
          <Text strong>{record.name}</Text>
          <Text className="muted">{record.code} · {roleLabel(record.role)}</Text>
        </Space>
      )
    },
    { title: '信号', dataIndex: 'signal', key: 'signal', width: 100, render: (value: string) => <SignalTag value={value} /> },
    { title: '方向', dataIndex: 'direction_score', key: 'direction_score', width: 110, render: (value: number) => <ScoreCell value={value} /> },
    { title: '低吸', dataIndex: 'low_buy_score', key: 'low_buy_score', width: 110, render: (value: number) => <ScoreCell value={value} /> },
    { title: '持有', dataIndex: 'hold_score', key: 'hold_score', width: 110, render: (value: number) => <ScoreCell value={value} /> },
    { title: '止盈', dataIndex: 'take_profit_score', key: 'take_profit_score', width: 110, render: (value: number) => <ScoreCell value={value} /> },
    { title: '风险', dataIndex: 'risk_score', key: 'risk_score', width: 110, render: (value: number) => <RiskScoreCell value={value} /> },
    { title: '现价', dataIndex: 'current_price', key: 'current_price', width: 90, render: formatPrice },
    {
      title: '低吸区间',
      key: 'buy_zone',
      width: 150,
      render: (_, record) => `${formatPrice(record.buy_zone.zone_low)} - ${formatPrice(record.buy_zone.zone_high)}`
    },
    { title: '回避价', key: 'avoid_above', width: 90, render: (_, record) => formatPrice(record.buy_zone.avoid_above) },
    { title: '止盈一', key: 'tp1', width: 90, render: (_, record) => formatPrice(record.take_profit_plan.first_take_profit_price) },
    { title: '止盈二', key: 'tp2', width: 90, render: (_, record) => formatPrice(record.take_profit_plan.second_take_profit_price) },
    { title: '防守线', key: 'exit', width: 100, render: (_, record) => formatPrice(record.exit_plan.effective_exit_price) },
    {
      title: '提示',
      key: 'warnings',
      width: compact ? 180 : 260,
      render: (_, record) => <WarningTags warnings={record.warnings} />
    }
  ];
  return <Table rowKey="code" columns={columns} dataSource={data} size="middle" pagination={false} scroll={{ x: compact ? 1280 : 1600 }} />;
}

function RiskTable({ data }: { data: RiskItem[] }) {
  const isMobile = useIsMobileLayout();
  if (isMobile) {
    return <RiskCards data={data} />;
  }

  const columns: ColumnsType<RiskItem> = [
    {
      title: 'ETF',
      key: 'etf',
      fixed: 'left',
      width: 210,
      render: (_, record) => (
        <Space direction="vertical" size={0}>
          <Text strong>{record.name}</Text>
          <Text className="muted">{record.code}</Text>
        </Space>
      )
    },
    { title: '信号', dataIndex: 'signal', key: 'signal', width: 100, render: (value: string) => <SignalTag value={value} /> },
    { title: '风险等级', dataIndex: 'risk_level', key: 'risk_level', width: 110, render: (value: string) => <RiskLevelTag value={value} /> },
    { title: '风险分', dataIndex: 'risk_score', key: 'risk_score', width: 120, render: (value: number) => <RiskScoreCell value={value} /> },
    { title: '止盈分', dataIndex: 'take_profit_score', key: 'take_profit_score', width: 120, render: (value: number) => <ScoreCell value={value} /> },
    { title: '止盈动作', dataIndex: 'take_profit_action', key: 'take_profit_action', width: 150 },
    { title: '硬止损', dataIndex: 'hard_stop_price', key: 'hard_stop_price', width: 100, render: formatPrice },
    { title: '趋势离场', dataIndex: 'trend_exit_price', key: 'trend_exit_price', width: 100, render: formatPrice },
    { title: '防守线', dataIndex: 'effective_exit_price', key: 'effective_exit_price', width: 100, render: formatPrice },
    { title: '提示', dataIndex: 'warnings', key: 'warnings', render: (warnings: string[]) => <WarningTags warnings={warnings} /> }
  ];
  return <Table rowKey="code" columns={columns} dataSource={data} size="middle" pagination={false} scroll={{ x: 1240 }} />;
}

function QualityTable({ data }: { data: DataQualityItem[] }) {
  const isMobile = useIsMobileLayout();
  if (isMobile) {
    return <QualityCards data={data} />;
  }

  const columns: ColumnsType<DataQualityItem> = [
    {
      title: 'ETF',
      key: 'etf',
      fixed: 'left',
      width: 210,
      render: (_, record) => (
        <Space direction="vertical" size={0}>
          <Text strong>{record.name}</Text>
          <Text className="muted">{record.code} · {roleLabel(record.role)}</Text>
        </Space>
      )
    },
    { title: '状态', dataIndex: 'ok', key: 'ok', width: 90, render: (ok: boolean) => <Badge status={ok ? 'success' : 'error'} text={ok ? '正常' : '异常'} /> },
    { title: '评分', dataIndex: 'score', key: 'score', width: 120, render: (value: number) => <ScoreCell value={value} /> },
    { title: '源', dataIndex: 'source', key: 'source', width: 110, render: (value: string) => <Tag>{value}</Tag> },
    { title: '年龄', dataIndex: 'age_seconds', key: 'age_seconds', width: 90, render: (value: number | null) => value == null ? '-' : `${value.toFixed(0)}s` },
    { title: '价格', dataIndex: 'price', key: 'price', width: 90, render: formatPrice },
    { title: 'IOPV', dataIndex: 'iopv', key: 'iopv', width: 90, render: formatPrice },
    { title: '溢价', dataIndex: 'premium_pct', key: 'premium_pct', width: 100, render: (value: number | null) => <PercentValue value={value} neutral /> },
    { title: '成交额', dataIndex: 'amount', key: 'amount', width: 120, render: formatAmount },
    { title: '净流占比', dataIndex: 'main_net_inflow_pct', key: 'main_net_inflow_pct', width: 110, render: (value: number | null) => <PercentValue value={value} /> },
    { title: '问题', dataIndex: 'issues', key: 'issues', render: (issues: string[]) => <WarningTags warnings={issues} /> }
  ];
  return <Table rowKey="code" columns={columns} dataSource={data} size="middle" pagination={false} scroll={{ x: 1280 }} />;
}

function IntegrationTable({ data }: { data: IntegrationStatus[] }) {
  const isMobile = useIsMobileLayout();
  if (isMobile) {
    return <IntegrationCards data={data} />;
  }

  const columns: ColumnsType<IntegrationStatus> = [
    { title: '组件', dataIndex: 'name', key: 'name', width: 120, render: (value: string) => <Text strong>{value}</Text> },
    { title: '状态', dataIndex: 'ok', key: 'ok', width: 90, render: (ok: boolean) => <Badge status={ok ? 'success' : 'error'} text={ok ? '正常' : '异常'} /> },
    { title: '启用', dataIndex: 'enabled', key: 'enabled', width: 80, render: (enabled: boolean) => enabled ? '是' : '否' },
    { title: '详情', dataIndex: 'detail', key: 'detail', ellipsis: true }
  ];
  return <Table rowKey="name" columns={columns} dataSource={data} size="small" pagination={false} />;
}


function MarketDirectionCards({ data, compact = false }: { data: MarketDirection[]; compact?: boolean }) {
  if (!data.length) {
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无市场流向" />;
  }

  return (
    <div className="mobile-card-list">
      {data.map((record) => (
        <article className="mobile-data-card" key={record.direction_key}>
          <div className="mobile-card-head">
            <div className="mobile-card-title-block">
              <Text strong className="mobile-card-title">{record.direction_label}</Text>
              <Text className="mobile-card-subtitle">成交 {formatAmount(record.total_amount)} · 均涨 {record.avg_change_pct == null ? '-' : formatPct(record.avg_change_pct)}</Text>
            </div>
            <MobileScoreBadge label="主线" value={record.mainline_probability} />
          </div>
          <div className="mobile-card-tags">
            <MarketStateTag value={record.state} />
            <Tag>{record.capital_status}</Tag>
            <TradeActionTag value={record.trade_action} />
          </div>
          <div className="mobile-metric-grid">
            <MobileMetric label="驻留" value={<ScoreText value={record.residency_score} />} />
            <MobileMetric label="承接" value={<ScoreText value={record.retention_score} />} />
            <MobileMetric label="低吸" value={<ScoreText value={record.low_buy_readiness_score} />} />
            <MobileMetric label="扩散" value={<PercentValue value={record.breadth_pct} neutral />} />
            <MobileMetric label="资金占比" value={<PercentValue value={record.capital_concentration_pct} neutral />} />
            <MobileMetric label="资金流" value={<MoneyValue value={record.main_net_inflow} />} />
          </div>
          <MobileCardSection label="强股验证"><StrongStockCell direction={record} /></MobileCardSection>
          <MobileCardSection label="ETF载体"><LinkedEtfsCell direction={record} /></MobileCardSection>
          {!compact && <MobileCardSection label="因子"><FactorScoresCell direction={record} /></MobileCardSection>}
          <MobileCardSection label="强板块"><BoardTags direction={record} /></MobileCardSection>
        </article>
      ))}
    </div>
  );
}

function DirectionCards({ data }: { data: DiscoveryDirection[] }) {
  if (!data.length) {
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无方向" />;
  }

  return (
    <div className="mobile-card-list">
      {data.map((record) => (
        <article className="mobile-data-card" key={record.direction_key}>
          <div className="mobile-card-head">
            <div className="mobile-card-title-block">
              <Text strong className="mobile-card-title">{record.direction_label}</Text>
              <Text className="mobile-card-subtitle">{record.etf_count} 个ETF · {record.positive_count} 个上涨</Text>
            </div>
            <MobileScoreBadge label="强度" value={record.score} />
          </div>
          <div className="mobile-metric-grid">
            <MobileMetric label="均涨幅" value={<PercentValue value={record.avg_change_pct} />} />
            <MobileMetric label="成交额" value={formatAmount(record.total_amount)} />
            <MobileMetric label="正向成交" value={<PercentValue value={record.positive_amount_pct} neutral />} />
            <MobileMetric label="主力净流" value={<MoneyValue value={record.main_net_inflow} />} />
          </div>
        </article>
      ))}
    </div>
  );
}

function CandidateTableCards({ data }: { data: DiscoveryEtfCandidate[] }) {
  if (!data.length) {
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无候选ETF" />;
  }

  return (
    <div className="mobile-card-list">
      {data.map((record) => (
        <article className="mobile-data-card" key={`${record.role}-${record.code}`}>
          <div className="mobile-card-head">
            <div className="mobile-card-title-block">
              <Text strong className="mobile-card-title">{record.name}</Text>
              <Text className="mobile-card-subtitle">{record.code} · {record.direction_label}</Text>
            </div>
            <Tag color={record.role === 'backup' ? 'gold' : 'blue'}>{roleLabel(record.role)}</Tag>
          </div>
          <div className="mobile-card-tags">
            <EntryBiasTag value={record.entry_bias} />
            {record.risk_flags.map((flag) => <Tag color="red" key={flag}>{flag}</Tag>)}
          </div>
          <div className="mobile-metric-grid">
            <MobileMetric label="评分" value={<ScoreText value={record.score} />} />
            <MobileMetric label="价格" value={formatPrice(record.price)} />
            <MobileMetric label="涨跌" value={<PercentValue value={record.change_pct} />} />
            <MobileMetric label="成交额" value={formatAmount(record.amount)} />
            <MobileMetric label="净流" value={<MoneyValue value={record.main_net_inflow} />} />
            <MobileMetric label="溢价" value={<PercentValue value={record.premium_pct} neutral />} />
          </div>
        </article>
      ))}
    </div>
  );
}

function SignalCards({ data, compact = false }: { data: TradingPlan[]; compact?: boolean }) {
  if (!data.length) {
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无交易信号" />;
  }

  return (
    <div className="mobile-card-list">
      {data.map((record) => (
        <article className="mobile-data-card" key={record.code}>
          <div className="mobile-card-head">
            <div className="mobile-card-title-block">
              <Text strong className="mobile-card-title">{record.name}</Text>
              <Text className="mobile-card-subtitle">{record.code} · {roleLabel(record.role)}</Text>
            </div>
            <SignalTag value={record.signal} />
          </div>
          <div className="mobile-metric-grid">
            <MobileMetric label="方向" value={<ScoreText value={record.direction_score} />} />
            <MobileMetric label="低吸" value={<ScoreText value={record.low_buy_score} />} />
            <MobileMetric label="持有" value={<ScoreText value={record.hold_score} />} />
            <MobileMetric label="止盈" value={<ScoreText value={record.take_profit_score} />} />
            <MobileMetric label="风险" value={<Text strong style={{ color: riskScoreColor(record.risk_score) }}>{record.risk_score.toFixed(0)}</Text>} />
            <MobileMetric label="现价" value={formatPrice(record.current_price)} />
          </div>
          <MobileCardSection label="低吸区间">{formatPrice(record.buy_zone.zone_low)} - {formatPrice(record.buy_zone.zone_high)} · 回避 {formatPrice(record.buy_zone.avoid_above)}</MobileCardSection>
          {!compact && <MobileCardSection label="止盈/防守">止盈 {formatPrice(record.take_profit_plan.first_take_profit_price)} / {formatPrice(record.take_profit_plan.second_take_profit_price)} · 防守 {formatPrice(record.exit_plan.effective_exit_price)}</MobileCardSection>}
          <MobileCardSection label="提示"><WarningTags warnings={record.warnings} /></MobileCardSection>
        </article>
      ))}
    </div>
  );
}

function RiskCards({ data }: { data: RiskItem[] }) {
  if (!data.length) {
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无风险" />;
  }

  return (
    <div className="mobile-card-list">
      {data.map((record) => (
        <article className="mobile-data-card" key={record.code}>
          <div className="mobile-card-head">
            <div className="mobile-card-title-block">
              <Text strong className="mobile-card-title">{record.name}</Text>
              <Text className="mobile-card-subtitle">{record.code}</Text>
            </div>
            <RiskLevelTag value={record.risk_level} />
          </div>
          <div className="mobile-card-tags"><SignalTag value={record.signal} /></div>
          <div className="mobile-metric-grid">
            <MobileMetric label="风险分" value={<Text strong style={{ color: riskScoreColor(record.risk_score) }}>{record.risk_score.toFixed(0)}</Text>} />
            <MobileMetric label="止盈分" value={<ScoreText value={record.take_profit_score} />} />
            <MobileMetric label="现价" value={formatPrice(record.current_price)} />
            <MobileMetric label="硬止损" value={formatPrice(record.hard_stop_price)} />
            <MobileMetric label="趋势离场" value={formatPrice(record.trend_exit_price)} />
            <MobileMetric label="防守线" value={formatPrice(record.effective_exit_price)} />
          </div>
          <MobileCardSection label="止盈动作">{record.take_profit_action}</MobileCardSection>
          <MobileCardSection label="提示"><WarningTags warnings={record.warnings} /></MobileCardSection>
        </article>
      ))}
    </div>
  );
}

function QualityCards({ data }: { data: DataQualityItem[] }) {
  if (!data.length) {
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无数据质量" />;
  }

  return (
    <div className="mobile-card-list">
      {data.map((record) => (
        <article className="mobile-data-card" key={record.code}>
          <div className="mobile-card-head">
            <div className="mobile-card-title-block">
              <Text strong className="mobile-card-title">{record.name}</Text>
              <Text className="mobile-card-subtitle">{record.code} · {roleLabel(record.role)}</Text>
            </div>
            <Badge status={record.ok ? 'success' : 'error'} text={record.ok ? '正常' : '异常'} />
          </div>
          <div className="mobile-metric-grid">
            <MobileMetric label="评分" value={<ScoreText value={record.score} />} />
            <MobileMetric label="源" value={<Tag>{record.source}</Tag>} />
            <MobileMetric label="年龄" value={record.age_seconds == null ? '-' : `${record.age_seconds.toFixed(0)}s`} />
            <MobileMetric label="价格" value={formatPrice(record.price)} />
            <MobileMetric label="IOPV" value={formatPrice(record.iopv)} />
            <MobileMetric label="溢价" value={<PercentValue value={record.premium_pct} neutral />} />
            <MobileMetric label="成交额" value={formatAmount(record.amount)} />
            <MobileMetric label="净流占比" value={<PercentValue value={record.main_net_inflow_pct} />} />
          </div>
          <MobileCardSection label="问题"><WarningTags warnings={record.issues} /></MobileCardSection>
        </article>
      ))}
    </div>
  );
}

function IntegrationCards({ data }: { data: IntegrationStatus[] }) {
  if (!data.length) {
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无基础设施状态" />;
  }

  return (
    <div className="mobile-card-list">
      {data.map((record) => (
        <article className="mobile-data-card" key={record.name}>
          <div className="mobile-card-head">
            <Text strong className="mobile-card-title">{record.name}</Text>
            <Badge status={record.ok ? 'success' : 'error'} text={record.ok ? '正常' : '异常'} />
          </div>
          <div className="mobile-metric-grid compact">
            <MobileMetric label="启用" value={record.enabled ? '是' : '否'} />
          </div>
          <MobileCardSection label="详情">{record.detail}</MobileCardSection>
        </article>
      ))}
    </div>
  );
}

function MobileScoreBadge({ label, value }: { label: string; value: number }) {
  return (
    <div className="mobile-score-badge">
      <span>{label}</span>
      <strong style={{ color: scoreColor(value) }}>{value.toFixed(0)}</strong>
    </div>
  );
}

function MobileMetric({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="mobile-metric">
      <Text className="mobile-metric-label">{label}</Text>
      <div className="mobile-metric-value">{value}</div>
    </div>
  );
}

function MobileCardSection({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="mobile-card-section">
      <Text className="mobile-section-label">{label}</Text>
      <div className="mobile-section-body">{children}</div>
    </div>
  );
}

function RiskList({ risk }: { risk?: RiskResponse }) {
  if (!risk?.items.length) {
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无风险" />;
  }

  return (
    <Space direction="vertical" size="middle" className="wide-stack">
      {risk.items.map((item) => (
        <div className="risk-row" key={item.code}>
          <div>
            <Text strong>{item.code}</Text>
            <Text className="risk-name">{item.name}</Text>
          </div>
          <Space>
            <RiskLevelTag value={item.risk_level} />
            <Text className="muted">现价 {formatPrice(item.current_price)} · 防守 {formatPrice(item.effective_exit_price)}</Text>
          </Space>
        </div>
      ))}
    </Space>
  );
}

type QualityGateStatus = 'trusted' | 'caution' | 'blocked' | 'missing';
type QualityBadgeStatus = 'success' | 'warning' | 'error' | 'default';

interface QualityGateView {
  status: QualityGateStatus;
  label: string;
  detail: string;
  scoreText: string;
  tagColor: string;
  badgeStatus: QualityBadgeStatus;
  okCount: number;
  totalCount: number;
  problemItems: DataQualityItem[];
}

function QualitySummary({ dataQuality }: { dataQuality?: DataQualityResponse }) {
  if (!dataQuality) {
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无数据" />;
  }

  const gate = getQualityGate(dataQuality);
  const hasIssues = gate.problemItems.length > 0 || dataQuality.warnings.length > 0;

  return (
    <Space direction="vertical" size="middle" className="wide-stack">
      <div className={`quality-gate compact quality-gate-${gate.status}`}>
        <div className="quality-gate-main">
          <Badge status={gate.badgeStatus} />
          <div>
            <Text strong className="quality-gate-title">{gate.label}</Text>
            <Text className="quality-gate-detail">{gate.detail}</Text>
          </div>
        </div>
        <Tag color={gate.tagColor}>{gate.okCount}/{gate.totalCount}可用</Tag>
      </div>
      {hasIssues ? <QualityIssueList dataQuality={dataQuality} compact /> : <Text className="quality-clean-note">全部检查通过，交易信号未被数据质量阻断。</Text>}
    </Space>
  );
}

function QualityGatePanel({ dataQuality }: { dataQuality?: DataQualityResponse }) {
  if (!dataQuality) {
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无数据质量" />;
  }

  const gate = getQualityGate(dataQuality);
  const hasIssues = gate.problemItems.length > 0 || dataQuality.warnings.length > 0;

  return (
    <Space direction="vertical" size="middle" className="wide-stack">
      <div className={`quality-gate quality-gate-${gate.status}`}>
        <div className="quality-gate-main">
          <Badge status={gate.badgeStatus} />
          <div>
            <Text strong className="quality-gate-title">{gate.label}</Text>
            <Text className="quality-gate-detail">{gate.detail}</Text>
          </div>
        </div>
        <div className="quality-gate-score">
          <Text className="metric-label">内部评分</Text>
          <Text strong>{gate.scoreText}</Text>
        </div>
      </div>
      <div className="quality-gate-meta">
        <MetricLabel label="检查标的" value={`${gate.totalCount} 个`} />
        <MetricLabel label="可用标的" value={`${gate.okCount}/${gate.totalCount}`} />
        <MetricLabel label="需处理" value={`${gate.problemItems.length + dataQuality.warnings.length} 项`} />
      </div>
      {hasIssues ? (
        <QualityIssueList dataQuality={dataQuality} />
      ) : (
        <Alert className="quality-clean-alert" type="success" showIcon message="当前数据质量正常，交易信号未被数据质量阻断。" />
      )}
    </Space>
  );
}

function QualityIssueList({ dataQuality, compact = false }: { dataQuality: DataQualityResponse; compact?: boolean }) {
  const gate = getQualityGate(dataQuality);
  const items = gate.problemItems;

  if (!items.length && !dataQuality.warnings.length) {
    return null;
  }

  return (
    <div className={compact ? 'quality-reason-list compact' : 'quality-reason-list'}>
      {dataQuality.warnings.map((warning) => (
        <div className="quality-reason-item" key={`warning-${warning}`}>
          <div className="quality-reason-head">
            <Text strong><WarningOutlined /> 全局告警</Text>
            <Text className="muted">{warningLabel(warning)}</Text>
          </div>
        </div>
      ))}
      {items.map((item) => (
        <div className="quality-reason-item" key={item.code}>
          <div className="quality-reason-head">
            <Text strong>{item.code} · {item.name}</Text>
            <Text className="muted">{item.source} · {item.age_seconds == null ? '无时间戳' : `${item.age_seconds.toFixed(0)}s`}</Text>
          </div>
          <div className="quality-reason-tags">
            <Tag color={qualityItemTagColor(item)}>{qualityItemLevel(item)}</Tag>
            <Tag>{item.score.toFixed(0)}分</Tag>
            {item.issues.length ? <WarningTags warnings={item.issues} /> : <Text className="muted">评分偏低，交易前复核</Text>}
          </div>
        </div>
      ))}
    </div>
  );
}

function getQualityGate(dataQuality?: DataQualityResponse): QualityGateView {
  if (!dataQuality) {
    return {
      status: 'missing',
      label: '无数据',
      detail: '数据质量报告尚未生成',
      scoreText: '-',
      tagColor: 'default',
      badgeStatus: 'default',
      okCount: 0,
      totalCount: 0,
      problemItems: []
    };
  }

  const items = dataQuality.items ?? [];
  const blockedItems = items.filter((item) => !item.ok || item.score < 70);
  const cautiousItems = items.filter((item) => item.ok && item.score >= 70 && item.score < 90);
  const warningItems = items.filter((item) => item.score >= 90 && item.issues.length > 0);
  const problemItems = [...blockedItems, ...cautiousItems, ...warningItems];
  const okCount = items.filter((item) => item.ok).length;
  const totalCount = items.length;
  const scoreText = `${dataQuality.overall_score.toFixed(0)}分`;

  if (blockedItems.length > 0 || dataQuality.overall_score < 70) {
    return {
      status: 'blocked',
      label: '不可用',
      detail: `存在数据阻断 · ${okCount}/${totalCount} 标的可用 · 暂停依赖相关信号`,
      scoreText,
      tagColor: 'red',
      badgeStatus: 'error',
      okCount,
      totalCount,
      problemItems
    };
  }

  if (cautiousItems.length > 0 || dataQuality.warnings.length > 0 || dataQuality.overall_score < 90) {
    return {
      status: 'caution',
      label: '谨慎',
      detail: `部分数据需要复核 · ${okCount}/${totalCount} 标的可用 · 新开仓先人工确认`,
      scoreText,
      tagColor: 'orange',
      badgeStatus: 'warning',
      okCount,
      totalCount,
      problemItems
    };
  }

  return {
    status: 'trusted',
    label: '可信',
    detail: `全部可信 · ${okCount}/${totalCount} 标的可用 · 不影响交易信号`,
    scoreText,
    tagColor: 'green',
    badgeStatus: 'success',
    okCount,
    totalCount,
    problemItems
  };
}

function qualityGateMeta(dataQuality?: DataQualityResponse): string {
  if (!dataQuality) {
    return '-';
  }
  const gate = getQualityGate(dataQuality);
  return `${gate.label} · ${formatDateTime(dataQuality.generated_at)}`;
}

function qualityItemLevel(item: DataQualityItem): string {
  if (!item.ok || item.score < 70) {
    return '不可用';
  }
  if (item.score < 90 || item.issues.length > 0) {
    return '谨慎';
  }
  return '可信';
}

function qualityItemTagColor(item: DataQualityItem): string {
  if (!item.ok || item.score < 70) {
    return 'red';
  }
  if (item.score < 90 || item.issues.length > 0) {
    return 'orange';
  }
  return 'green';
}

function SectionHeader({ icon, title, meta, extra }: { icon: ReactNode; title: string; meta?: string; extra?: ReactNode }) {
  return (
    <div className="section-header">
      <Space>
        <span className="section-icon">{icon}</span>
        <Text strong>{title}</Text>
        {meta && <Text className="muted">{meta}</Text>}
      </Space>
      {extra}
    </div>
  );
}

function BackendBadge({ health, loading }: { health?: HealthResponse; loading: boolean }) {
  if (loading && !health) {
    return <Badge status="processing" text="检查中" />;
  }
  if (!health) {
    return <Badge status="default" text="未连接" />;
  }
  return <Badge status={health.ok ? 'success' : 'error'} text={health.ok ? '后端在线' : '后端异常'} />;
}

function SessionBadge({ session, loading, hasToken, compact = false }: { session?: WebSessionInfo; loading: boolean; hasToken: boolean; compact?: boolean }) {
  if (!hasToken) {
    return <Badge status="default" text="未登录" />;
  }
  if (loading && !session) {
    return <Badge status="processing" text="验证中" />;
  }
  if (!session) {
    return <Badge status="warning" text="会话待验证" />;
  }
  const expires = session.expires_at ? ` · ${formatDateTime(session.expires_at)}` : '';
  return <Badge status="success" text={compact ? session.username : `${session.username}${expires}`} />;
}

function ScoreCell({ value }: { value: number }) {
  return <Progress percent={clamp(value)} size="small" strokeColor={scoreColor(value)} format={() => value.toFixed(0)} />;
}

function RiskScoreCell({ value }: { value: number }) {
  return <Progress percent={clamp(value)} size="small" strokeColor={riskScoreColor(value)} format={() => value.toFixed(0)} />;
}

function SignalTag({ value }: { value: string }) {
  const colorMap: Record<string, string> = {
    buy: 'green',
    low_buy: 'green',
    watch_low_buy: 'green',
    hold: 'blue',
    wait: 'default',
    reduce: 'orange',
    take_profit: 'orange',
    exit: 'red'
  };
  return <Tag color={colorMap[value] ?? 'default'}>{signalLabel(value)}</Tag>;
}

function EntryBiasTag({ value }: { value: string }) {
  const colorMap: Record<string, string> = {
    watch_low_buy: 'green',
    wait: 'default',
    direction_hot_wait_pullback: 'orange',
    pullback_watch: 'green',
    avoid_premium: 'red',
    avoid: 'red'
  };
  return <Tag color={colorMap[value] ?? 'default'}>{entryBiasLabel(value)}</Tag>;
}


function TradeActionTag({ value }: { value: string }) {
  const colorMap: Record<string, string> = {
    low_buy_allowed: 'green',
    wait_pullback_low_buy: 'blue',
    observe_next_day_retention: 'orange',
    do_not_chase_wait_pullback: 'orange',
    avoid_or_reduce: 'red',
    wait: 'default'
  };
  return <Tag color={colorMap[value] ?? 'default'}>{tradeActionLabel(value)}</Tag>;
}

function MarketStateTag({ value }: { value: string }) {
  const colorMap: Record<string, string> = {
    confirmed_mainline: 'green',
    candidate: 'blue',
    hot_today: 'orange',
    overheated: 'orange',
    weakening: 'red',
    mainline_candidate: 'green',
    strong_direction: 'blue',
    watch_direction: 'orange',
    weak_direction: 'default',
    hot_board: 'blue',
    strong_board: 'blue',
    watch_board: 'orange',
    weak_board: 'default'
  };
  return <Tag color={colorMap[value] ?? 'default'}>{marketStateLabel(value)}</Tag>;
}

function RiskLevelTag({ value }: { value: string }) {
  const colorMap: Record<string, string> = {
    low: 'green',
    normal: 'green',
    medium: 'orange',
    high: 'red',
    critical: 'red'
  };
  return <Tag color={colorMap[value] ?? 'default'}>{riskLevelLabel(value)}</Tag>;
}

function WarningTags({ warnings }: { warnings: string[] }) {
  if (!warnings.length) {
    return <Tag color="green"><CheckCircleOutlined /> 正常</Tag>;
  }
  return (
    <Space size={[0, 4]} wrap>
      {warnings.map((warning) => (
        <Tooltip key={warning} title={warning}>
          <Tag color="orange">{warningLabel(warning)}</Tag>
        </Tooltip>
      ))}
    </Space>
  );
}

function warningLabel(value: string): string {
  const premiumMatch = value.match(/^IOPV premium ([+-]?\d+(?:\.\d+)?)% is above low-buy threshold$/);
  if (premiumMatch) {
    return `IOPV溢价 ${premiumMatch[1]}%，高于低吸阈值`;
  }
  const staleMatch = value.match(/^data stale over (\d+) seconds$/);
  if (staleMatch) {
    return `行情超过 ${staleMatch[1]} 秒未更新`;
  }
  const snapshotStaleMatch = value.match(/^stale snapshot over (\d+)s$/);
  if (snapshotStaleMatch) {
    return `快照超过 ${snapshotStaleMatch[1]} 秒未更新`;
  }
  const map: Record<string, string> = {
    'price is too far above VWAP for low-buy': '价格明显高于VWAP，不适合低吸',
    'price far below VWAP; confirm it is not breakdown': '价格显著低于VWAP，先确认不是破位',
    'price is extended above MA5': '价格明显高于MA5，不追高',
    '3-day gain is too fast; wait for pullback': '3日涨幅过快，等回踩',
    'intraday volatility is high; split orders only': '盘中波动偏高，只适合分批',
    'price below MA20; trend risk high': '价格跌破MA20，趋势风险较高',
    'same-day drawdown is severe; avoid catching a falling market': '当日回撤较大，避免接下跌',
    'invalid price': '价格无效',
    'missing latest snapshot': '缺少最新行情快照',
    'missing ETF IOPV': '缺少ETF IOPV',
    'ETF premium/discount absolute value over 3%': 'ETF溢折价绝对值超过3%',
    'zero amount': '成交额为0，流动性数据不可用',
    'some instruments have weak data quality; avoid using them for fresh entry signals': '部分标的数据质量偏弱，避免直接开新仓',
    'one or more snapshots are stale': '部分行情快照延迟',
    'free fallback quote source is in use; validate before fresh entry signals': '使用备用免费行情源，交易前复核'
  };
  return map[value] ?? value;
}

function PercentValue({ value, neutral = false }: { value: number | null | undefined; neutral?: boolean }) {
  if (value == null || Number.isNaN(value)) {
    return <span>-</span>;
  }
  const className = neutral ? '' : value > 0 ? 'num-up' : value < 0 ? 'num-down' : '';
  return <span className={className}>{formatPct(value)}</span>;
}

function MoneyValue({ value }: { value: number | null | undefined }) {
  if (value == null || Number.isNaN(value)) {
    return <span>-</span>;
  }
  const className = value > 0 ? 'num-up' : value < 0 ? 'num-down' : '';
  return <span className={className}>{formatAmount(value)}</span>;
}

function MetricLabel({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div>
      <Text className="metric-label">{label}</Text>
      <div className="metric-value">{value}</div>
    </div>
  );
}

type CarrierCandidateSource = 'market_flow' | 'discovery' | 'none';

interface CarrierCandidateSet {
  source: CarrierCandidateSource;
  candidates: DiscoveryEtfCandidate[];
  direction?: MarketDirection;
  generatedAt?: string;
}

function getCarrierCandidateSet(marketFlow?: MarketFlowResponse, discovery?: DiscoveryResponse): CarrierCandidateSet {
  const directions = marketFlow?.directions ?? [];
  const primaryDirection = directions.find((direction) => getDirectionCarrierEtfs(direction).length > 0 && !isWeakCarrierDirection(direction))
    ?? directions.find((direction) => getDirectionCarrierEtfs(direction).length > 0);
  if (primaryDirection) {
    return {
      source: 'market_flow',
      candidates: getDirectionCarrierEtfs(primaryDirection),
      direction: primaryDirection,
      generatedAt: marketFlow?.generated_at
    };
  }

  const discoveryCandidates = getDiscoveryCandidates(discovery);
  if (discoveryCandidates.length) {
    return {
      source: 'discovery',
      candidates: discoveryCandidates,
      generatedAt: discovery?.generated_at
    };
  }

  return { source: 'none', candidates: [] };
}

function getDirectionCarrierEtfs(direction: MarketDirection): DiscoveryEtfCandidate[] {
  const rawItems = direction.main_etfs?.length
    ? [...direction.main_etfs, ...(direction.backup_etf ? [direction.backup_etf] : [])]
    : direction.linked_etfs.slice(0, 3);
  return rawItems.slice(0, 3).map((item, index) => ({
    ...item,
    role: index < 2 ? 'main' : 'backup',
    rank: index + 1,
    direction_key: direction.direction_key,
    direction_label: direction.direction_label
  }));
}

function carrierCandidateMeta(carrierSet: CarrierCandidateSet): string {
  if (carrierSet.source === 'market_flow' && carrierSet.direction && carrierSet.generatedAt) {
    return `${carrierSet.direction.direction_label} · ${marketStateLabel(carrierSet.direction.state)} · ${formatDateTime(carrierSet.generatedAt)}`;
  }
  if (carrierSet.source === 'discovery' && carrierSet.generatedAt) {
    return `ETF库兜底 · ${formatDateTime(carrierSet.generatedAt)}`;
  }
  return '-';
}

function carrierScore(candidate: DiscoveryEtfCandidate): number {
  return candidate.mapping_score ?? candidate.score;
}

function getFixedPoolCodes(latest?: LatestResponse): Set<string> {
  return new Set((latest?.plans ?? []).map((plan) => plan.code));
}

function isWeakCarrierDirection(direction: MarketDirection): boolean {
  return direction.state === 'weakening' || direction.state === 'weak_direction';
}

function getDiscoveryCandidates(discovery?: DiscoveryResponse): DiscoveryEtfCandidate[] {
  if (!discovery) {
    return [];
  }
  return [...discovery.main_candidates, discovery.backup_candidate].filter((candidate): candidate is DiscoveryEtfCandidate => Boolean(candidate));
}

function getErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return error.status === 401 ? 'API Token 无效或缺失' : error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return '请求失败';
}

function clamp(value: number): number {
  if (Number.isNaN(value)) {
    return 0;
  }
  return Math.max(0, Math.min(100, Math.round(value)));
}

function scoreColor(value: number): string {
  if (value >= 80) return '#16a34a';
  if (value >= 60) return '#1677ff';
  if (value >= 40) return '#d97706';
  return '#dc2626';
}

function riskScoreColor(value: number): string {
  if (value >= 70) return '#dc2626';
  if (value >= 45) return '#d97706';
  return '#16a34a';
}

function formatAmount(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) {
    return '-';
  }
  const sign = value < 0 ? '-' : '';
  const absolute = Math.abs(value);
  if (absolute >= 100_000_000) {
    return `${sign}${(absolute / 100_000_000).toFixed(2)}亿`;
  }
  if (absolute >= 10_000) {
    return `${sign}${(absolute / 10_000).toFixed(1)}万`;
  }
  return `${sign}${absolute.toFixed(0)}`;
}

function formatNumber(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) {
    return '-';
  }
  return value.toFixed(2);
}

function formatPrice(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) {
    return '-';
  }
  return value.toFixed(3);
}

function formatPct(value: number): string {
  const prefix = value > 0 ? '+' : '';
  return `${prefix}${value.toFixed(2)}%`;
}

function formatDateTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return '-';
  }
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false
  }).format(date);
}

function latestDataTimeMeta(latest: LatestResponse): string {
  if (latest.data_time) {
    return `行情 ${formatDateTime(latest.data_time)}`;
  }
  return `生成 ${formatDateTime(latest.generated_at)}`;
}

function roleLabel(value: string): string {
  const map: Record<string, string> = {
    main: '主要',
    backup: '备选',
    watch: '观察',
    benchmark: '基准'
  };
  return map[value] ?? value;
}

function poolStatusLabel(value: string): string {
  const map: Record<string, string> = {
    keep: '保持固定池',
    partial_rotate: '部分调仓候选',
    rotate: '调仓候选',
    no_recommendation: '暂无建议'
  };
  return map[value] ?? value;
}

function poolActionLabel(value: string): string {
  const map: Record<string, string> = {
    keep: '保留',
    promote: '建议纳入',
    replace_candidate: '建议替换',
    watch: '观察',
    avoid: '回避'
  };
  return map[value] ?? value;
}

function poolActionColor(value: string): string {
  const map: Record<string, string> = {
    keep: 'green',
    promote: 'blue',
    replace_candidate: 'orange',
    watch: 'default',
    avoid: 'red'
  };
  return map[value] ?? 'default';
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
    WAIT: '等待'
  };
  return map[value] ?? value;
}

function actionColor(side: string): string {
  const map: Record<string, string> = {
    BUY: 'green',
    SELL: 'red',
    HOLD: 'blue',
    WAIT: 'orange',
    AVOID: 'red'
  };
  return map[side] ?? 'default';
}

function urgencyLabel(value: string): string {
  const map: Record<string, string> = {
    high: '高优先级',
    medium: '中优先级',
    normal: '普通',
    low: '低优先级'
  };
  return map[value] ?? value;
}

function actionPortfolioStatusLabel(value: string): string {
  const map: Record<string, string> = {
    risk_exit: '风险离场',
    sell_or_reduce: '卖出/减仓',
    buy_available: '可买入',
    wait_low_buy: '等待低吸',
    wait: '等待'
  };
  return map[value] ?? value;
}

function signalLabel(value: string): string {
  const map: Record<string, string> = {
    buy: '买入',
    low_buy: '低吸',
    watch_low_buy: '等低吸',
    hold: '持有',
    wait: '等待',
    reduce: '减仓',
    take_profit: '止盈',
    exit: '离场'
  };
  return map[value] ?? value;
}

function entryBiasLabel(value: string): string {
  const map: Record<string, string> = {
    watch_low_buy: '等低吸',
    wait: '等待',
    direction_hot_wait_pullback: '等回落',
    pullback_watch: '回踩观察',
    avoid_premium: '溢价回避',
    avoid: '回避'
  };
  return map[value] ?? value;
}


function tradeActionLabel(value: string): string {
  const map: Record<string, string> = {
    low_buy_allowed: '可低吸',
    wait_pullback_low_buy: '等回踩',
    observe_next_day_retention: '看承接',
    do_not_chase_wait_pullback: '不追高',
    avoid_or_reduce: '回避/降仓',
    wait: '等待'
  };
  return map[value] ?? value;
}

function marketStateLabel(value: string): string {
  const map: Record<string, string> = {
    confirmed_mainline: '确认主线',
    candidate: '候选主线',
    hot_today: '今日强',
    overheated: '过热',
    weakening: '弱化',
    mainline_candidate: '候选主线',
    strong_direction: '强方向',
    watch_direction: '观察',
    weak_direction: '弱方向',
    hot_board: '热板块',
    strong_board: '强板块',
    watch_board: '观察板块',
    weak_board: '弱板块'
  };
  return map[value] ?? value;
}

function riskLevelLabel(value: string): string {
  const map: Record<string, string> = {
    low: '低',
    normal: '正常',
    medium: '中',
    high: '高',
    critical: '极高'
  };
  return map[value] ?? value;
}

export default App;
