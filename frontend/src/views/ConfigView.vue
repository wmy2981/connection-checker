<script setup lang="ts">
import { computed, h, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
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
import BrandLogo from '@/components/BrandLogo.vue'
import DataImportDialog from '@/components/DataImportDialog.vue'
import TargetFormModal from '@/components/TargetFormModal.vue'
import ThemeToggle from '@/components/ThemeToggle.vue'
import { copyText } from '@/composables/useClipboard'
import { formatDateTime } from '@/composables/useAppTime'
import type { AppSettings, BackupInfo, CheckResult, LogEntry, S3Config, S3ConfigInput, Target, TargetInput, TargetStatus, WebhookConfig } from '@/types'

const router = useRouter()
const message = useMessage()

const targets = ref<Target[]>([])
const loading = ref(false)
const modalShow = ref(false)
const editing = ref<Target | null>(null)
// 每个目标的最新检查状态（来自 /stats/summary），供「最近状态」列展示
const targetStatus = ref<Record<string, TargetStatus>>({})

const webhook = ref<WebhookConfig>({ enabled: true, url: null, fail_threshold: 3 })
const webhookUrl = ref('')
const webhookSaving = ref(false)
const webhookTesting = ref(false)

const appSettings = ref<AppSettings>({
  result_max_records: 50000,
  ping_count: 4,
  connect_timeout: 3,
  http_timeout: 5,
  stats_window: 50,
  log_level: 'INFO',
  log_cleanup_mode: 'delete',
  log_retention_days: 30,
  storage_mode: 'local',
  brand_icon: null,
})
const appSaving = ref(false)

const logCleanupOptions = [
  { label: '删除', value: 'delete' },
  { label: '上传 S3', value: 'upload' },
  { label: '不清理', value: 'none' },
]

const storageModeOptions = [
  { label: '仅本地', value: 'local' },
  { label: '本地 + S3 双写', value: 'both' },
  { label: '仅 S3', value: 's3' },
]

const s3 = ref<S3Config>({
  enabled: false,
  endpoint: '',
  bucket: '',
  region: null,
  datapath: '',
  has_credentials: false,
})
const s3Credentials = ref<{ access_id: string; access_key: string }>({ access_id: '', access_key: '' })
const s3Saving = ref(false)
const s3Testing = ref(false)

const s3Ready = computed(
  () =>
    s3.value.enabled &&
    !!s3.value.endpoint &&
    !!s3.value.bucket &&
    !!s3.value.datapath &&
    s3.value.has_credentials,
)

const apiToken = ref<string | null>(null)

const brandIconInput = ref('')
const brandSaving = ref(false)

// --- 数据管理（导入/导出/备份） ---
const showImport = ref(false)
const showRestore = ref(false)
const restoringBackup = ref<string | null>(null)
const dataBusy = ref(false)
const showBackups = ref(false)
const backups = ref<BackupInfo[]>([])
const backupsLoading = ref(false)
const backupCreating = ref(false)
const backupDeleting = ref<string | null>(null)
const showRename = ref(false)
const renamingBackup = ref('')
const renameInput = ref('')
const renameSaving = ref(false)

async function exportData() {
  try {
    await api.exportData()
  } catch (e) {
    message.error(errText(e))
  }
}

async function onImportConfirm(payload: {
  file?: File
  include_records: boolean
  include_targets: boolean
  include_settings: boolean
}) {
  if (!payload.file) return
  dataBusy.value = true
  try {
    const r = await api.importData(
      payload.file,
      payload.include_records,
      payload.include_targets,
      payload.include_settings,
    )
    message.success(
      `导入完成：记录 ${r.records} 条、目标 ${r.targets} 个${r.settings ? '、设置' : ''}；导入前已自动备份（${r.backup}）`,
    )
    showImport.value = false
    refreshSettings()
  } catch (e) {
    message.error(errText(e))
  } finally {
    dataBusy.value = false
  }
}

async function onRestoreConfirm(payload: {
  file?: File
  include_records: boolean
  include_targets: boolean
  include_settings: boolean
}) {
  const name = restoringBackup.value
  if (!name) return
  dataBusy.value = true
  try {
    const r = await api.restoreBackup(name, {
      include_records: payload.include_records,
      include_targets: payload.include_targets,
      include_settings: payload.include_settings,
    })
    message.success(
      `恢复完成：记录 ${r.records} 条、目标 ${r.targets} 个${r.settings ? '、设置' : ''}；恢复前已自动备份（${r.backup}）`,
    )
    showRestore.value = false
    refreshSettings()
  } catch (e) {
    message.error(errText(e))
  } finally {
    dataBusy.value = false
  }
}

// 导入/恢复改动配置后刷新页面数据（目标表格、设置、令牌等）
function refreshSettings() {
  load()
  loadAppSettings()
  loadWebhook()
  loadS3()
  loadApiToken()
}

async function openBackups() {
  showBackups.value = true
  await loadBackups()
}

async function loadBackups() {
  backupsLoading.value = true
  try {
    backups.value = (await api.listBackups()).backups
  } catch {
    /* 401 由 client 处理 */
  } finally {
    backupsLoading.value = false
  }
}

async function createBackup() {
  backupCreating.value = true
  try {
    const r = await api.createBackup()
    message.success(`备份已创建：${r.name}`)
    await loadBackups()
  } catch (e) {
    message.error(errText(e))
  } finally {
    backupCreating.value = false
  }
}

async function downloadBackup(name: string) {
  try {
    await api.downloadBackup(name)
  } catch (e) {
    message.error(errText(e))
  }
}

async function removeBackup(name: string) {
  backupDeleting.value = name
  try {
    await api.deleteBackup(name)
    message.success('备份已删除')
    await loadBackups()
  } catch (e) {
    message.error(errText(e))
  } finally {
    backupDeleting.value = null
  }
}

function openRename(name: string) {
  renamingBackup.value = name
  renameInput.value = name
  showRename.value = true
}

async function submitRename() {
  const newName = renameInput.value.trim()
  if (!newName) {
    message.warning('请输入新文件名')
    return
  }
  if (!/\.zip$/i.test(newName) || /[/\\]/.test(newName) || newName.startsWith('.')) {
    message.error('文件名必须以 .zip 结尾，且不含路径分隔符、不能以点开头')
    return
  }
  renameSaving.value = true
  try {
    const r = await api.renameBackup(renamingBackup.value, newName)
    message.success(`已重命名为 ${r.name}`)
    showRename.value = false
    await loadBackups()
  } catch (e) {
    message.error(errText(e))
  } finally {
    renameSaving.value = false
  }
}

const backupColumns = computed<DataTableColumns<BackupInfo>>(() => [
  { title: '文件名', key: 'name' },
  {
    title: '大小',
    key: 'size',
    render: (r) => `${(r.size / 1024).toFixed(1)} KB`,
  },
  {
    title: '创建时间',
    key: 'created_at',
    render: (r) => formatDateTime(r.created_at),
  },
  {
    title: '操作',
    key: 'actions',
    render: (r) =>
      h(NSpace, { size: 4 }, {
        default: () => [
          h(
            NButton,
            {
              size: 'tiny',
              secondary: true,
              onClick: () => {
                restoringBackup.value = r.name
                showRestore.value = true
              },
            },
            { default: () => '恢复' },
          ),
          h(
            NButton,
            { size: 'tiny', secondary: true, onClick: () => downloadBackup(r.name) },
            { default: () => '下载' },
          ),
          h(
            NButton,
            { size: 'tiny', secondary: true, onClick: () => openRename(r.name) },
            { default: () => '重命名' },
          ),
          h(
            NPopconfirm,
            {
              positiveButtonProps: { type: 'error' },
              onPositiveClick: () => removeBackup(r.name),
            },
            {
              trigger: () =>
                h(
                  NButton,
                  {
                    size: 'tiny',
                    type: 'error',
                    secondary: true,
                    loading: backupDeleting.value === r.name,
                  },
                  { default: () => '删除' },
                ),
              default: () => `确认删除备份 ${r.name}？`,
            },
          ),
        ],
      }),
  },
])
const iconFileInput = ref<HTMLInputElement | null>(null)
// 预览加载失败（非法 URL）时回退默认图标
const previewBroken = ref(false)
watch(brandIconInput, () => {
  previewBroken.value = false
})

// 本地上传图标：转 base64 data URI 填入输入框（预览后保存）；限 1MB（后端字段上限 2M）
const ICON_FILE_MAX = 1 * 1024 * 1024

function pickIconFile() {
  iconFileInput.value?.click()
}

function onIconFile(ev: Event) {
  const input = ev.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  if (file.size > ICON_FILE_MAX) {
    message.warning('图片超过 1MB，请压缩后重试')
    input.value = ''
    return
  }
  const reader = new FileReader()
  reader.onload = () => {
    brandIconInput.value = String(reader.result ?? '')
    message.info('已载入图片，保存后生效')
  }
  reader.readAsDataURL(file)
  input.value = '' // 允许重复选择同一文件
}

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
const logLevel = ref<string[]>([])
const logStart = ref<number | null>(null)
const logEnd = ref<number | null>(null)
const logSource = ref<string[]>([])
const logSourceOptions = ref<string[]>([])
const logPage = ref(1)
const logTableMaxHeight = ref(420)
const logData = ref<{ results: LogEntry[]; total: number; page_size: number; pages: number }>({
  results: [],
  total: 0,
  page_size: 100,
  pages: 0,
})

// 弹窗可拖拽调整大小：拖拽会给 modal 设置内联高度，此时用 ResizeObserver 联动
// 表格高度（减去筛选区/分页区等固定部分）。modal 高度 auto（内容驱动）时不联动，
// 否则表格高度反作用于内容形成正反馈循环。
let logResizeObserver: ResizeObserver | null = null
let logPollTimer: number | null = null
const LOG_POLL_INTERVAL = 15_000
watch(showLogs, async (v) => {
  if (!v) {
    // 关闭时停止自动刷新
    if (logPollTimer != null) {
      window.clearInterval(logPollTimer)
      logPollTimer = null
    }
    return
  }
  // 弹窗打开期间每 15s 静默刷新，持续追踪最新日志（保持当前筛选与页码）
  if (logPollTimer == null) {
    logPollTimer = window.setInterval(() => {
      if (showLogs.value) void fetchLogs(true)
    }, LOG_POLL_INTERVAL)
  }
  await nextTick()
  logResizeObserver?.disconnect()
  const modal = document.querySelector<HTMLElement>('.n-modal')
  if (modal) {
    logResizeObserver = new ResizeObserver((entries) => {
      if (!modal.style.height) return
      const h = entries[0].contentRect.height
      logTableMaxHeight.value = Math.max(180, Math.round(h - 210))
    })
    logResizeObserver.observe(modal)
  }
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
  {
    title: '来源',
    key: 'source',
    width: 160,
    render: (row) => row.source ?? row.name,
  },
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
  void loadLogSources()
}

function resetLogFilters() {
  logLevel.value = []
  logSource.value = []
  logStart.value = null
  logEnd.value = null
  logPage.value = 1
  fetchLogs()
}

async function loadLogSources() {
  try {
    const data = await api.logSources()
    logSourceOptions.value = data.sources
  } catch {
    /* 401 由 client 统一跳转 */
  }
}

async function fetchLogs(silent = false) {
  // 后台轮询（silent）不触发 loading，避免表格每 15s 闪烁
  if (!silent) logLoading.value = true
  try {
    logData.value = await api.queryLogs({
      level: multi(logLevel.value),
      start: toLogTs(logStart.value),
      end: toLogTs(logEnd.value),
      source: multi(logSource.value),
      page: logPage.value,
      page_size: 100,
    })
  } catch (e) {
    message.error(errText(e))
  } finally {
    if (!silent) logLoading.value = false
  }
}

async function exportLogs() {
  logExporting.value = true
  try {
    await api.exportLogs({
      level: multi(logLevel.value),
      start: toLogTs(logStart.value),
      end: toLogTs(logEnd.value),
      source: multi(logSource.value),
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

// 多选值可能是数组或 null（naive-ui clear 时 emit null）
function multi(v: unknown): string | undefined {
  return Array.isArray(v) && v.length ? v.join(',') : undefined
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

async function loadStats() {
  try {
    const s = await api.stats()
    const map: Record<string, TargetStatus> = {}
    for (const t of s.target_status) map[t.target_id] = t
    targetStatus.value = map
  } catch {
    /* 401 由 client 处理 */
  }
}

async function loadAppSettings() {
  try {
    appSettings.value = await api.getAppSettings()
    brandIconInput.value = appSettings.value.brand_icon ?? ''
  } catch {
    /* 401 由 client 处理 */
  }
}

async function saveBrandIcon() {
  const icon = brandIconInput.value.trim()
  if (!icon) {
    message.error('请先输入图标 URL 或 base64 data URI')
    return
  }
  brandSaving.value = true
  try {
    const saved = await api.updateAppSettings({ ...appSettings.value, brand_icon: icon })
    appSettings.value = saved
    // base64 已由后端转存为服务器文件，输入框显示文件 URL（所见即所存）
    brandIconInput.value = saved.brand_icon ?? ''
    window.dispatchEvent(new Event('cc-brand-icon-changed'))
    message.success('品牌图标已保存')
  } catch (e) {
    message.error(errText(e))
  } finally {
    brandSaving.value = false
  }
}

async function clearBrandIcon() {
  brandSaving.value = true
  try {
    appSettings.value = await api.updateAppSettings({ ...appSettings.value, brand_icon: null })
    brandIconInput.value = ''
    window.dispatchEvent(new Event('cc-brand-icon-changed'))
    message.success('已恢复默认图标')
  } catch (e) {
    message.error(errText(e))
  } finally {
    brandSaving.value = false
  }
}

async function saveAppSettings() {
  const needsS3 =
    appSettings.value.log_cleanup_mode === 'upload' ||
    appSettings.value.storage_mode === 'both' ||
    appSettings.value.storage_mode === 's3'
  if (needsS3 && !s3Ready.value) {
    message.error('日志保留/记录存储模式依赖 S3，请先在「S3 存储配置」中完成配置（含凭据）')
    return
  }
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
  if (!url) {
    message.warning('请先填写 Webhook 地址')
    return
  }
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

async function loadS3() {
  try {
    s3.value = await api.getS3Config()
  } catch {
    /* 401 由 client 处理 */
  }
}

// 令牌明文（后端回读明文）；默认掩码显示，眼睛图标切换明文
const apiTokenSet = ref(false)

async function loadApiToken() {
  try {
    const info = await api.getApiToken()
    apiToken.value = info.token
    apiTokenSet.value = info.has_token
  } catch {
    /* 401 由 client 处理 */
  }
}

async function regenerateToken() {
  try {
    apiToken.value = (await api.generateApiToken()).token
    apiTokenSet.value = true
    message.success('已生成新令牌，旧令牌立即失效')
  } catch (e) {
    message.error(errText(e))
  }
}

async function removeToken() {
  try {
    await api.deleteApiToken()
    apiToken.value = null
    apiTokenSet.value = false
    message.success('已删除 API 令牌')
  } catch (e) {
    message.error(errText(e))
  }
}

async function copyToken() {
  if (!apiToken.value) return
  const ok = await copyText(apiToken.value)
  if (ok) message.success('已复制到剪贴板')
  else message.warning('浏览器限制自动复制，请手动选中复制')
}

async function s3Payload(): Promise<S3ConfigInput> {
  return {
    enabled: s3.value.enabled,
    endpoint: s3.value.endpoint.trim(),
    bucket: s3.value.bucket.trim(),
    region: s3.value.region?.trim() || null,
    datapath: s3.value.datapath.trim(),
    access_id: s3Credentials.value.access_id.trim() || null,
    access_key: s3Credentials.value.access_key || null,
  }
}

async function saveS3() {
  s3Saving.value = true
  try {
    s3.value = await api.updateS3Config(await s3Payload())
    s3Credentials.value = { access_id: '', access_key: '' }
    message.success('S3 配置已保存')
  } catch (e) {
    message.error(errText(e))
  } finally {
    s3Saving.value = false
  }
}

async function clearS3Credentials() {
  try {
    // 传空字符串显式清除已保存凭据（null 语义是不修改）
    const payload = await s3Payload()
    s3.value = await api.updateS3Config({ ...payload, access_id: '', access_key: '' })
    s3Credentials.value = { access_id: '', access_key: '' }
    message.success('S3 凭据已清除，S3 功能停用')
  } catch (e) {
    message.error(errText(e))
  }
}

async function testS3() {
  s3Testing.value = true
  try {
    const r = await api.testS3(await s3Payload())
    message.success(r.info)
  } catch (e) {
    message.error(errText(e))
  } finally {
    s3Testing.value = false
  }
}

// --- SSE 实时状态：检查结果到达时局部更新「最近状态」列，节流兜底全量刷新 ---
let es: EventSource | null = null
let lastStatsRefresh = 0
const STATS_REFRESH_THROTTLE = 10_000

function onSseResult(ev: Event) {
  try {
    const r = JSON.parse((ev as MessageEvent).data) as CheckResult
    const cur = targetStatus.value[r.target_id]
    if (cur) {
      cur.last_status = r.status
      cur.last_latency_ms = r.latency_ms
      cur.last_checked_at = r.checked_at
      cur.last_message = r.message
    }
  } catch {
    /* 解析失败仅跳过局部更新 */
  }
  const now = Date.now()
  if (now - lastStatsRefresh >= STATS_REFRESH_THROTTLE) {
    lastStatsRefresh = now
    void loadStats()
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
  load()
  loadStats()
  loadAppSettings()
  loadWebhook()
  loadS3()
  loadApiToken()
  connectSse()
})

onUnmounted(() => {
  es?.close()
})

function openCreate() {
  editing.value = null
  modalShow.value = true
}

function openEdit(t: Target) {
  editing.value = t
  modalShow.value = true
}

// 复制目标：同一份参数创建新目标（名称加「副本」后缀，新 id 由后端生成）
async function duplicate(t: Target) {
  const { id: _id, created_at: _created, updated_at: _updated, ...rest } = t
  try {
    await api.createTarget({
      ...rest,
      name: t.name ? `${t.name}（副本）` : null,
    })
    message.success('已复制为新目标')
    await load()
  } catch (e) {
    message.error(errText(e))
  }
}

const modalSaving = ref(false)

async function save(payload: TargetInput) {
  modalSaving.value = true
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
  } finally {
    modalSaving.value = false
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

const statusLabels: Record<string, string> = { success: '成功', fail: '失败', timeout: '超时', error: '错误' }

const statusTag: Record<string, { type: 'success' | 'error' | 'warning' | 'default'; label: string }> = {
  success: { type: 'success', label: '成功' },
  fail: { type: 'error', label: '失败' },
  timeout: { type: 'warning', label: '超时' },
  error: { type: 'default', label: '错误' },
}

// 正在手动检查的目标集合，防止重复点击触发多次检查
const runningIds = ref<Set<string>>(new Set())

async function runOne(t: Target) {
  if (runningIds.value.has(t.id)) return
  runningIds.value.add(t.id)
  try {
    const r = await api.runChecks(t.id)
    const status = r[0]?.status
    const text = `检查完成：${statusLabels[status ?? ''] ?? '完成'}`
    if (status === 'fail' || status === 'error') message.error(text)
    else if (status === 'timeout') message.warning(text)
    else message.success(text)
    await loadStats()
  } catch (e) {
    message.error(errText(e))
  } finally {
    runningIds.value.delete(t.id)
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
    title: '最近状态',
    key: 'last_status',
    width: 150,
    render: (t) => {
      const s = targetStatus.value[t.id]
      const status = s?.last_status
      if (!status) return h('span', { class: 'dim' }, '—')
      return h(NSpace, { size: 4, align: 'center' }, () => [
        h(
          NTag,
          {
            size: 'small',
            bordered: false,
            type: statusTag[status].type,
            title: s.last_checked_at ? `最近检查：${formatDateTime(s.last_checked_at)}` : undefined,
          },
          { default: () => statusTag[status].label },
        ),
        s.last_latency_ms != null
          ? h(
              'span',
              {
                class:
                  s.last_latency_ms >= 1000
                    ? 'lat-bad'
                    : s.last_latency_ms >= 500
                      ? 'lat-warn'
                      : 'dim',
              },
              `${s.last_latency_ms}ms`,
            )
          : null,
      ])
    },
  },
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
    render: (t) =>
      t.time_ranges.length
        ? t.time_ranges.map((r) => `${r.start}–${r.end}`).join(', ')
        : '全天',
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
    width: 280,
    render: (t) =>
      h(NSpace, { size: 4 }, () => [
        t.enabled
          ? h(
              NButton,
              {
                size: 'tiny',
                secondary: true,
                type: 'primary',
                loading: runningIds.value.has(t.id),
                onClick: () => runOne(t),
              },
              { default: () => '检查' },
            )
          : null,
        h(
          NButton,
          { size: 'tiny', secondary: true, onClick: () => openEdit(t) },
          { default: () => '编辑' },
        ),
        h(
          NButton,
          { size: 'tiny', secondary: true, onClick: () => duplicate(t) },
          { default: () => '复制' },
        ),
        h(
          NPopconfirm,
          { onPositiveClick: () => remove(t.id), positiveButtonProps: { type: 'error' } },
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
        <div class="brand">
          <BrandLogo />
          <span>配置管理</span>
        </div>
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
              <span class="label">统计窗口(次)</span>
              <n-input-number v-model:value="appSettings.stats_window" :min="10" :max="10000" style="width: 180px" />
              <span class="hint">仪表盘「成功/失败/超时/错误」统计的近 N 次检查记录</span>
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
            <n-space align="center" :size="12" wrap>
              <span class="label">日志保留模式</span>
              <n-select
                v-model:value="appSettings.log_cleanup_mode"
                :options="logCleanupOptions"
                style="width: 140px"
              />
              <span class="hint">delete=删除 n 天前日志 / upload=上传 S3 后删本地（需先配置 S3）/ none=不清理</span>
            </n-space>
            <n-space align="center" :size="12" wrap>
              <span class="label">日志保留天数</span>
              <n-input-number
                v-model:value="appSettings.log_retention_days"
                :min="1"
                :max="3650"
                style="width: 180px"
              />
            </n-space>
            <n-space align="center" :size="12" wrap>
              <span class="label">记录存储模式</span>
              <n-select
                v-model:value="appSettings.storage_mode"
                :options="storageModeOptions"
                style="width: 180px"
              />
              <span class="hint">仅 S3 / 双写需先配置 S3；S3 上按天对象永久保留</span>
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
              <n-input
                v-model:value="webhookUrl"
                placeholder="https://gotify.example.com/message?token=..."
                :maxlength="500"
                clearable
              />
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

          <n-card title="S3 存储配置" size="small">
          <n-space vertical size="large">
            <n-space align="center" :size="12">
              <span>启用 S3</span>
              <n-switch v-model:value="s3.enabled" />
              <span class="hint">检查记录/日志的 S3 兼容存储；启用前需填写 endpoint/bucket/数据路径与凭据</span>
            </n-space>
            <n-space align="center" :size="12" wrap>
              <span class="label">Endpoint</span>
              <n-input
                v-model:value="s3.endpoint"
                placeholder="https://s3.example.com"
                :maxlength="500"
                clearable
                style="width: 300px"
              />
            </n-space>
            <n-space align="center" :size="12" wrap>
              <span class="label">Bucket</span>
              <n-input
                v-model:value="s3.bucket"
                placeholder="存储桶名称"
                :maxlength="255"
                clearable
                style="width: 200px"
              />
              <span class="label">Region（可选）</span>
              <n-input v-model:value="s3.region" placeholder="部分服务要求" clearable style="width: 150px" />
            </n-space>
            <n-space align="center" :size="12" wrap>
              <span class="label">数据路径</span>
              <n-input
                v-model:value="s3.datapath"
                placeholder="如 connection-checker/，数据在 bucket 中的路径前缀"
                :maxlength="500"
                clearable
                style="width: 300px"
              />
            </n-space>
            <n-space align="center" :size="12" wrap>
              <span class="label">Access ID</span>
              <n-input v-model:value="s3Credentials.access_id" placeholder="留空则不修改" clearable style="width: 300px" />
            </n-space>
            <n-space align="center" :size="12" wrap>
              <span class="label">Access Key</span>
              <n-input
                v-model:value="s3Credentials.access_key"
                type="password"
                show-password-on="click"
                placeholder="留空则不修改"
                clearable
                style="width: 300px"
              />
            </n-space>
            <n-space align="end" :size="12">
              <span v-if="s3.enabled && !s3.has_credentials" class="hint">尚未配置凭据，S3 功能不可用</span>
              <n-button :loading="s3Testing" @click="testS3">测试连接</n-button>
              <n-button type="primary" :loading="s3Saving" @click="saveS3">保存 S3 配置</n-button>
              <n-popconfirm
                v-if="s3.has_credentials"
                :positive-button-props="{ type: 'error' }"
                @positive-click="clearS3Credentials"
              >
                <template #trigger>
                  <n-button type="error" secondary>清除凭据</n-button>
                </template>
                确认清除已保存的 S3 凭据？S3 功能将立即停用
              </n-popconfirm>
            </n-space>
          </n-space>
          </n-card>

          <n-card title="API 访问令牌" size="small">
          <n-space vertical size="large">
            <n-space align="center" :size="12" wrap>
              <span class="label">令牌</span>
              <n-input
                v-if="apiToken"
                :value="apiToken"
                readonly
                type="password"
                show-password-on="click"
                style="width: 340px"
              />
              <span v-else class="hint">未设置 API 令牌，外部 API 调用将被拒绝</span>
              <n-button v-if="apiToken" size="small" @click="copyToken">复制</n-button>
              <n-popconfirm v-if="apiTokenSet" :positive-button-props="{ type: 'error' }" @positive-click="removeToken">
                <template #trigger>
                  <n-button size="small" type="error" secondary>删除</n-button>
                </template>
                删除后外部 API 调用立即失效，确认删除？
              </n-popconfirm>
            </n-space>
            <n-space align="center" :size="12" wrap>
              <n-popconfirm @positive-click="regenerateToken">
                <template #trigger>
                  <n-button size="small" secondary>重新生成</n-button>
                </template>
                重新生成后旧令牌立即失效，确认？
              </n-popconfirm>
              <span class="hint">外部调用携带请求头 Authorization: Bearer &lt;token&gt;；令牌存于 secrets.json</span>
            </n-space>
          </n-space>
          </n-card>

          <n-card title="品牌图标" size="small">
          <n-space vertical size="large">
            <n-space align="center" :size="12" wrap>
              <img
                :src="previewBroken ? '/favicon.svg' : brandIconInput || '/favicon.svg'"
                alt="图标预览"
                class="brand-preview"
                @error="previewBroken = true"
              />
              <span class="hint">预览；必须是正方形（PNG/JPEG/GIF/WebP/SVG），不符合将被拒绝保存</span>
            </n-space>
            <n-space align="center" :size="12" wrap>
              <span class="label">图标</span>
              <n-input
                v-model:value="brandIconInput"
                placeholder="图片 URL 或 base64 data URI；base64 将转存为服务器文件（限 1MB）"
                :maxlength="2000000"
                clearable
                style="width: 420px"
              />
              <n-button size="small" secondary @click="pickIconFile">上传图片</n-button>
              <input
                ref="iconFileInput"
                type="file"
                accept="image/*"
                class="hidden-file"
                @change="onIconFile"
              />
            </n-space>
            <n-space align="end">
              <n-button :loading="brandSaving" type="primary" @click="saveBrandIcon">保存图标</n-button>
              <n-button v-if="appSettings.brand_icon" :loading="brandSaving" @click="clearBrandIcon">恢复默认</n-button>
            </n-space>
          </n-space>
          </n-card>

          <n-card title="数据管理" size="small">
            <n-space vertical size="large">
              <n-space align="center" :size="12" wrap>
                <n-button secondary @click="exportData">导出数据</n-button>
                <n-button secondary @click="showImport = true">导入数据</n-button>
                <n-button secondary @click="openBackups">备份管理</n-button>
              </n-space>
              <span class="hint">
                导出/备份打包 config、检查记录与日志（不含密钥）；导入/恢复按内容勾选（可多选），
                操作前自动备份当前数据
              </span>
            </n-space>
          </n-card>

        </n-space>
      </div>
    </n-layout-content>
    <AppFooter />
  </n-layout>

  <DataImportDialog
    :show="showImport"
    mode="import"
    :loading="dataBusy"
    @update:show="(v: boolean) => (showImport = v)"
    @confirm="onImportConfirm"
  />
  <DataImportDialog
    :show="showRestore"
    mode="restore"
    :backup-name="restoringBackup"
    :loading="dataBusy"
    @update:show="(v: boolean) => (showRestore = v)"
    @confirm="onRestoreConfirm"
  />
  <n-modal v-model:show="showBackups">
    <n-card
      style="width: 640px; max-width: 94vw"
      title="备份管理"
      :bordered="false"
      size="huge"
      role="dialog"
      aria-modal="true"
      closable
      @close="showBackups = false"
    >
      <n-space vertical size="large">
        <n-space justify="space-between" align="center" wrap>
          <span class="hint">备份存于服务器 data/backups/，全部保留、手动删除</span>
          <n-button size="small" type="primary" :loading="backupCreating" @click="createBackup">
            创建备份
          </n-button>
        </n-space>
        <n-empty v-if="!backupsLoading && !backups.length" description="暂无备份" />
        <n-data-table
          v-else
          :columns="backupColumns"
          :data="backups"
          :loading="backupsLoading"
          size="small"
        />
      </n-space>
    </n-card>
  </n-modal>

  <n-modal v-model:show="showRename">
    <n-card
      style="width: 420px; max-width: 94vw"
      title="重命名备份"
      :bordered="false"
      size="huge"
      role="dialog"
      aria-modal="true"
      closable
      @close="showRename = false"
    >
      <n-space vertical size="large">
        <span class="hint">原文件名：{{ renamingBackup }}</span>
        <n-input
          v-model:value="renameInput"
          placeholder="新文件名（.zip 结尾）"
          :maxlength="255"
          @keydown.enter="submitRename"
        />
        <n-space justify="end">
          <n-button @click="showRename = false">取消</n-button>
          <n-button type="primary" :loading="renameSaving" @click="submitRename">确定</n-button>
        </n-space>
      </n-space>
    </n-card>
  </n-modal>

  <TargetFormModal
    v-model:show="modalShow"
    :target="editing"
    :saving="modalSaving"
    @save="save"
  />

  <n-modal
    v-model:show="showLogs"
    preset="card"
    title="日志管理"
    style="width: 900px; max-width: 96vw; resize: both; overflow: auto"
  >
    <n-space vertical :size="12">
      <n-space align="center" :size="12" wrap>
        <span class="label">级别</span>
        <n-select
          v-model:value="logLevel"
          :options="logLevelOptions"
          multiple
          clearable
          placeholder="级别"
          style="width: 150px"
        />
        <n-select
          v-model:value="logSource"
          :options="logSourceOptions.map((s) => ({ label: s, value: s }))"
          placeholder="来源文件/模块"
          multiple
          clearable
          filterable
          :menu-props="{ class: 'wide-popup' }"
          style="width: 240px"
        />
        <n-date-picker v-model:value="logStart" type="datetime" clearable style="width: 190px" placeholder="起始时间" />
        <n-date-picker v-model:value="logEnd" type="datetime" clearable style="width: 190px" placeholder="结束时间" />
        <n-button size="small" type="primary" :loading="logLoading" @click="() => fetchLogs()">查询</n-button>
        <n-button size="small" quaternary @click="resetLogFilters">重置</n-button>
        <n-button size="small" :loading="logExporting" @click="exportLogs">导出</n-button>
      </n-space>
      <n-data-table
        :columns="logColumns"
        :data="logData.results"
        :loading="logLoading"
        :max-height="logTableMaxHeight"
        size="small"
      />
      <n-space align="center" justify="space-between" :size="12">
        <span class="hint">共 {{ logData.total.toLocaleString() }} 条；时间为服务器本地时区</span>
        <n-pagination
          v-model:page="logPage"
          :page-count="logData.pages || 1"
          :page-size="logData.page_size"
          @update:page="() => fetchLogs()"
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
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 18px;
  font-weight: 600;
  white-space: nowrap;
}
.brand-preview {
  width: 48px;
  height: 48px;
  object-fit: contain;
  border: 1px solid var(--cc-panel-border);
  border-radius: 6px;
  flex-shrink: 0;
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
.dim {
  color: var(--cc-text-3);
  font-size: 12px;
  white-space: nowrap;
}
.hidden-file {
  display: none;
}
.lat-warn {
  color: #fab219;
  font-size: 12px;
  white-space: nowrap;
}
.lat-bad {
  color: #d03b3b;
  font-size: 12px;
  white-space: nowrap;
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
