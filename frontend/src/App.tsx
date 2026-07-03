import { useEffect, useState } from 'react';
import { App as AntdApp, Button, Empty, Input, Layout, Modal, Space, Spin } from 'antd';
import { LockOutlined, UserOutlined } from '@ant-design/icons';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { ApiError, SESSION_STORAGE_KEY, api } from './api';
import { QuantWorkbench } from './features/quant/QuantWorkbench';
import { getErrorMessage } from './shared/errors';
import { useProtectedQuery } from './shared/useProtectedQuery';
import type { PositionExitInput } from './types';

const { Content } = Layout;

function App() {
  const queryClient = useQueryClient();
  const { message } = AntdApp.useApp();
  const [sessionToken, setSessionToken] = useState(() => window.localStorage.getItem(SESSION_STORAGE_KEY) ?? '');
  const [loginOpen, setLoginOpen] = useState(!sessionToken);
  const [loginUsername, setLoginUsername] = useState('admin');
  const [loginPassword, setLoginPassword] = useState('');

  const decisionQuery = useProtectedQuery(
    ['quant-decision', sessionToken],
    sessionToken,
    ({ signal }) => api.getQuantDecision(sessionToken, signal),
    30_000
  );

  const tradesQuery = useProtectedQuery(
    ['trade-journal', sessionToken],
    sessionToken,
    ({ signal }) => api.getTrades(sessionToken, signal),
    60_000
  );

  const unauthorized = decisionQuery.error instanceof ApiError && decisionQuery.error.status === 401;
  const firstLoad = Boolean(sessionToken) && decisionQuery.isLoading;

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
    },
    onError: (error) => message.error(getErrorMessage(error))
  });

  const forceRefreshMutation = useMutation({
    mutationFn: () => api.getMarketFlow(sessionToken, true),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['quant-decision', sessionToken] }),
    onError: (error) => message.error(getErrorMessage(error))
  });

  const savePositionMutation = useMutation({
    mutationFn: ({ code, input }: { code: string; input: { entry_price: number; shares: number | null; entry_date: string | null; note: string } }) =>
      api.upsertPosition(sessionToken, code, input),
    onSuccess: () => {
      message.success('持仓已保存');
      queryClient.invalidateQueries({ queryKey: ['quant-decision', sessionToken] });
      queryClient.invalidateQueries({ queryKey: ['trade-journal', sessionToken] });
    },
    onError: (error) => message.error(getErrorMessage(error))
  });

  const closePositionMutation = useMutation({
    mutationFn: ({ code, input }: { code: string; input: PositionExitInput }) => api.closePosition(sessionToken, code, input),
    onSuccess: (record) => {
      message.success(`已记录卖出：${record.code} ${record.realized_profit_pct.toFixed(2)}%`);
      queryClient.invalidateQueries({ queryKey: ['quant-decision', sessionToken] });
      queryClient.invalidateQueries({ queryKey: ['trade-journal', sessionToken] });
    },
    onError: (error) => message.error(getErrorMessage(error))
  });

  const deletePositionMutation = useMutation({
    mutationFn: (code: string) => api.deletePosition(sessionToken, code),
    onSuccess: () => {
      message.success('持仓已删除');
      queryClient.invalidateQueries({ queryKey: ['quant-decision', sessionToken] });
      queryClient.invalidateQueries({ queryKey: ['trade-journal', sessionToken] });
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
  };

  return (
    <Layout className="app-shell table-only-shell">
      <Content className="table-only-content">
        {!sessionToken ? (
          <section className="login-placeholder">
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="请先登录" />
            <Button type="primary" onClick={() => setLoginOpen(true)}>登录</Button>
          </section>
        ) : firstLoad ? (
          <section className="login-placeholder"><Spin tip="加载主线方向" /></section>
        ) : (
          <QuantWorkbench
            decision={decisionQuery.data}
            tradeJournal={tradesQuery.data}
            onRefresh={() => forceRefreshMutation.mutate()}
            refreshing={forceRefreshMutation.isPending || decisionQuery.isFetching}
            onLogout={logout}
            onSavePosition={(code, input) => savePositionMutation.mutate({ code, input })}
            onClosePosition={(code, input) => closePositionMutation.mutate({ code, input })}
            onDeletePosition={(code) => deletePositionMutation.mutate(code)}
            savingPosition={savePositionMutation.isPending}
            closingPosition={closePositionMutation.isPending}
            deletingPosition={deletePositionMutation.isPending}
            errorMessage={decisionQuery.error ? getErrorMessage(decisionQuery.error) : tradesQuery.error ? getErrorMessage(tradesQuery.error) : null}
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
