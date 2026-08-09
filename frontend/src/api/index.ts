import type {
  CheckResult,
  Paginated,
  ResultFilterParams,
  StatsSummary,
  Target,
  TargetInput,
  TrendData,
  WebhookConfig,
} from '@/types'

import { request } from './client'

function buildQuery(params: ResultFilterParams): string {
  const q = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === '') continue
    if (k === 'status' && v === 'all') continue
    q.set(k, String(v))
  }
  const s = q.toString()
  return s ? `?${s}` : ''
}

export const api = {
  login: (access_code: string) =>
    request<{ ok: boolean }>('/auth/login', { method: 'POST', body: JSON.stringify({ access_code }) }),
  logout: () =>
    request<{ ok: boolean }>('/auth/logout', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    }),
  me: () => request<{ authenticated: boolean }>('/auth/me'),
  meta: () => request<{ tz: string }>('/meta'),

  listTargets: () => request<Target[]>('/targets'),
  createTarget: (input: TargetInput) =>
    request<Target>('/targets', { method: 'POST', body: JSON.stringify(input) }),
  updateTarget: (id: string, input: Partial<TargetInput>) =>
    request<Target>(`/targets/${id}`, { method: 'PUT', body: JSON.stringify(input) }),
  deleteTarget: (id: string) => request<void>(`/targets/${id}`, { method: 'DELETE' }),

  queryResults: (params: ResultFilterParams) =>
    request<Paginated<CheckResult>>(`/results${buildQuery(params)}`),
  runChecks: (targetId?: string) =>
    request<CheckResult[]>('/checks/run', {
      method: 'POST',
      body: JSON.stringify(targetId ? { target_id: targetId } : {}),
    }),
  stats: () => request<StatsSummary>('/stats/summary'),
  statsTrend: (hours = 24) => request<TrendData>(`/stats/trend?hours=${hours}`),
  getWebhook: () => request<WebhookConfig>('/settings/webhook'),
  updateWebhook: (cfg: WebhookConfig) =>
    request<WebhookConfig>('/settings/webhook', { method: 'PUT', body: JSON.stringify(cfg) }),
  testWebhook: (url: string) =>
    request<{ ok: boolean; info: string }>('/settings/webhook/test', {
      method: 'POST',
      body: JSON.stringify(url ? { url } : {}),
    }),
}
