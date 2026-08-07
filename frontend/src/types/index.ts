export type CheckMethod = 'ping' | 'port' | 'http'
export type Status = 'success' | 'fail' | 'timeout' | 'error'

export interface TimeRange {
  start: string
  end: string
}

export interface Target {
  id: string
  name: string | null
  ip: string
  check_method: CheckMethod
  check_interval: number
  time_ranges: TimeRange[]
  enabled: boolean
  port: number | null
  scheme: 'http' | 'https'
  url_path: string
  http_success_codes: number[] | null
  timeout: number | null
  created_at: string
  updated_at: string
}

export interface TargetInput {
  name?: string | null
  ip: string
  check_method: CheckMethod
  check_interval?: number
  time_ranges?: TimeRange[]
  enabled?: boolean
  port?: number | null
  scheme?: 'http' | 'https'
  url_path?: string
  http_success_codes?: number[] | null
  timeout?: number | null
}

export interface CheckResult {
  id: string
  target_id: string
  target_name: string | null
  ip: string
  check_method: CheckMethod
  status: Status
  latency_ms: number | null
  message: string
  extra: Record<string, unknown>
  checked_at: string
}

export interface ResultFilterParams {
  status?: string
  ip?: string
  target_name?: string
  target_id?: string
  date?: string
  time_start?: string
  time_end?: string
  page?: number
  page_size?: number
}

export interface Paginated<T> {
  results: T[]
  total: number
  page: number
  page_size: number
  pages: number
}

export interface TargetStatus {
  target_id: string
  name: string | null
  ip: string
  check_method: CheckMethod
  enabled: boolean
  check_interval: number
  last_status: Status | null
  last_latency_ms: number | null
  last_checked_at: string | null
  last_message: string | null
}

export interface StatsSummary {
  total_targets: number
  enabled_targets: number
  last_total_checks: number
  last_success: number
  last_fail: number
  last_timeout: number
  last_error: number
  latest_check_at: string | null
  target_status: TargetStatus[]
}
