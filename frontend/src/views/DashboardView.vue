<script setup lang="ts">
import { computed, h, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  NBadge,
  NButton,
  NCard,
  NDataTable,
  NDatePicker,
  NDescriptions,
  NDescriptionsItem,
  NDropdown,
  NEmpty,
  NInput,
  NLayout,
  NLayoutContent,
  NLayoutHeader,
  NModal,
  NPagination,
  NRadioButton,
  NRadioGroup,
  NSelect,
  NSpace,
  NTag,
  useMessage,
} from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'

import { api } from '@/api'
import AppFooter from '@/components/AppFooter.vue'
import BrandLogo from '@/components/BrandLogo.vue'
import StatsCards from '@/components/StatsCards.vue'
import ThemeToggle from '@/components/ThemeToggle.vue'
import TrendChart from '@/components/TrendChart.vue'
import { formatDateTime } from '@/composables/useAppTime'
import type { CheckResult, ResultFilterParams, StatsSummary, TrendData } from '@/types'

const router = useRouter()
const message = useMessage()

const stats = ref<StatsSummary | null>(null)
const trend = ref<TrendData | null>(null)
const results = ref<CheckResult[]>([])
const total = ref(0)
const pages = ref(0)
const page = ref(1)
const pageSize = 20
const loading = ref(false)
const running = ref(false)

const filters = reactive({
  status: [] as string[],
  check_method: [] as string[],
  ip: '',
  target_name: [] as string[],
  target_id: [] as string[],
  start_at: null as number | null,
  end_at: null as number | null,
})

function toIsoTs(ts: number | null): string | undefined {
  if (!ts) return undefined
  const d = new Date(ts)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

// 多选值可能是数组或 null（naive-ui clear 时 emit null）
function multi(v: unknown): string | undefined {
  return Array.isArray(v) && v.length ? v.join(',') : undefined
}

// 名称（地址）筛选：无名称的目标用 IP 作为值，后端按名称或 IP 匹配
const targetNameOptions = computed(() =>
  (stats.value?.target_status ?? []).map((t) => ({
    label: t.name ? `${t.name} (${t.ip})` : t.ip,
    value: t.name ?? t.ip,
  })),
)

const targetIdOptions = computed(() =>
  (stats.value?.target_status ?? []).map((t) => ({
    label: t.target_id,
    value: t.target_id,
  })),
)

const statusOptions = [
  { label: '成功', value: 'success' },
  { label: '失败', value: 'fail' },
  { label: '超时', value: 'timeout' },
  { label: '错误', value: 'error' },
]

const methodOptions = [
  { label: 'Ping', value: 'ping' },
  { label: '端口', value: 'port' },
  { label: 'HTTP', value: 'http' },
  { label: 'DNS', value: 'dns' },
]

const statusTag: Record<string, { type: 'success' | 'error' | 'warning' | 'default'; label: string }> = {
  success: { type: 'success', label: '成功' },
  fail: { type: 'error', label: '失败' },
  timeout: { type: 'warning', label: '超时' },
  error: { type: 'default', label: '错误' },
}

const methodLabel: Record<string, string> = { ping: 'Ping', port: '端口', http: 'HTTP', dns: 'DNS' }

// 目标卡排序：异常目标（失败/超时/错误）置顶，同等级保持添加顺序（稳定排序）
const sortedTargets = computed(() => {
  const order: Record<string, number> = { fail: 0, timeout: 1, error: 2 }
  const list = stats.value?.target_status ?? []
  return [...list].sort((a, b) => {
    const oa = a.last_status ? (order[a.last_status] ?? 3) : 3
    const ob = b.last_status ? (order[b.last_status] ?? 3) : 3
    return oa - ob
  })
})

// 近 24h 可用率着色：≥99.9% 绿、≥95% 橙、其余红
function uptimeClass(pct: number): string {
  if (pct >= 99.9) return 'up-good'
  if (pct >= 95) return 'up-warn'
  return 'up-bad'
}

const detail = ref<CheckResult | null>(null)
const showDetail = ref(false)

// HTTPS 检查的证书剩余天数（extra.tls.days_remaining），用于提前发现即将过期
const certDays = computed(() => {
  const tls = detail.value?.extra?.tls as { days_remaining?: number } | undefined
  return tls?.days_remaining != null ? tls.days_remaining : null
})

// ping 关键指标（丢包率 / min-max / 抖动 / 标准差），详情弹窗友好展示
const pingStats = computed(() => {
  const e = detail.value?.extra
  if (detail.value?.check_method !== 'ping' || !e) return null
  const loss = e.packet_loss_pct as number | undefined
  if (loss == null) return null
  return {
    loss,
    min: e.min_ms as number | undefined,
    max: e.max_ms as number | undefined,
    jitter: e.jitter_ms as number | undefined,
    stddev: e.stddev_ms as number | undefined,
  }
})

// http 关键指标（最终 URL / 状态码 / TTFB / 响应大小 / TLS 版本）
const httpMeta = computed(() => {
  const e = detail.value?.extra
  if (detail.value?.check_method !== 'http' || !e) return null
  return {
    finalUrl: e.final_url as string | undefined,
    status: e.http_status as number | undefined,
    ttfb: e.ttfb_ms as number | undefined,
    size: e.response_size as number | undefined,
    tlsVersion: (e.tls as { version?: string } | undefined)?.version,
  }
})

// dns 解析结果（地址列表），详情弹窗友好展示
const dnsMeta = computed(() => {
  const e = detail.value?.extra
  if (detail.value?.check_method !== 'dns' || !e) return null
  return {
    resolved: (e.resolved_ip as string[] | undefined) ?? [],
    count: e.resolved_count as number | undefined,
  }
})

// port 连接信息（远端/本机地址），详情弹窗友好展示
const portMeta = computed(() => {
  const e = detail.value?.extra
  if (detail.value?.check_method !== 'port' || !e) return null
  return {
    remoteIp: e.remote_ip as string | undefined,
    remotePort: e.remote_port as number | undefined,
    localIp: e.local_ip as string | undefined,
    localPort: e.local_port as number | undefined,
  }
})

function formatTime(iso: string): string {
  return formatDateTime(iso)
}

// 相对时间：1 分钟内「N 秒前」、1 小时内「N 分钟前」、24 小时内「N 小时前」，
// 超过 24 小时显示绝对时间；每 30 秒刷新一次
const nowTs = ref(Date.now())
let relTimer: number | null = null
function relTime(iso: string): string {
  const diff = Math.max(0, nowTs.value - new Date(iso).getTime())
  if (diff < 60_000) return `${Math.floor(diff / 1000)} 秒前`
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)} 分钟前`
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)} 小时前`
  return formatDateTime(iso)
}

// 行按状态着色（成功绿、失败红、超时橙、错误亮橙）且点击整行可打开详情
function rowProps(r: CheckResult): Record<string, unknown> {
  return {
    class: `row-${r.status}`,
    style: 'cursor: pointer',
    onClick: () => {
      detail.value = r
      showDetail.value = true
    },
  }
}

function errText(e: unknown): string {
  return e instanceof Error ? e.message : '操作失败'
}

async function fetchStats() {
  try {
    stats.value = await api.stats()
  } catch {
    /* 401 由 client 统一跳转 */
  }
}

// 趋势图目标筛选：null = 全部目标；粒度：hour 24h / day 7 天
const trendTargetId = ref<string | null>(null)
const trendUnit = ref<'hour' | 'day'>('hour')

const trendOptions = computed(() =>
  (stats.value?.target_status ?? []).map((t) => ({
    label: t.name ? `${t.name} (${t.ip})` : t.ip,
    value: t.target_id,
  })),
)

async function fetchTrend() {
  try {
    trend.value = await api.statsTrend(
      trendUnit.value === 'day' ? 168 : 24,
      trendTargetId.value ?? undefined,
      trendUnit.value,
    )
  } catch {
    /* 401 由 client 统一跳转 */
  }
}

watch([trendTargetId, trendUnit], () => {
  void fetchTrend()
})

async function fetchResults() {
  loading.value = true
  try {
    const params: ResultFilterParams = {
      status: multi(filters.status),
      check_method: multi(filters.check_method),
      ip: filters.ip,
      target_name: multi(filters.target_name),
      target_id: multi(filters.target_id),
      start_at: toIsoTs(filters.start_at),
      end_at: toIsoTs(filters.end_at),
      page: page.value,
      page_size: pageSize,
    }
    const data = await api.queryResults(params)
    results.value = data.results
    total.value = data.total
    pages.value = data.pages
  } catch {
    /* ignore */
  } finally {
    loading.value = false
  }
}

function refresh() {
  lastFullRefresh = Date.now()
  void fetchStats()
  void fetchResults()
  void fetchTrend()
}

function applyFilters() {
  page.value = 1
  void fetchResults()
}

const exportOptions = [
  { label: '导出 CSV', key: 'csv' },
  { label: '导出 JSON', key: 'json' },
]

function onExportSelect(key: string) {
  const params: ResultFilterParams = {
    status: multi(filters.status),
    check_method: multi(filters.check_method),
    ip: filters.ip,
    target_name: multi(filters.target_name),
    target_id: multi(filters.target_id),
    start_at: toIsoTs(filters.start_at),
    end_at: toIsoTs(filters.end_at),
  }
  api.exportResults(key as 'csv' | 'json', params).catch((e) => message.error(errText(e)))
}

function resetFilters() {
  filters.status = []
  filters.check_method = []
  filters.ip = ''
  filters.target_name = []
  filters.target_id = []
  filters.start_at = null
  filters.end_at = null
  applyFilters()
}

function filterByTarget(targetId: string) {
  filters.target_id = [targetId]
  applyFilters()
}

function runAll() {
  running.value = true
  api
    .runChecks()
    .then((rs) => {
      const fails = rs.filter((r) => r.status !== 'success').length
      if (rs.length === 0) {
        message.warning('没有启用的检查目标')
      } else if (fails > 0) {
        message.warning(`检查完成：${rs.length - fails} 个正常，${fails} 个异常`)
      } else {
        message.success(`检查完成：全部 ${rs.length} 个目标正常`)
      }
      refresh()
    })
    .catch((e) => message.error(errText(e)))
    .finally(() => {
      running.value = false
    })
}

// 正在手动检查的目标集合，防止重复点击触发多次检查
const runningIds = ref<Set<string>>(new Set())

async function runOne(targetId: string) {
  if (runningIds.value.has(targetId)) return
  runningIds.value.add(targetId)
  try {
    const r = await api.runChecks(targetId)
    const status = r[0]?.status ?? 'success'
    const label = statusTag[status]?.label ?? status
    const text = `检查完成：${label}`
    if (status === 'success') message.success(text)
    else if (status === 'timeout') message.warning(text)
    else message.error(text)
    refresh()
  } catch (e) {
    message.error(errText(e))
  } finally {
    runningIds.value.delete(targetId)
  }
}

async function logout() {
  await api.logout()
  router.push('/login')
}

// --- SSE 实时推送 ---
let es: EventSource | null = null
let lastFullRefresh = 0
// 全量刷新节流窗口（毫秒）：目标卡即时局部更新，统计/趋势/表格最多每窗口刷新一次
const SSE_REFRESH_THROTTLE = 10_000

function onSseResult(ev: Event) {
  // 目标卡即时局部更新：避免每次事件都全量拉 3 个接口
  if (stats.value) {
    try {
      const r = JSON.parse((ev as MessageEvent).data) as CheckResult
      const t = stats.value.target_status.find((x) => x.target_id === r.target_id)
      if (t) {
        t.last_status = r.status
        t.last_latency_ms = r.latency_ms
        t.last_checked_at = r.checked_at
        t.last_message = r.message
      }
    } catch {
      /* 解析失败仅跳过局部更新 */
    }
  }
  const now = Date.now()
  if (now - lastFullRefresh >= SSE_REFRESH_THROTTLE) {
    lastFullRefresh = now
    refresh()
  }
}

function connectSse() {
  es = new EventSource('/api/v1/stream')
  es.addEventListener('result', onSseResult)
  es.onerror = () => {
    /* EventSource 自动重连 */
  }
}

onMounted(() => {
  refresh()
  connectSse()
  relTimer = window.setInterval(() => {
    nowTs.value = Date.now()
  }, 30_000)
})

onUnmounted(() => {
  es?.close()
  if (relTimer != null) {
    window.clearInterval(relTimer)
    relTimer = null
  }
})

const columns: DataTableColumns<CheckResult> = [
  {
    title: '时间',
    key: 'checked_at',
    width: 120,
    render: (r) => h('span', { title: formatTime(r.checked_at) }, relTime(r.checked_at)),
  },
  {
    title: '目标',
    key: 'ip',
    minWidth: 180,
    render: (r) =>
      h('div', { class: 'cell-target' }, [
        h('div', { class: 'cell-name' }, r.target_name ?? r.ip),
        r.target_name ? h('div', { class: 'cell-ip' }, r.ip) : null,
      ]),
  },
  {
    title: '方式',
    key: 'check_method',
    width: 80,
    render: (r) => methodLabel[r.check_method] ?? r.check_method,
  },
  {
    title: '状态',
    key: 'status',
    width: 90,
    render: (r) =>
      h(
        NTag,
        { type: statusTag[r.status]?.type ?? 'default', size: 'small', bordered: false },
        { default: () => statusTag[r.status]?.label ?? r.status },
      ),
  },
  {
    title: '延迟',
    key: 'latency_ms',
    width: 90,
    render: (r) => (r.latency_ms != null ? `${r.latency_ms}ms` : '-'),
  },
  {
    title: '详情',
    key: 'message',
    minWidth: 220,
    ellipsis: { tooltip: true },
  },
  {
    title: '操作',
    key: 'action',
    width: 80,
    render: (r) =>
      h(
        NButton,
        {
          size: 'small',
          quaternary: true,
          type: 'primary',
          onClick: () => {
            detail.value = r
            showDetail.value = true
          },
        },
        { default: () => '查看' },
      ),
  },
]
</script>

<template>
  <n-layout class="page">
    <n-layout-header bordered class="header">
      <div class="container header-inner">
        <div class="brand">
          <BrandLogo />
          <span>连接检查工具</span>
        </div>
        <n-space align="center" wrap :size="8">
          <n-button size="small" type="primary" :loading="running" @click="runAll">全部立即检查</n-button>
          <n-button size="small" @click="router.push('/config')">配置管理</n-button>
          <ThemeToggle />
          <n-button size="small" quaternary @click="logout">退出登录</n-button>
        </n-space>
      </div>
    </n-layout-header>

    <n-layout-content class="content">
      <div class="container">
        <n-space vertical size="large">
          <StatsCards :stats="stats" />

          <n-card title="目标状态" size="small">
            <div v-if="stats && stats.target_status.length" class="targets-grid">
              <div
                v-for="t in sortedTargets"
                :key="t.target_id"
                class="target-card"
                :class="[
                  { disabled: !t.enabled },
                  t.last_status ? `st-${t.last_status}` : '',
                ]"
                :title="t.last_checked_at ? `最近检查：${formatTime(t.last_checked_at)}` : '暂无检查记录'"
                @click="filterByTarget(t.target_id)"
              >
                <n-badge
                  dot
                  :type="statusTag[t.last_status ?? 'error']?.type ?? 'default'"
                  :show="!!t.last_status"
                />
                <span class="tname">{{ t.name || t.ip }}</span>
                <n-tag size="small" :bordered="false">{{ methodLabel[t.check_method] }}</n-tag>
                <n-tag
                  v-if="t.last_status"
                  size="small"
                  :type="statusTag[t.last_status]?.type ?? 'default'"
                  :bordered="false"
                >
                  {{ statusTag[t.last_status]?.label }}
                </n-tag>
                <n-tag v-else size="small" :bordered="false">未检查</n-tag>
                <span v-if="t.last_latency_ms != null" class="lat">{{ t.last_latency_ms }}ms</span>
                <span
                  v-if="t.uptime_pct != null"
                  class="uptime"
                  :class="uptimeClass(t.uptime_pct)"
                  :title="`近 24 小时 ${t.uptime_total} 次检查的可用率`"
                >
                  24h {{ t.uptime_pct }}%
                </span>
                <n-tag
                  v-if="t.consecutive_fails > 0"
                  size="small"
                  type="error"
                  :bordered="false"
                  title="当前连续失败次数"
                >
                  连败 {{ t.consecutive_fails }}
                </n-tag>
                <span v-if="!t.enabled" class="off">已停用</span>
                <span v-else-if="t.check_interval === 0" class="off">仅手动</span>
                <n-button
                  v-if="t.enabled"
                  size="tiny"
                  type="primary"
                  secondary
                  :loading="runningIds.has(t.target_id)"
                  @click.stop="runOne(t.target_id)"
                >
                  检查
                </n-button>
              </div>
            </div>
            <n-empty v-else description="还没有检查目标，去「配置管理」添加" />
          </n-card>

          <n-card :title="trendUnit === 'day' ? '成功率趋势（近 7 天）' : '成功率趋势（近 24 小时）'" size="small">
            <template #header-extra>
              <n-space align="center" :size="8">
                <n-radio-group v-model:value="trendUnit" size="small">
                  <n-radio-button value="hour">24h</n-radio-button>
                  <n-radio-button value="day">7 天</n-radio-button>
                </n-radio-group>
                <n-select
                  v-model:value="trendTargetId"
                  :options="trendOptions"
                  clearable
                  placeholder="全部目标"
                  size="small"
                  style="width: 200px"
                />
              </n-space>
            </template>
            <TrendChart v-if="trend && trend.buckets.length" :buckets="trend.buckets" />
            <n-empty v-else description="暂无数据" />
          </n-card>

          <n-card title="检查记录" size="small">
            <n-space align="center" wrap :size="12">
              <n-select
                v-model:value="filters.status"
                :options="statusOptions"
                multiple
                clearable
                placeholder="状态"
                style="width: 150px"
              />
              <n-select
                v-model:value="filters.check_method"
                :options="methodOptions"
                multiple
                clearable
                placeholder="检查方式"
                style="width: 150px"
              />
              <n-input
                v-model:value="filters.ip"
                placeholder="IP 筛选（如 192.168.*）"
                clearable
                style="width: 180px"
                @keyup.enter="applyFilters"
              />
              <n-select
                v-model:value="filters.target_name"
                :options="targetNameOptions"
                multiple
                clearable
                placeholder="目标名称/地址"
                :menu-props="{ class: 'wide-popup' }"
                style="width: 240px"
              />
              <n-select
                v-model:value="filters.target_id"
                :options="targetIdOptions"
                multiple
                clearable
                placeholder="目标 ID"
                :menu-props="{ class: 'wide-popup' }"
                style="width: 240px"
              />
              <n-date-picker
                v-model:value="filters.start_at"
                type="datetime"
                placeholder="起始时间"
                clearable
                style="width: 170px"
              />
              <n-date-picker
                v-model:value="filters.end_at"
                type="datetime"
                placeholder="结束时间"
                clearable
                style="width: 170px"
              />
              <n-button type="primary" secondary @click="applyFilters">查询</n-button>
              <n-button quaternary @click="resetFilters">重置</n-button>
              <n-dropdown trigger="click" :options="exportOptions" @select="onExportSelect">
                <n-button size="small" secondary>导出</n-button>
              </n-dropdown>
            </n-space>

            <div class="table">
              <n-data-table
                :columns="columns"
                :data="results"
                :loading="loading"
                :row-key="(r: CheckResult) => r.id"
                :row-props="rowProps"
                :max-height="520"
                size="small"
                single-line
              />
              <div class="pager">
                <span class="pager-info">共 {{ total }} 条</span>
                <n-pagination
                  v-model:page="page"
                  :item-count="total"
                  :page-size="pageSize"
                  @update:page="fetchResults"
                />
              </div>
            </div>
          </n-card>
        </n-space>
      </div>
    </n-layout-content>
    <AppFooter />
  </n-layout>

  <n-modal v-model:show="showDetail">
    <n-card style="width: 600px; max-width: 94vw" title="检查详情" :bordered="false" size="huge" role="dialog" aria-modal="true">
      <n-descriptions v-if="detail" label-placement="left" :column="1" bordered size="small">
        <n-descriptions-item label="时间">{{ formatTime(detail.checked_at) }}</n-descriptions-item>
        <n-descriptions-item label="目标">{{ detail.target_name ? `${detail.target_name} (${detail.ip})` : detail.ip }}</n-descriptions-item>
        <n-descriptions-item label="方式">{{ methodLabel[detail.check_method] }}</n-descriptions-item>
        <n-descriptions-item label="状态">
          <n-tag size="small" :type="statusTag[detail.status]?.type ?? 'default'" :bordered="false">
            {{ statusTag[detail.status]?.label }}
          </n-tag>
        </n-descriptions-item>
        <n-descriptions-item label="延迟">{{ detail.latency_ms != null ? `${detail.latency_ms}ms` : '-' }}</n-descriptions-item>
        <n-descriptions-item v-if="pingStats" label="Ping 统计">
          丢包 {{ pingStats.loss }}%
          <template v-if="pingStats.min != null && pingStats.max != null">
            · 延迟 {{ pingStats.min }}~{{ pingStats.max }}ms
          </template>
          <template v-if="pingStats.jitter"> · 抖动 {{ pingStats.jitter }}ms</template>
          <template v-if="pingStats.stddev"> · 标准差 {{ pingStats.stddev }}ms</template>
        </n-descriptions-item>
        <n-descriptions-item v-if="httpMeta" label="HTTP 详情">
          <template v-if="httpMeta.finalUrl">{{ httpMeta.finalUrl }} · </template>
          <template v-if="httpMeta.status != null">状态 {{ httpMeta.status }} · </template>
          <template v-if="httpMeta.ttfb != null">TTFB {{ httpMeta.ttfb }}ms · </template>
          <template v-if="httpMeta.size != null">{{ httpMeta.size }}B · </template>
          <template v-if="httpMeta.tlsVersion">TLS {{ httpMeta.tlsVersion }}</template>
        </n-descriptions-item>
        <n-descriptions-item v-if="dnsMeta" label="解析结果">
          {{ dnsMeta.resolved.length ? dnsMeta.resolved.join('、') : '无地址' }}
          <template v-if="dnsMeta.count != null">（共 {{ dnsMeta.count }} 个地址）</template>
        </n-descriptions-item>
        <n-descriptions-item v-if="portMeta" label="连接信息">
          <template v-if="portMeta.remoteIp">{{ portMeta.remoteIp }}:{{ portMeta.remotePort }}</template>
          <template v-if="portMeta.localIp"> · 本机 {{ portMeta.localIp }}:{{ portMeta.localPort }}</template>
        </n-descriptions-item>
        <n-descriptions-item v-if="certDays != null" label="证书剩余">
          <n-tag
            size="small"
            :type="certDays <= 0 ? 'error' : certDays < 30 ? 'warning' : 'success'"
            :bordered="false"
          >
            {{ certDays }} 天
          </n-tag>
        </n-descriptions-item>
        <n-descriptions-item label="信息">{{ detail.message }}</n-descriptions-item>
        <n-descriptions-item label="附加数据">
          <pre class="extra">{{ JSON.stringify(detail.extra, null, 2) }}</pre>
        </n-descriptions-item>
      </n-descriptions>
      <template #footer>
        <n-space justify="end">
          <n-button @click="showDetail = false">关闭</n-button>
        </n-space>
      </template>
    </n-card>
  </n-modal>
</template>

<style scoped>
.page {
  min-height: 100vh;
  padding-top: 20px;
}
.header {
  padding: 0;
}
.header-inner {
  max-width: 1200px;
  margin: 0 auto;
  padding: 12px 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.brand {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 18px;
  font-weight: 600;
  white-space: nowrap;
}
.content {
  padding: 32px 0 48px;
}
.container {
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 24px;
}
.targets-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 12px;
}
@media (max-width: 480px) {
  .targets-grid {
    grid-template-columns: 1fr;
  }
}
.target-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid var(--cc-panel-border);
  border-radius: 8px;
  cursor: pointer;
  transition:
    background 0.2s,
    border-color 0.2s;
}
.target-card:hover {
  background: var(--cc-hover);
}
.target-card.disabled {
  opacity: 0.55;
}
/* 故障目标边框着色，便于一眼识别 */
.target-card.st-fail {
  border-color: rgba(208, 59, 59, 0.55);
}
.target-card.st-timeout {
  border-color: rgba(250, 178, 25, 0.55);
}
.target-card.st-error {
  border-color: rgba(236, 131, 90, 0.55);
}
.tname {
  font-weight: 600;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.lat {
  color: var(--cc-text-3);
  font-size: 12px;
}
.off {
  color: var(--cc-text-3);
  font-size: 12px;
}
.uptime {
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
}
.up-good {
  color: #0ca30c;
}
.up-warn {
  color: #fab219;
}
.up-bad {
  color: #d03b3b;
}
.table {
  margin-top: 14px;
}
.table :deep(.row-success) {
  background: rgba(12, 163, 12, 0.05);
}
.table :deep(.row-fail) {
  background: rgba(208, 59, 59, 0.08);
}
.table :deep(.row-timeout) {
  background: rgba(250, 178, 25, 0.06);
}
.table :deep(.row-error) {
  background: rgba(236, 131, 90, 0.07);
}
.cell-name {
  font-weight: 600;
  line-height: 1.3;
}
.cell-ip {
  font-size: 12px;
  color: var(--cc-text-3);
  line-height: 1.3;
}
.pager {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 12px;
  gap: 8px;
  flex-wrap: wrap;
}
.pager-info {
  color: var(--cc-text-3);
  font-size: 13px;
}
.extra {
  margin: 0;
  font-size: 12px;
  max-height: 200px;
  overflow: auto;
  white-space: pre-wrap;
}
@media (max-width: 640px) {
  .header-inner {
    padding: 10px 16px;
    flex-wrap: wrap;
  }
  .container {
    padding: 0 16px;
  }
  .content {
    padding: 16px 0 32px;
  }
}
</style>
