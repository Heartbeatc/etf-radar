import type {
  AiStatus,
  AiSummaryItem,
  AiSummaryKind,
  AiSummaryReport,
  DataQualityResponse,
  DiscoveryResponse,
  HealthResponse,
  IntegrationStatus,
  LatestResponse,
  MarketFlowResponse,
  PoolRecommendationResponse,
  RiskResponse,
  WebLoginResponse,
  WebSessionInfo
} from './types';

export const SESSION_STORAGE_KEY = 'etf_radar_web_session';

export class ApiError extends Error {
  status: number;
  payload: unknown;

  constructor(status: number, message: string, payload: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.payload = payload;
  }
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE';
  token?: string | null;
  body?: unknown;
  signal?: AbortSignal;
}

async function requestJson<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers = new Headers({ Accept: 'application/json' });
  if (options.token) {
    headers.set('Authorization', `Bearer ${options.token}`);
  }
  const init: RequestInit = {
    method: options.method ?? 'GET',
    headers,
    signal: options.signal
  };
  if (options.body !== undefined) {
    headers.set('Content-Type', 'application/json');
    init.body = JSON.stringify(options.body);
  }

  const response = await fetch(path, init);
  const text = await response.text();
  let payload: unknown = null;

  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = text;
    }
  }

  if (!response.ok) {
    const message =
      typeof payload === 'object' && payload && 'detail' in payload
        ? String((payload as { detail: unknown }).detail)
        : `HTTP ${response.status}`;
    throw new ApiError(response.status, message, payload);
  }

  return payload as T;
}

export const api = {
  login: (username: string, password: string) =>
    requestJson<WebLoginResponse>('/api/v1/auth/login', {
      method: 'POST',
      body: { username, password }
    }),
  getSession: (token: string, signal?: AbortSignal) =>
    requestJson<WebSessionInfo>('/api/v1/auth/session', { token, signal }),
  logout: (token: string) => requestJson<{ ok: boolean }>('/api/v1/auth/logout', { method: 'POST', token }),
  getHealth: (signal?: AbortSignal) => requestJson<HealthResponse>('/health', { signal }),
  getLatest: (token: string, signal?: AbortSignal) => requestJson<LatestResponse>('/api/v1/latest', { token, signal }),
  getDiscovery: (token: string, force = false, signal?: AbortSignal) =>
    requestJson<DiscoveryResponse>(`/api/v1/discovery${force ? '?force=true' : ''}`, { token, signal }),
  getMarketFlow: (token: string, force = false, signal?: AbortSignal) =>
    requestJson<MarketFlowResponse>(`/api/v1/market-flow${force ? '?force=true' : ''}`, { token, signal }),
  getPoolRecommendation: (token: string, signal?: AbortSignal) =>
    requestJson<PoolRecommendationResponse>('/api/v1/pool-recommendation', { token, signal }),
  getRisk: (token: string, signal?: AbortSignal) => requestJson<RiskResponse>('/api/v1/risk', { token, signal }),
  getDataQuality: (token: string, signal?: AbortSignal) =>
    requestJson<DataQualityResponse>('/api/v1/data-quality', { token, signal }),
  getIntegrations: (token: string, signal?: AbortSignal) =>
    requestJson<IntegrationStatus[]>('/api/v1/integrations', { token, signal }),
  getAiStatus: (token: string, signal?: AbortSignal) =>
    requestJson<AiStatus>('/api/v1/ai/status', { token, signal }),
  setAiEnabled: (token: string, enabled: boolean) =>
    requestJson<AiStatus>('/api/v1/ai/status', { method: 'PUT', token, body: { enabled } }),
  getAiSummaries: (token: string, signal?: AbortSignal) =>
    requestJson<AiSummaryReport>('/api/v1/ai/summaries', { token, signal }),
  generateAiSummary: (token: string, kind: AiSummaryKind | string, force = true) =>
    requestJson<AiSummaryItem>(`/api/v1/ai/summaries/${kind}${force ? '?force=true' : ''}`, { method: 'POST', token })
};
