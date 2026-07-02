import { Badge } from 'antd';
import type { HealthResponse, WebSessionInfo } from '../types';

export function StatusBadge({ health, loading }: { health?: HealthResponse; loading: boolean }) {
  if (loading && !health) return <Badge status="processing" text="检查中" />;
  if (!health) return <Badge status="default" text="未连接" />;
  return <Badge status={health.ok ? 'success' : 'error'} text={health.ok ? '后端在线' : '后端异常'} />;
}

export function SessionBadge({ session, loading, hasToken }: { session?: WebSessionInfo; loading: boolean; hasToken: boolean }) {
  if (!hasToken) return <Badge status="default" text="未登录" />;
  if (loading && !session) return <Badge status="processing" text="验证中" />;
  if (!session) return <Badge status="warning" text="待验证" />;
  return <Badge status="success" text={session.username} />;
}
