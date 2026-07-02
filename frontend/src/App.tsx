import { type ReactNode, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  App as AntdApp,
  Badge,
  Button,
  Card,
  Col,
  Empty,
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
  WarningOutlined
} from '@ant-design/icons';
import ReactECharts from 'echarts-for-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ApiError, SESSION_STORAGE_KEY, api } from './api';
import type {
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
  RiskItem,
  RiskResponse,
  TradingPlan,
  WebSessionInfo
} from './types';

const { Header, Content } = Layout;
const { Text, Title } = Typography;

function App() {
  const queryClient = useQueryClient();
  const { message } = AntdApp.useApp();
  const [sessionToken, setSessionToken] = useState(() => window.localStorage.getItem(SESSION_STORAGE_KEY) ?? '');
  const [loginOpen, setLoginOpen] = useState(!sessionToken);
  const [loginUsername, setLoginUsername] = useState('admin');
  const [loginPassword, setLoginPassword] = useState('');
  const [autoRefresh, setAutoRefresh] = useState(true);

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

  const protectedErrors = [sessionQuery.error, latestQuery.error, discoveryQuery.error, marketFlowQuery.error, riskQuery.error, dataQualityQuery.error, integrationsQuery.error].filter(Boolean);
  const unauthorized = protectedErrors.some((error) => error instanceof ApiError && error.status === 401);
  const refreshing = [healthQuery, sessionQuery, latestQuery, discoveryQuery, marketFlowQuery, riskQuery, dataQualityQuery, integrationsQuery].some((query) => query.isFetching);
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
                risk={riskQuery.data}
                dataQuality={dataQualityQuery.data}
                integrations={integrationsQuery.data ?? []}
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

interface DashboardProps {
  latest?: LatestResponse;
  discovery?: DiscoveryResponse;
  marketFlow?: MarketFlowResponse;
  risk?: RiskResponse;
  dataQuality?: DataQualityResponse;
  integrations: IntegrationStatus[];
  onForceDiscovery: () => void;
  forcingDiscovery: boolean;
  errorMessage: string | null;
}

function Dashboard(props: DashboardProps) {
  const { latest, discovery, marketFlow, risk, dataQuality, integrations, onForceDiscovery, forcingDiscovery, errorMessage } = props;

  const tabItems = [
    {
      key: 'overview',
      label: <span><DashboardOutlined /> 总览</span>,
      children: <OverviewTab latest={latest} discovery={discovery} marketFlow={marketFlow} risk={risk} dataQuality={dataQuality} onForceDiscovery={onForceDiscovery} forcingDiscovery={forcingDiscovery} />
    },
    {
      key: 'market-flow',
      label: <span><ThunderboltOutlined /> 市场流向</span>,
      children: <MarketFlowTab marketFlow={marketFlow} />
    },
    {
      key: 'discovery',
      label: <span><LineChartOutlined /> ETF载体</span>,
      children: <DiscoveryTab discovery={discovery} onForceDiscovery={onForceDiscovery} forcingDiscovery={forcingDiscovery} />
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
      key: 'quality',
      label: <span><DatabaseOutlined /> 数据质量</span>,
      children: <QualityTab dataQuality={dataQuality} integrations={integrations} />
    }
  ];

  return (
    <>
      {errorMessage && <Alert className="stack-alert" type="error" showIcon message={errorMessage} />}
      <MetricStrip latest={latest} discovery={discovery} marketFlow={marketFlow} risk={risk} dataQuality={dataQuality} integrations={integrations} />
      <Tabs className="work-tabs" items={tabItems} destroyInactiveTabPane={false} />
    </>
  );
}

interface OverviewTabProps {
  latest?: LatestResponse;
  discovery?: DiscoveryResponse;
  marketFlow?: MarketFlowResponse;
  risk?: RiskResponse;
  dataQuality?: DataQualityResponse;
  onForceDiscovery: () => void;
  forcingDiscovery: boolean;
}

function OverviewTab({ latest, discovery, marketFlow, risk, dataQuality, onForceDiscovery, forcingDiscovery }: OverviewTabProps) {
  return (
    <Space direction="vertical" size="large" className="wide-stack">
      <MarketFlowSummary marketFlow={marketFlow} compact />
      <CandidateCards discovery={discovery} onForceDiscovery={onForceDiscovery} forcingDiscovery={forcingDiscovery} compact />
      <Row gutter={[16, 16]}>
        <Col xs={24} xl={14}>
          <section className="panel">
            <SectionHeader icon={<BarChartOutlined />} title="固定池信号" meta={latest ? formatDateTime(latest.generated_at) : '-'} />
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
            <SectionHeader icon={<DatabaseOutlined />} title="数据质量" meta={dataQuality ? `${dataQuality.overall_score.toFixed(0)}分` : '-'} />
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
  const items = direction.main_etfs?.length ? [...direction.main_etfs, ...(direction.backup_etf ? [direction.backup_etf] : [])] : direction.linked_etfs;
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

function DiscoveryTab({ discovery, onForceDiscovery, forcingDiscovery }: { discovery?: DiscoveryResponse; onForceDiscovery: () => void; forcingDiscovery: boolean }) {
  const candidates = useMemo(() => getDiscoveryCandidates(discovery), [discovery]);

  return (
    <Space direction="vertical" size="large" className="wide-stack">
      <CandidateCards discovery={discovery} onForceDiscovery={onForceDiscovery} forcingDiscovery={forcingDiscovery} />
      <section className="panel">
        <SectionHeader icon={<ThunderboltOutlined />} title="方向排行" meta={discovery ? formatDateTime(discovery.generated_at) : '-'} />
        <DirectionTable data={discovery?.directions ?? []} />
      </section>
      <section className="panel">
        <SectionHeader icon={<BarChartOutlined />} title="候选ETF" meta={`${candidates.length} 个`} />
        <CandidateTable data={candidates} />
      </section>
    </Space>
  );
}

function SignalsTab({ latest }: { latest?: LatestResponse }) {
  return (
    <section className="panel">
      <SectionHeader icon={<BarChartOutlined />} title="交易信号" meta={latest ? formatDateTime(latest.generated_at) : '-'} />
      <SignalTable data={latest?.plans ?? []} />
    </section>
  );
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

function QualityTab({ dataQuality, integrations }: { dataQuality?: DataQualityResponse; integrations: IntegrationStatus[] }) {
  return (
    <Row gutter={[16, 16]}>
      <Col xs={24} xl={16}>
        <section className="panel">
          <SectionHeader icon={<DatabaseOutlined />} title="数据源" meta={dataQuality ? formatDateTime(dataQuality.generated_at) : '-'} />
          <QualityTable data={dataQuality?.items ?? []} />
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
  const firstMain = discovery?.main_candidates?.[0];
  const secondMain = discovery?.main_candidates?.[1];
  const integrationOk = integrations.filter((item) => item.ok).length;

  return (
    <Row gutter={[12, 12]} className="metric-row">
      <Col xs={12} lg={6}>
        <Card className="metric-card">
          <Statistic title="当前主线" value={topDirection?.direction_label ?? '-'} prefix={<ThunderboltOutlined />} valueStyle={{ fontSize: 20 }} />
          {topDirection && <Text className="metric-foot">强度 {topDirection.score} · 成交 {formatAmount(topDirection.total_amount)}</Text>}
        </Card>
      </Col>
      <Col xs={12} lg={6}>
        <Card className="metric-card">
          <Statistic title="候选一" value={firstMain?.code ?? latest?.top_low_buy ?? '-'} prefix={<LineChartOutlined />} valueStyle={{ fontSize: 20 }} />
          {firstMain && <Text className="metric-foot">{firstMain.name}</Text>}
        </Card>
      </Col>
      <Col xs={12} lg={6}>
        <Card className="metric-card">
          <Statistic title="候选二" value={secondMain?.code ?? latest?.top_hold ?? '-'} prefix={<BarChartOutlined />} valueStyle={{ fontSize: 20 }} />
          {secondMain && <Text className="metric-foot">{secondMain.name}</Text>}
        </Card>
      </Col>
      <Col xs={12} lg={6}>
        <Card className="metric-card">
          <Statistic title="风险/质量" value={`${risk?.risk_budget_state ?? '-'} / ${dataQuality?.overall_score?.toFixed(0) ?? '-'}`} prefix={<SafetyCertificateOutlined />} valueStyle={{ fontSize: 20 }} />
          <Text className="metric-foot">基础设施 {integrationOk}/{integrations.length || 0}</Text>
        </Card>
      </Col>
    </Row>
  );
}

function CandidateCards({ discovery, onForceDiscovery, forcingDiscovery, compact = false }: { discovery?: DiscoveryResponse; onForceDiscovery: () => void; forcingDiscovery: boolean; compact?: boolean }) {
  const candidates = getDiscoveryCandidates(discovery);

  return (
    <section className="panel">
      <SectionHeader
        icon={<ThunderboltOutlined />}
        title="主线候选"
        meta={discovery ? `${discovery.source} · ${formatDateTime(discovery.generated_at)}` : '-'}
        extra={<Button icon={<ReloadOutlined />} onClick={onForceDiscovery} loading={forcingDiscovery}>强制刷新</Button>}
      />
      {candidates.length ? (
        <div className={compact ? 'candidate-grid compact' : 'candidate-grid'}>
          {candidates.map((candidate) => (
            <article key={`${candidate.role}-${candidate.code}`} className="candidate-card">
              <Space direction="vertical" size="small" className="card-stack">
                <Space wrap>
                  <Tag color={candidate.role === 'backup' ? 'gold' : 'blue'}>{roleLabel(candidate.role)}</Tag>
                  <EntryBiasTag value={candidate.entry_bias} />
                  {candidate.risk_flags.map((flag) => <Tag color="red" key={flag}>{flag}</Tag>)}
                </Space>
                <div>
                  <div className="candidate-name">{candidate.name}</div>
                  <Text className="muted">{candidate.code} · {candidate.direction_label}</Text>
                </div>
                <Progress percent={clamp(candidate.score)} size="small" strokeColor={scoreColor(candidate.score)} />
                <div className="candidate-metrics">
                  <MetricLabel label="涨跌" value={<PercentValue value={candidate.change_pct} />} />
                  <MetricLabel label="成交" value={formatAmount(candidate.amount)} />
                  <MetricLabel label="净流" value={<MoneyValue value={candidate.main_net_inflow} />} />
                  <MetricLabel label="溢价" value={<PercentValue value={candidate.premium_pct} neutral />} />
                </div>
              </Space>
            </article>
          ))}
        </div>
      ) : (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无候选" />
      )}
    </section>
  );
}

function DirectionChart({ directions }: { directions: DiscoveryDirection[] }) {
  const option = useMemo(() => {
    const top = directions.slice(0, 8);
    return {
      color: ['#1677ff'],
      tooltip: { trigger: 'axis' },
      grid: { left: 36, right: 16, top: 24, bottom: 72 },
      xAxis: { type: 'category', data: top.map((item) => item.direction_label), axisLabel: { interval: 0, rotate: 28 } },
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
  }, [directions]);

  if (!directions.length) {
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无方向" />;
  }

  return <ReactECharts option={option} style={{ height: 310 }} notMerge lazyUpdate />;
}

function DirectionTable({ data }: { data: DiscoveryDirection[] }) {
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
  const columns: ColumnsType<IntegrationStatus> = [
    { title: '组件', dataIndex: 'name', key: 'name', width: 120, render: (value: string) => <Text strong>{value}</Text> },
    { title: '状态', dataIndex: 'ok', key: 'ok', width: 90, render: (ok: boolean) => <Badge status={ok ? 'success' : 'error'} text={ok ? '正常' : '异常'} /> },
    { title: '启用', dataIndex: 'enabled', key: 'enabled', width: 80, render: (enabled: boolean) => enabled ? '是' : '否' },
    { title: '详情', dataIndex: 'detail', key: 'detail', ellipsis: true }
  ];
  return <Table rowKey="name" columns={columns} dataSource={data} size="small" pagination={false} />;
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

function QualitySummary({ dataQuality }: { dataQuality?: DataQualityResponse }) {
  if (!dataQuality) {
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无数据" />;
  }

  return (
    <Space direction="vertical" size="middle" className="wide-stack">
      <Progress percent={clamp(dataQuality.overall_score)} strokeColor={scoreColor(dataQuality.overall_score)} />
      <div className="quality-grid">
        {dataQuality.items.map((item) => (
          <div className="quality-item" key={item.code}>
            <Badge status={item.ok ? 'success' : 'error'} />
            <Text strong>{item.code}</Text>
            <Text className="muted">{item.source}</Text>
            <Text>{item.score}</Text>
          </div>
        ))}
      </div>
    </Space>
  );
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

function SessionBadge({ session, loading, hasToken }: { session?: WebSessionInfo; loading: boolean; hasToken: boolean }) {
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
  return <Badge status="success" text={`${session.username}${expires}`} />;
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
      {warnings.map((warning) => <Tag color="orange" key={warning}>{warning}</Tag>)}
    </Space>
  );
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

function roleLabel(value: string): string {
  const map: Record<string, string> = {
    main: '主要',
    backup: '备选',
    watch: '观察',
    benchmark: '基准'
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
