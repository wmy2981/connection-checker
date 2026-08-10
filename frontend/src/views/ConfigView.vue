<script setup lang="ts">
import { h, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  NButton,
  NCard,
  NDataTable,
  NDatePicker,
  NEmpty,
  NInput,
  NInputNumber,
  NLayout,
  NLayoutContent,
  NLayoutHeader,
  NModal,
  NPagination,
  NPopconfirm,
  NSelect,
  NSpace,
  NSwitch,
  NTag,
  useMessage,
} from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'

import { api } from '@/api'
import AppFooter from '@/components/AppFooter.vue'
import TargetFormModal from '@/components/TargetFormModal.vue'
import ThemeToggle from '@/components/ThemeToggle.vue'
import type { AppSettings, LogEntry, Target, TargetInput, WebhookConfig } from '@/types'

const router = useRouter()
const message = useMessage()

const targets = ref<Target[]>([])
const loading = ref(false)
const modalShow = ref(false)
const editing = ref<Target | null>(null)

const webhook = ref<WebhookConfig>({ enabled: true, url: null, fail_threshold: 3 })
const webhookUrl = ref('')
const webhookSaving = ref(false)
const webhookTesting = ref(false)

const appSettings = ref<AppSettings>({
  result_max_records: 50000,
  ping_count: 4,
  connect_timeout: 3,
  http_timeout: 5,
  log_level: 'INFO',
})
const appSaving = ref(false)

const logLevelOptions = [
  { label: 'DEBUG', value: 'DEBUG' },
  { label: 'INFO', value: 'INFO' },
  { label: 'WARN', value: 'WARN' },
  { label: 'ERROR', value: 'ERROR' },
]

// --- 日志管理弹窗 ---
const showLogs = ref(false)
const logLoading = ref(false)
const logExporting = ref(false)
const logLevel = ref('')
const logStart = ref<number | null>(null)
const logEnd = ref<number | null>(null)
const logPage = ref(1)
const logData = ref<{ results: LogEntry[]; total: number; page_size: number; pages: number }>({
  results: [],
  total: 0,
  page_size: 100,
  pages: 0,
})

const logLevelTagType: Record<string, 'default' | 'info' | 'warning' | 'error'> = {
  DEBUG: 'default',
  INFO: 'info',
  WARN: 'warning',
  WARNING: 'warning',
  ERROR: 'error',
}

const logColumns: DataTableColumns<LogEntry> = [
  { title: '时间', key: 'time', width: 160 },
  {
    title: '级别',
    key: 'level',
    width: 80,
    render: (row) => h(NTag, { size: 'small', bordered: false, type: logLevelTagType[row.level] ?? 'default' }, { default: () => row.level }),
  },
  { title: '来源', key: 'name', width: 120 },
  {
    title: '消息',
    key: 'message',
    minWidth: 280,
    render: (row) =>
      h('div', { style: 'white-space: pre-wrap; word-break: break-all; line-height: 1.5;' }, row.message),
  },
]

function toLogTs(ts: number | null): string | undefined {
  if (!ts) return undefined
  const d = new Date(ts)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

function openLogs() {
  showLogs.value = true
  logPage.value = 1
  fetchLogs()
}

async function fetchLogs() {
  logLoading.value = true
  try {
    logData.value = await api.queryLogs({
      level: logLevel.value || undefined,
      start: toLogTs(logStart.value),
      end: toLogTs(logEnd.value),
      page: logPage.value,
      page_size: 100,
    })
  } catch (e) {
    message.error(errText(e))
  } finally {
    logLoading.value = false
  }
}

async function exportLogs() {
  logExporting.value = true
  try {
    await api.exportLogs({
      level: logLevel.value || undefined,
      start: toLogTs(logStart.value),
      end: toLogTs(logEnd.value),
    })
  } catch (e) {
    message.error(errText(e))
  } finally {
    logExporting.value = false
  }
}

function errText(e: unknown): string {
  return e instanceof Error ? e.message : '操作失败'
}

async function load() {
  loading.value = true
  try {
    targets.value = await api.listTargets()
  } catch {
    /* 401 由 client 处理 */
  } finally {
    loading.value = false
  }
}

async function loadAppSettings() {
  try {
    appSettings.value = await api.getAppSettings()
  } catch {
    /* 401 由 client 处理 */
  }
}

async function saveAppSettings() {
  appSaving.value = true
  try {
    appSettings.value = await api.updateAppSettings(appSettings.value)
    message.success('全局设置已保存')
  } catch (e) {
    message.error(errText(e))
  } finally {
    appSaving.value = false
  }
}

async function loadWebhook() {
  try {
    const cfg = await api.getWebhook()
    webhook.value = cfg
    webhookUrl.value = cfg.url ?? ''
  } catch {
    /* 401 由 client 处理 */
  }
}

async function testWebhook() {
  const url = webhookUrl.value.trim()
  webhookTesting.value = true
  try {
    const r = await api.testWebhook(url)
    message.success(`推送成功（${r.info}）`)
  } catch (e) {
    message.error(errText(e))
  } finally {
    webhookTesting.value = false
  }
}

async function saveWebhook() {
  webhookSaving.value = true
  try {
    const saved = await api.updateWebhook({
      ...webhook.value,
      url: webhookUrl.value.trim() || null,
    })
    webhook.value = saved
    webhookUrl.value = saved.url ?? ''
    message.success('告警配置已保存')
  } catch (e) {
    message.error(errText(e))
  } finally {
    webhookSaving.value = false
  }
}

onMounted(() => {
  load()
  loadAppSettings()
  loadWebhook()
})

function openCreate() {
  editing.value = null
  modalShow.value = true
}

function openEdit(t: Target) {
  editing.value = t
  modalShow.value = true
}

async function save(payload: TargetInput) {
  try {
    if (editing.value) {
      await api.updateTarget(editing.value.id, payload)
      message.success('已更新')
    } else {
      await api.createTarget(payload)
      message.success('已添加')
    }
    modalShow.value = false
    await load()
  } catch (e) {
    message.error(errText(e))
  }
}

async function remove(id: string) {
  try {
    await api.deleteTarget(id)
    message.success('已删除')
    await load()
  } catch (e) {
    message.error(errText(e))
  }
}

async function toggleEnabled(t: Target, value: boolean) {
  try {
    await api.updateTarget(t.id, { enabled: value })
    await load()
  } catch (e) {
    message.error(errText(e))
    await load()
  }
}

async function runOne(t: Target) {
  try {
    const r = await api.runChecks(t.id)
    message.success(`检查完成：${r[0]?.status ?? '完成'}`)
  } catch (e) {
    message.error(errText(e))
  }
}

function methodText(t: Target): string {
  if (t.check_method === 'port') return `端口 :${t.port}`
  if (t.check_method === 'http') return t.port ? `HTTP (${t.scheme}:${t.port})` : `HTTP (${t.scheme})`
  if (t.check_method === 'dns') return 'DNS 解析'
  return 'Ping'
}

const columns: DataTableColumns<Target> = [
  { title: '名称', key: 'name', render: (t) => t.name || '-' },
  { title: 'IP / 主机名', key: 'ip', minWidth: 140 },
  { title: '方式', key: 'check_method', render: (t) => methodText(t) },
  {
    title: '间隔',
    key: 'check_interval',
    width: 80,
    render: (t) => (t.check_interval === 0 ? '关闭' : `${t.check_interval}s`),
  },
  {
    title: '时间窗口',
    key: 'time_ranges',
    minWidth: 150,
    render: (t) => t.time_ranges.map((r) => `${r.start}–${r.end}`).join(', '),
  },
  {
    title: '启用',
    key: 'enabled',
    width: 70,
    render: (t) => h(NSwitch, { value: t.enabled, onUpdateValue: (v: boolean) => toggleEnabled(t, v) }),
  },
  {
    title: '操作',
    key: 'action',
    width: 220,
    render: (t) =>
      h(NSpace, { size: 4 }, () => [
        h(
          NButton,
          { size: 'tiny', secondary: true, type: 'primary', onClick: () => runOne(t) },
          { default: () => '检查' },
        ),
        h(
          NButton,
          { size: 'tiny', secondary: true, onClick: () => openEdit(t) },
          { default: () => '编辑' },
        ),
        h(
          NPopconfirm,
          { onPositiveClick: () => remove(t.id) },
          {
            trigger: () =>
              h(NButton, { size: 'tiny', type: 'error', secondary: true }, { default: () => '删除' }),
            default: () => '确认删除该目标？',
          },
        ),
      ]),
  },
]
</script>

<template>
  <n-layout class="page">
    <n-layout-header bordered class="header">
      <div class="container header-inner">
        <div class="brand">配置管理</div>
        <n-space align="center" wrap :size="8">
          <n-button size="small" @click="router.push('/dashboard')">返回仪表盘</n-button>
          <n-button size="small" @click="openLogs">日志管理</n-button>
          <ThemeToggle />
          <n-button size="small" type="primary" @click="openCreate">新增目标</n-button>
        </n-space>
      </div>
    </n-layout-header>

    <n-layout-content class="content">
      <div class="container">
        <n-space vertical size="large">
          <n-card title="检查目标" size="small">
          <template #header-extra>
            <n-button size="small" secondary @click="load">刷新</n-button>
          </template>
          <n-data-table
            v-if="targets.length"
            :columns="columns"
            :data="targets"
            :loading="loading"
            :row-key="(t: Target) => t.id"
            :max-height="640"
          />
          <n-empty v-else description="暂无检查目标，点击「新增目标」添加" />
          </n-card>

          <n-card title="全局检查设置" size="small">
          <n-space vertical size="large">
            <n-space align="center" :size="12" wrap>
              <span class="label">结果保留条数</span>
              <n-input-number
                v-model:value="appSettings.result_max_records"
                :min="100"
                :max="1000000"
                :step="1000"
                style="width: 180px"
              />
              <span class="hint">results.jsonl 保留上限，超出自动裁掉最旧记录</span>
            </n-space>
            <n-space align="center" :size="12" wrap>
              <span class="label">Ping 发包数</span>
              <n-input-number v-model:value="appSettings.ping_count" :min="1" :max="20" style="width: 180px" />
              <span class="hint">全局默认；单个 Ping 目标可在「编辑」中单独覆盖</span>
            </n-space>
            <n-space align="center" :size="12" wrap>
              <span class="label">Ping/TCP 超时(秒)</span>
              <n-input-number
                v-model:value="appSettings.connect_timeout"
                :min="0.1"
                :max="60"
                :step="0.5"
                style="width: 180px"
              />
            </n-space>
            <n-space align="center" :size="12" wrap>
              <span class="label">HTTP 超时(秒)</span>
              <n-input-number
                v-model:value="appSettings.http_timeout"
                :min="0.1"
                :max="120"
                :step="0.5"
                style="width: 180px"
              />
              <span class="hint">配置存于 config.json，外部编辑 5 秒内自动生效</span>
            </n-space>
            <n-space align="center" :size="12" wrap>
              <span class="label">日志等级</span>
              <n-select
                v-model:value="appSettings.log_level"
                :options="logLevelOptions"
                style="width: 120px"
              />
              <span class="hint">保存到 config.json，热加载生效；级别越低日志越详细</span>
            </n-space>
            <n-space justify="end">
              <n-button type="primary" :loading="appSaving" @click="saveAppSettings">保存全局设置</n-button>
            </n-space>
          </n-space>
          </n-card>

          <n-card title="告警通知（Webhook）" size="small">
          <n-space vertical size="large">
            <n-space align="center" :size="12">
              <span>启用告警</span>
              <n-switch v-model:value="webhook.enabled" />
              <span class="hint">连续失败达到阈值时通过 Webhook 推送，目标恢复时通知</span>
            </n-space>
            <n-space vertical :size="8">
              <span class="label">Webhook 地址（兼容 Gotify / 企业微信 / 自建服务，POST JSON）</span>
              <n-input v-model:value="webhookUrl" placeholder="https://gotify.example.com/message?token=..." clearable />
            </n-space>
            <n-space align="center" :size="12">
              <span>连续失败阈值</span>
              <n-input-number v-model:value="webhook.fail_threshold" :min="1" :max="100" style="width: 120px" />
              <span class="hint">连续失败 N 次触发告警</span>
            </n-space>
            <n-space justify="end">
              <n-button :loading="webhookTesting" @click="testWebhook">测试推送</n-button>
              <n-button type="primary" :loading="webhookSaving" @click="saveWebhook">保存告警配置</n-button>
            </n-space>
          </n-space>
          </n-card>
        </n-space>
      </div>
    </n-layout-content>
    <AppFooter />
  </n-layout>

  <TargetFormModal
    v-model:show="modalShow"
    :target="editing"
    @save="save"
  />

  <n-modal
    v-model:show="showLogs"
    preset="card"
    title="日志管理"
    style="width: 900px; max-width: 96vw"
  >
    <n-space vertical :size="12">
      <n-space align="center" :size="12" wrap>
        <span class="label">最低级别</span>
        <n-select
          v-model:value="logLevel"
          :options="[{ label: '全部', value: '' }, ...logLevelOptions]"
          style="width: 110px"
        />
        <n-date-picker v-model:value="logStart" type="datetime" clearable style="width: 190px" placeholder="起始时间" />
        <n-date-picker v-model:value="logEnd" type="datetime" clearable style="width: 190px" placeholder="结束时间" />
        <n-button size="small" type="primary" :loading="logLoading" @click="fetchLogs">查询</n-button>
        <n-button size="small" :loading="logExporting" @click="exportLogs">导出</n-button>
      </n-space>
      <n-data-table
        :columns="logColumns"
        :data="logData.results"
        :loading="logLoading"
        :max-height="420"
        size="small"
      />
      <n-space align="center" justify="space-between" :size="12">
        <span class="hint">共 {{ logData.total }} 条；时间为服务器本地时区</span>
        <n-pagination
          v-model:page="logPage"
          :page-count="logData.pages || 1"
          :page-size="logData.page_size"
          @update:page="fetchLogs"
        />
      </n-space>
    </n-space>
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
  font-size: 18px;
  font-weight: 600;
  white-space: nowrap;
}
.content {
  padding: 32px 0 48px;
}
.hint {
  color: var(--cc-text-3);
  font-size: 12px;
}
.label {
  font-size: 13px;
}
.container {
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 24px;
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
