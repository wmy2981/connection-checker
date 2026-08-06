import type {
  CheckResult,
  Paginated,
  ResultFilterParams,
  StatsSummary,
  Target,
  TargetInput,
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
  logout: () => request<{ ok: boolean }>('/auth/logout', { method: 'POST' }),
  me: () => request<{ authenticated: boolean }>('/auth/me'),

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
}
