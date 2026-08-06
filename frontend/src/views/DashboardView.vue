<script setup lang="ts">
import { h, onMounted, onUnmounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  NBadge,
  NButton,
  NCard,
  NDataTable,
  NDatePicker,
  NDescriptions,
  NDescriptionsItem,
  NEmpty,
  NGrid,
  NGridItem,
  NInput,
  NModal,
  NPagination,
  NSelect,
  NSpace,
  NTag,
  NTimePicker,
  useMessage,
} from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'

import { api } from '@/api'
import StatsCards from '@/components/StatsCards.vue'
import type { CheckResult, ResultFilterParams, StatsSummary } from '@/types'

const router = useRouter()
const message = useMessage()

const stats = ref<StatsSummary | null>(null)
const results = ref<CheckResult[]>([])
const total = ref(0)
const pages = ref(0)
const page = ref(1)
const pageSize = 20
const loading = ref(false)
const running = ref(false)

const dateValue = ref<number | null>(null)

const filters = reactive({
  status: 'all',
  ip: '',
  target_id: '',
  date: null as string | null,
  time_start: null as string | null,
  time_end: null as string | null,
})

const statusOptions = [
  { label: '全部状态', value: 'all' },
  { label: '成功', value: 'success' },
  { label: '失败', value: 'fail' },
  { label: '超时', value: 'timeout' },
  { label: '错误', value: 'error' },
]

const statusTag: Record<string, { type: 'success' | 'error' | 'warning' | 'default'; label: string }> = {
  success: { type: 'success', label: '成功' },
  fail: { type: 'error', label: '失败' },
  timeout: { type: 'warning', label: '超时' },
  error: { type: 'default', label: '错误' },
}

const methodLabel: Record<string, string> = { ping: 'Ping', port: '端口', http: 'HTTP' }

const detail = ref<CheckResult | null>(null)
const showDetail = ref(false)

function formatTime(iso: string): string {
  const d = new Date(iso)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
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

async function fetchResults() {
  loading.value = true
  try {
    const params: ResultFilterParams = {
      status: filters.status,
      ip: filters.ip,
      target_id: filters.target_id,
      date: filters.date ?? undefined,
      time_start: filters.time_start ?? undefined,
      time_end: filters.time_end ?? undefined,
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
  void fetchStats()
  void fetchResults()
}

function applyFilters() {
  page.value = 1
  void fetchResults()
}

function resetFilters() {
  filters.status = 'all'
  filters.ip = ''
  filters.target_id = ''
  filters.date = null
  filters.time_start = null
  filters.time_end = null
  dateValue.value = null
  applyFilters()
}

function filterByTarget(targetId: string) {
  filters.target_id = targetId
  applyFilters()
}

function setDateFilter(value: number | null) {
  if (!value) {
    filters.date = null
    return
  }
  const d = new Date(value)
  const p = (n: number) => String(n).padStart(2, '0')
  filters.date = `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

async function runAll() {
  running.value = true
  try {
    const r = await api.runChecks()
    message.success(`已触发 ${r.length} 个目标检查`)
    refresh()
  } catch (e) {
    message.error(errText(e))
  } finally {
    running.value = false
  }
}

async function runOne(targetId: string) {
  try {
    const r = await api.runChecks(targetId)
    message.success(`检查完成：${r[0]?.status ?? '完成'}`)
    refresh()
  } catch (e) {
    message.error(errText(e))
  }
}

async function logout() {
  await api.logout()
  router.push('/login')
}

// --- SSE 实时推送 ---
let es: EventSource | null = null

function connectSse() {
  es = new EventSource('/api/v1/stream')
  es.addEventListener('result', () => refresh())
  es.onerror = () => {
    /* EventSource 自动重连 */
  }
}

onMounted(() => {
  refresh()
  connectSse()
})

onUnmounted(() => {
  es?.close()
})

const columns: DataTableColumns<CheckResult> = [
  {
    title: '时间',
    key: 'checked_at',
    width: 170,
    render: (r) => formatTime(r.checked_at),
  },
  {
    title: '目标',
    key: 'ip',
    minWidth: 180,
    render: (r) => `${r.target_name ?? ''} ${r.ip}`.trim(),
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
      <div class="brand">连接检查工具</div>
      <n-space align="center">
        <n-button size="small" type="primary" :loading="running" @click="runAll">全部立即检查</n-button>
        <n-button size="small" @click="router.push('/config')">配置管理</n-button>
        <n-button size="small" quaternary @click="logout">退出登录</n-button>
      </n-space>
    </n-layout-header>

    <n-layout-content class="content">
      <n-space vertical size="large">
        <StatsCards :stats="stats" />

        <n-card title="目标状态" size="small">
          <n-grid v-if="stats && stats.target_status.length" :cols="1" :x-gap="12" :y-gap="12" responsive="screen" item-responsive>
            <n-grid-item v-for="t in stats.target_status" :key="t.target_id" span="1 m:1">
              <div
                class="target-card"
                :class="{ disabled: !t.enabled }"
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
                <span v-if="t.last_latency_ms != null" class="lat">{{ t.last_latency_ms }}ms</span>
                <span v-if="!t.enabled" class="off">已停用</span>
                <n-button size="tiny" type="primary" secondary @click.stop="runOne(t.target_id)">
                  检查
                </n-button>
              </div>
            </n-grid-item>
          </n-grid>
          <n-empty v-else description="还没有检查目标，去「配置管理」添加" />
        </n-card>

        <n-card title="检查记录" size="small">
          <n-space align="center" wrap :size="12">
            <n-select v-model:value="filters.status" :options="statusOptions" style="width: 130px" />
            <n-input v-model:value="filters.ip" placeholder="IP 筛选" clearable style="width: 160px" />
            <n-date-picker v-model:value="dateValue" style="width: 150px" @update:value="setDateFilter" />
            <n-time-picker
              :value="filters.time_start as unknown as number"
              format="HH:mm"
              value-format="HH:mm"
              placeholder="开始时间"
              style="width: 120px"
              @update:value="(v: unknown) => (filters.time_start = v ? (v as string) : null)"
            />
            <n-time-picker
              :value="filters.time_end as unknown as number"
              format="HH:mm"
              value-format="HH:mm"
              placeholder="结束时间"
              style="width: 120px"
              @update:value="(v: unknown) => (filters.time_end = v ? (v as string) : null)"
            />
            <n-button type="primary" secondary @click="applyFilters">查询</n-button>
            <n-button quaternary @click="resetFilters">重置</n-button>
          </n-space>

          <div class="table">
            <n-data-table
              :columns="columns"
              :data="results"
              :loading="loading"
              :row-key="(r: CheckResult) => r.id"
              :max-height="520"
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
    </n-layout-content>
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
}
.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 20px;
}
.brand {
  font-size: 18px;
  font-weight: 600;
}
.content {
  padding: 20px;
  max-width: 1280px;
  margin: 0 auto;
}
.target-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  border: 1px solid var(--n-border-color);
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.2s;
}
.target-card:hover {
  background: var(--n-hover-color);
}
.target-card.disabled {
  opacity: 0.55;
}
.tname {
  font-weight: 600;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.lat {
  color: var(--n-text-color-3);
  font-size: 12px;
}
.off {
  color: var(--n-text-color-3);
  font-size: 12px;
}
.table {
  margin-top: 14px;
}
.pager {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 12px;
}
.pager-info {
  color: var(--n-text-color-3);
  font-size: 13px;
}
.extra {
  margin: 0;
  font-size: 12px;
  max-height: 200px;
  overflow: auto;
  white-space: pre-wrap;
}
</style>
