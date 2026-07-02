import { useEffect, useState } from 'react';
import { App as AntdApp, Button, Empty, Input, Layout, Modal, Space, Spin, Switch, Tooltip, Typography } from 'antd';
import { LineChartOutlined, LockOutlined, LogoutOutlined, ReloadOutlined, UserOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query';
import { ApiError, SESSION_STORAGE_KEY, api } from './api';
import { QuantWorkbench, type PositionDraft } from './features/quant/QuantWorkbench';
import { SessionBadge, StatusBadge } from './shared/AppBadges';
import { getErrorMessage } from './shared/errors';
import { useProtectedQuery } from './shared/useProtectedQuery';
import type { AiSummaryKind, PositionInput } from './types';

const { Header, Content } = Layout;
const { Text, Title } = Typography;

function invalidateTradingQueries(queryClient: QueryClient, token: string) {
  queryClient.invalidateQueries({ queryKey: ['quant-framework', token] });
  queryClient.invalidateQueries({ queryKey: ['quant-maturity', token] });
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
  const quantMaturityQuery = useProtectedQuery(['quant-maturity', sessionToken], sessionToken, ({ signal }) => api.getQuantMaturity(sessionToken, signal), autoRefresh ? 60_000 : false);
  const positionsQuery = useProtectedQuery(['positions', sessionToken], sessionToken, ({ signal }) => api.getPositions(sessionToken, signal), autoRefresh ? 30_000 : false);
  const integrationsQuery = useProtectedQuery(['integrations', sessionToken], sessionToken, ({ signal }) => api.getIntegrations(sessionToken, signal), autoRefresh ? 60_000 : false);
  const aiStatusQuery = useProtectedQuery(['ai-status', sessionToken], sessionToken, ({ signal }) => api.getAiStatus(sessionToken, signal), autoRefresh ? 60_000 : false);
  const aiSummariesQuery = useProtectedQuery(['ai-summaries', sessionToken], sessionToken, ({ signal }) => api.getAiSummaries(sessionToken, signal), autoRefresh ? 60_000 : false);

  const protectedErrors = [sessionQuery.error, frameworkQuery.error, quantValidationQuery.error, quantMaturityQuery.error, positionsQuery.error, integrationsQuery.error, aiStatusQuery.error, aiSummariesQuery.error].filter(Boolean);
  const unauthorized = protectedErrors.some((error) => error instanceof ApiError && error.status === 401);
  const refreshing = [healthQuery, sessionQuery, frameworkQuery, quantValidationQuery, quantMaturityQuery, positionsQuery, integrationsQuery, aiStatusQuery, aiSummariesQuery].some((query) => query.isFetching);
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
      queryClient.invalidateQueries({ queryKey: ['quant-maturity', sessionToken] });
      queryClient.invalidateQueries({ queryKey: ['quant-validation', sessionToken] });
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
            <Title level={4} className="brand-title">Quant Radar</Title>
            <Text className="brand-subtitle">ETF 量化执行工作台</Text>
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
          <QuantWorkbench
            health={healthQuery.data}
            session={sessionQuery.data}
            framework={frameworkQuery.data}
            quantValidation={quantValidationQuery.data}
            quantMaturity={quantMaturityQuery.data}
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
export default App;
