import type {
  ApiTokenInfo,
  AppSettings,
  BackupInfo,
  CheckResult,
  ImportStats,
  LogEntry,
  LogQueryParams,
  Paginated,
  ResultFilterParams,
  S3Config,
  S3ConfigInput,
  StatsSummary,
  Target,
  TargetInput,
  TrendData,
  WebhookConfig,
} from '@/types'

import { ApiError, request } from './client'

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

// 导出下载超时（毫秒）：大结果集 blob 下载比普通请求宽松
const EXPORT_TIMEOUT_MS = 60_000

async function downloadExport(
  path: string,
  params: ResultFilterParams,
  fallbackName = 'export.txt',
): Promise<void> {
  const query = buildQuery(params)
  const controller = new AbortController()
  // 超时覆盖整个导出：响应体（blob）阶段同样受保护，停滞的流会在 60s 后中止
  const timer = setTimeout(() => controller.abort(), EXPORT_TIMEOUT_MS)
  try {
    const res = await fetch(`${path}${query}`, { signal: controller.signal })
    if (res.status === 401) {
      window.location.href = '/login'
      return
    }
    if (!res.ok) throw new ApiError(res.status, res.statusText)
    const blob = await res.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    const cd = res.headers.get('Content-Disposition')
    const m = cd?.match(/filename="([^"]+)"/)
    a.download = m?.[1] ?? fallbackName
    a.href = url
    a.click()
    URL.revokeObjectURL(url)
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') {
      throw new ApiError(408, '导出超时，请缩小筛选范围后重试')
    }
    throw e
  } finally {
    clearTimeout(timer)
  }
}

// 导入上传超时（毫秒）：zip 数据包可能较大，比导出更宽松
const IMPORT_TIMEOUT_MS = 120_000

// multipart 上传导入 zip：不走 request()（其强制 JSON Content-Type），
// 须带 X-Requested-With 头（后端 CSRF JSON 检查的唯一例外条件）
async function uploadImport(
  file: File,
  includeRecords: boolean,
  includeTargets: boolean,
  includeSettings: boolean,
): Promise<ImportStats> {
  const form = new FormData()
  form.append('file', file)
  form.append('include_records', String(includeRecords))
  form.append('include_targets', String(includeTargets))
  form.append('include_settings', String(includeSettings))
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), IMPORT_TIMEOUT_MS)
  try {
    const res = await fetch('/api/v1/data/import', {
      method: 'POST',
      body: form,
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
      signal: controller.signal,
    })
    if (res.status === 401) {
      window.location.href = '/login'
      throw new ApiError(401, '未授权')
    }
    const data = (await res.json().catch(() => null)) as ImportStats | null
    if (!res.ok) {
      throw new ApiError(res.status, (data as { detail?: string } | null)?.detail ?? res.statusText)
    }
    return data as ImportStats
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') {
      throw new ApiError(408, '导入超时，请稍后重试')
    }
    throw e
  } finally {
    clearTimeout(timer)
  }
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
  meta: () => request<{ tz: string; version: string }>('/meta'),

  listTargets: () => request<Target[]>('/targets'),
  createTarget: (input: TargetInput) =>
    request<Target>('/targets', { method: 'POST', body: JSON.stringify(input) }),
  updateTarget: (id: string, input: Partial<TargetInput>) =>
    request<Target>(`/targets/${id}`, { method: 'PUT', body: JSON.stringify(input) }),
  deleteTarget: (id: string) => request<void>(`/targets/${id}`, { method: 'DELETE' }),

  queryResults: (params: ResultFilterParams) =>
    request<Paginated<CheckResult>>(`/results${buildQuery(params)}`),
  exportResults: (format: 'csv' | 'json', params: ResultFilterParams) =>
    downloadExport(`/api/v1/results/export.${format}`, params, `results.${format}`),
  runChecks: (targetId?: string) =>
    request<CheckResult[]>('/checks/run', {
      method: 'POST',
      body: JSON.stringify(targetId ? { target_id: targetId } : {}),
    }),
  stats: () => request<StatsSummary>('/stats/summary'),
  statsTrend: (hours = 24, targetId?: string, unit: 'hour' | 'day' = 'hour') =>
    request<TrendData>(
      `/stats/trend?hours=${hours}&unit=${unit}${targetId ? `&target_id=${encodeURIComponent(targetId)}` : ''}`,
    ),
  getAppSettings: () => request<AppSettings>('/settings/app'),
  updateAppSettings: (cfg: AppSettings) =>
    request<AppSettings>('/settings/app', { method: 'PUT', body: JSON.stringify(cfg) }),
  getWebhook: () => request<WebhookConfig>('/settings/webhook'),
  updateWebhook: (cfg: WebhookConfig) =>
    request<WebhookConfig>('/settings/webhook', { method: 'PUT', body: JSON.stringify(cfg) }),
  testWebhook: (url: string) =>
    request<{ ok: boolean; info: string }>('/settings/webhook/test', {
      method: 'POST',
      body: JSON.stringify(url ? { url } : {}),
    }),
  getS3Config: () => request<S3Config>('/settings/s3'),
  updateS3Config: (cfg: S3ConfigInput) =>
    request<S3Config>('/settings/s3', { method: 'PUT', body: JSON.stringify(cfg) }),
  testS3: (cfg: S3ConfigInput) =>
    request<{ ok: boolean; info: string }>('/settings/s3/test', {
      method: 'POST',
      body: JSON.stringify(cfg),
    }),
  getApiToken: () => request<ApiTokenInfo>('/settings/api-token'),
  generateApiToken: () =>
    request<{ token: string }>('/settings/api-token/generate', {
      method: 'POST',
      body: JSON.stringify({}),
    }),
  deleteApiToken: () => request<{ ok: boolean }>('/settings/api-token', { method: 'DELETE' }),
  queryLogs: (params: LogQueryParams) =>
    request<Paginated<LogEntry>>(`/logs${buildQuery(params as ResultFilterParams)}`),
  exportLogs: (params: LogQueryParams) =>
    downloadExport('/api/v1/logs/export', params as ResultFilterParams, 'logs.log'),
  logSources: () => request<{ sources: string[] }>('/logs/sources'),

  // 数据导入导出与备份
  exportData: () => downloadExport('/api/v1/data/export', {}, 'connection-checker-data.zip'),
  importData: (
    file: File,
    includeRecords: boolean,
    includeTargets: boolean,
    includeSettings: boolean,
  ) => uploadImport(file, includeRecords, includeTargets, includeSettings),
  listBackups: () => request<{ backups: BackupInfo[] }>('/data/backups'),
  createBackup: () =>
    request<{ ok: boolean; name: string; size: number }>('/data/backups', {
      method: 'POST',
      body: JSON.stringify({}),
    }),
  restoreBackup: (
    name: string,
    include: {
      include_records: boolean
      include_targets: boolean
      include_settings: boolean
    },
  ) =>
    request<ImportStats & { ok: boolean }>(
      `/data/backups/${encodeURIComponent(name)}/restore`,
      { method: 'POST', body: JSON.stringify(include) },
    ),
  downloadBackup: (name: string) =>
    downloadExport(`/api/v1/data/backups/${encodeURIComponent(name)}/download`, {}, name),
  deleteBackup: (name: string) =>
    request<void>(`/data/backups/${encodeURIComponent(name)}`, { method: 'DELETE' }),
}
