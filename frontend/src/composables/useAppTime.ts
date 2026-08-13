import { ref } from 'vue'

import { api } from '@/api'

/**
 * 应用统一时区：以容器 TZ 环境变量为准，后端 /api/v1/meta 返回 IANA 名称。
 * 未设置时回退到浏览器本地时区。所有时间显示与日期筛选都应经由本模块，
 * 保证前后端时区一致（后端筛选同样基于容器时区）。
 */
const tz = ref<string>('UTC')
let loaded = false

export async function loadAppTz(): Promise<void> {
  if (loaded) return
  loaded = true
  try {
    const meta = await api.meta()
    if (meta.tz) tz.value = meta.tz
  } catch {
    tz.value = '' // 空值 → 用浏览器时区
  }
}

export function appTz(): string {
  return tz.value
}

function fmtParts(date: Date, opts: Intl.DateTimeFormatOptions): Record<string, string> {
  const options: Intl.DateTimeFormatOptions = { hour12: false, ...opts }
  if (tz.value) options.timeZone = tz.value
  const parts = new Intl.DateTimeFormat('en-US', options).formatToParts(date)
  const map: Record<string, string> = {}
  for (const p of parts) map[p.type] = p.value
  return map
}

/** 格式化 ISO 时间戳为 `YYYY-MM-DD HH:mm:ss`（容器时区）。 */
export function formatDateTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const p = fmtParts(d, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
  return `${p.year}-${p.month}-${p.day} ${p.hour}:${p.minute}:${p.second}`
}

/**
 * 相对时间：1 分钟内「N 秒前」、1 小时内「N 分钟前」、24 小时内「N 小时前」，
 * 超过 24 小时返回绝对时间。now 由调用方传入以支持定时刷新。
 */
export function relativeTime(iso: string, now: number = Date.now()): string {
  const diff = Math.max(0, now - new Date(iso).getTime())
  if (diff < 60_000) return `${Math.floor(diff / 1000)} 秒前`
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)} 分钟前`
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)} 小时前`
  return formatDateTime(iso)
}

/** 将时间戳转为容器时区的 `YYYY-MM-DD`（用于历史日期筛选）。 */
export function dateFromTimestamp(ms: number): string {
  const d = new Date(ms)
  if (Number.isNaN(d.getTime())) return ''
  const p = fmtParts(d, { year: 'numeric', month: '2-digit', day: '2-digit' })
  return `${p.year}-${p.month}-${p.day}`
}
