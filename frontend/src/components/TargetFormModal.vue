<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import {
  NButton,
  NCard,
  NForm,
  NFormItem,
  NInput,
  NInputNumber,
  NModal,
  NSelect,
  NSpace,
  NSwitch,
  NTimePicker,
  useMessage,
} from 'naive-ui'

import { copyText } from '@/composables/useClipboard'
import type { CheckMethod, Target, TargetInput, TimeRange } from '@/types'

const props = defineProps<{ show: boolean; target: Target | null; saving?: boolean }>()
const emit = defineEmits<{
  'update:show': [value: boolean]
  save: [payload: TargetInput]
}>()

const message = useMessage()
const saving = ref(false)

const form = reactive({
  name: '',
  ip: '',
  check_method: 'ping' as CheckMethod,
  check_interval: 60,
  enabled: true,
  notify_enabled: true,
  ping_count: null as number | null,
  port: null as number | null,
  scheme: 'http' as 'http' | 'https',
  url_path: '/',
  http_codes_text: '',
  timeout: null as number | null,
  time_ranges: [{ start: '00:00', end: '23:59' }] as TimeRange[],
})

const methodOptions = [
  { label: 'Ping', value: 'ping' },
  { label: 'TCP 端口', value: 'port' },
  { label: 'HTTP(S)', value: 'http' },
  { label: 'DNS 解析', value: 'dns' },
]
const schemeOptions = [
  { label: 'http', value: 'http' },
  { label: 'https', value: 'https' },
]

// 常用检查间隔快捷选择
const intervalOptions = [
  { label: '30s', value: 30 },
  { label: '1m', value: 60 },
  { label: '5m', value: 300 },
  { label: '15m', value: 900 },
  { label: '1h', value: 3600 },
]

// 常用端口与超时快捷选择
const portOptions = [80, 443, 22, 8080, 3306, 5432]
const timeoutOptions = [1, 3, 5, 10]

// 常用期望状态码快捷选择（空值 = 用默认 200-399）
const codeOptions = [
  { label: '200', value: '200' },
  { label: '200,204', value: '200,204' },
  { label: '200-299', value: '200,201,202,203,204,205,206,207,208,226' },
  { label: '301,302', value: '301,302' },
  { label: '默认', value: '' },
]

watch(
  () => [props.show, props.target],
  () => {
    if (!props.show) return
    const t = props.target
    form.name = t?.name ?? ''
    form.ip = t?.ip ?? ''
    form.check_method = t?.check_method ?? 'ping'
    form.check_interval = t?.check_interval ?? 60
    form.enabled = t?.enabled ?? true
    form.notify_enabled = t?.notify_enabled ?? true
    form.ping_count = t?.ping_count ?? null
    form.port = t?.port ?? null
    form.scheme = t?.scheme ?? 'http'
    form.url_path = t?.url_path ?? '/'
    form.http_codes_text = t?.http_success_codes?.join(',') ?? ''
    form.timeout = t?.timeout ?? null
    form.time_ranges =
      t && t.time_ranges.length ? t.time_ranges.map((r) => ({ ...r })) : [{ start: '00:00', end: '23:59' }]
  },
)

function addRange() {
  form.time_ranges.push({ start: '00:00', end: '23:59' })
}

function removeRange(index: number) {
  form.time_ranges.splice(index, 1)
}

function parseCodes(text: string): number[] | null {
  const codes = text
    .split(',')
    .map((s) => Number(s.trim()))
    .filter((n) => Number.isInteger(n) && n >= 100 && n <= 599)
  return codes.length ? [...new Set(codes)] : null
}

function validate(): string | null {
  if (!form.name?.trim() && !form.ip.trim()) return '请填写名称或 IP'
  if (!form.ip.trim()) return '请填写 IP 或主机名'
  if (form.check_method === 'port' && !form.port) return '端口检查需要填写端口'
  if (form.check_method === 'http' && form.http_codes_text.trim()) {
    const parts = form.http_codes_text
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean)
    const invalid = parts.filter(
      (p) => !/^\d{3}$/.test(p) || Number(p) < 100 || Number(p) > 599,
    )
    if (invalid.length) {
      return `期望状态码包含无效值：${invalid.join(', ')}（应为 100-599 的数字，逗号分隔）`
    }
  }
  if (form.time_ranges.some((r) => !r.start || !r.end)) return '时间窗口的开始/结束时间不能为空'
  return null
}

async function copyId() {
  if (!props.target) return
  const ok = await copyText(props.target.id)
  if (ok) message.success('目标 ID 已复制')
  else message.warning('浏览器限制自动复制，请手动选中复制')
}

function submit() {
  if (saving.value) return
  const err = validate()
  if (err) {
    message.error(err)
    return
  }
  saving.value = true
  const payload: TargetInput = {
    name: form.name.trim() || null,
    ip: form.ip.trim(),
    check_method: form.check_method,
    check_interval: form.check_interval,
    enabled: form.enabled,
    notify_enabled: form.notify_enabled,
    time_ranges: form.time_ranges.length ? form.time_ranges : [{ start: '00:00', end: '23:59' }],
    ping_count: form.check_method === 'ping' ? form.ping_count : null,
    port: form.check_method === 'ping' ? null : form.port,
    scheme: form.scheme,
    url_path: form.check_method === 'http' ? form.url_path : '/',
    http_success_codes: form.check_method === 'http' ? parseCodes(form.http_codes_text) : null,
    timeout: form.timeout,
  }
  emit('save', payload)
  saving.value = false
}
</script>

<template>
  <n-modal
    :show="show"
    :mask-closable="false"
    @update:show="(v: boolean) => emit('update:show', v)"
  >
    <n-card
      style="width: 560px; max-width: 94vw"
      :title="target ? `编辑目标：${target.name || target.ip}` : '新增目标'"
      :bordered="false"
      size="huge"
      role="dialog"
      aria-modal="true"
      closable
      @close="emit('update:show', false)"
    >
      <n-form label-placement="left" label-width="90">
        <n-form-item v-if="target" label="目标 ID">
          <n-space align="center" style="width: 100%">
            <n-input :value="target.id" disabled />
            <n-button size="small" secondary @click="copyId">复制</n-button>
          </n-space>
        </n-form-item>
        <n-form-item label="名称">
          <n-input v-model:value="form.name" placeholder="可选，便于识别" :maxlength="100" />
        </n-form-item>
        <n-form-item label="IP / 主机名" required>
          <n-input
            v-model:value="form.ip"
            placeholder="如 8.8.8.8 或 example.com"
            :maxlength="255"
          />
        </n-form-item>
        <n-form-item label="检查方式" required>
          <n-select v-model:value="form.check_method" :options="methodOptions" />
        </n-form-item>

        <template v-if="form.check_method === 'ping'">
          <n-form-item label="发包数">
            <n-input-number
              v-model:value="form.ping_count"
              :min="1"
              :max="20"
              :show-button="false"
              style="width: 100%"
              placeholder="留空用全局默认"
            />
          </n-form-item>
        </template>

        <template v-if="form.check_method === 'port'">
          <n-form-item label="端口" required>
            <n-space vertical style="width: 100%">
              <n-input-number v-model:value="form.port" :min="1" :max="65535" style="width: 100%" />
              <n-space :size="4" wrap>
                <n-button
                  v-for="p in portOptions"
                  :key="p"
                  size="tiny"
                  secondary
                  :type="form.port === p ? 'primary' : 'default'"
                  @click="form.port = p"
                >
                  {{ p }}
                </n-button>
              </n-space>
            </n-space>
          </n-form-item>
        </template>

        <template v-if="form.check_method === 'http'">
          <n-form-item label="协议">
            <n-select v-model:value="form.scheme" :options="schemeOptions" />
          </n-form-item>
          <n-form-item label="端口">
            <n-space vertical style="width: 100%">
              <n-input-number
                v-model:value="form.port"
                :min="1"
                :max="65535"
                :show-button="false"
                style="width: 100%"
                placeholder="留空用协议默认（80/443）"
              />
              <n-space :size="4" wrap>
                <n-button
                  v-for="p in portOptions"
                  :key="p"
                  size="tiny"
                  secondary
                  :type="form.port === p ? 'primary' : 'default'"
                  @click="form.port = p"
                >
                  {{ p }}
                </n-button>
              </n-space>
            </n-space>
          </n-form-item>
          <n-form-item label="路径">
            <n-input v-model:value="form.url_path" placeholder="/" />
          </n-form-item>
          <n-form-item label="期望状态码">
            <n-space vertical style="width: 100%">
              <n-input
                v-model:value="form.http_codes_text"
                placeholder="逗号分隔，如 200,201,204；留空用默认（200-399）"
              />
              <n-space :size="4" wrap>
                <n-button
                  v-for="opt in codeOptions"
                  :key="opt.label"
                  size="tiny"
                  secondary
                  :type="form.http_codes_text === opt.value ? 'primary' : 'default'"
                  @click="form.http_codes_text = opt.value"
                >
                  {{ opt.label }}
                </n-button>
              </n-space>
            </n-space>
          </n-form-item>
        </template>

        <n-form-item label="间隔(秒)" required>
          <n-space vertical style="width: 100%">
            <n-input-number v-model:value="form.check_interval" :min="0" :step="5" style="width: 100%" />
            <n-space :size="4" wrap>
              <n-button
                v-for="opt in intervalOptions"
                :key="opt.value"
                size="tiny"
                secondary
                :type="form.check_interval === opt.value ? 'primary' : 'default'"
                @click="form.check_interval = opt.value"
              >
                {{ opt.label }}
              </n-button>
            </n-space>
            <span class="hint">0 = 关闭定时检查，仅手动触发</span>
          </n-space>
        </n-form-item>
        <n-form-item label="超时(秒)">
          <n-space vertical style="width: 100%">
            <n-input-number v-model:value="form.timeout" :min="0.1" :step="0.5" :show-button="false" style="width: 100%" placeholder="留空用默认值" />
            <n-space :size="4" wrap>
              <n-button
                v-for="t in timeoutOptions"
                :key="t"
                size="tiny"
                secondary
                :type="form.timeout === t ? 'primary' : 'default'"
                @click="form.timeout = t"
              >
                {{ t }}s
              </n-button>
            </n-space>
          </n-space>
        </n-form-item>
        <n-form-item label="启用">
          <n-switch v-model:value="form.enabled" />
        </n-form-item>
        <n-form-item label="告警推送">
          <n-space vertical style="width: 100%">
            <n-switch v-model:value="form.notify_enabled" />
            <span class="hint">关闭后该目标不推送告警与恢复通知</span>
          </n-space>
        </n-form-item>

        <n-form-item label="时间窗口">
          <n-space vertical style="width: 100%">
            <div
              v-for="(range, idx) in form.time_ranges"
              :key="idx"
              class="range-row"
            >
              <n-time-picker
                :formatted-value="range.start"
                format="HH:mm"
                value-format="HH:mm"
                placeholder="开始"
                @update:formatted-value="(v: string | null) => (range.start = v ?? '')"
              />
              <span class="sep">—</span>
              <n-time-picker
                :formatted-value="range.end"
                format="HH:mm"
                value-format="HH:mm"
                placeholder="结束"
                @update:formatted-value="(v: string | null) => (range.end = v ?? '')"
              />
              <n-button size="small" quaternary type="error" :disabled="form.time_ranges.length <= 1" @click="removeRange(idx)">
                删除
              </n-button>
            </div>
            <n-button size="small" dashed @click="addRange">添加时间段</n-button>
            <span class="hint">跨午夜（如 22:00–06:00）同样支持</span>
          </n-space>
        </n-form-item>
      </n-form>

      <template #footer>
        <n-space justify="end">
          <n-button @click="emit('update:show', false)">取消</n-button>
          <n-button type="primary" :loading="saving || props.saving" @click="submit">保存</n-button>
        </n-space>
      </template>
    </n-card>
  </n-modal>
</template>

<style scoped>
.range-row {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
}
.sep {
  color: var(--cc-text-3);
}
.hint {
  font-size: 12px;
  color: var(--cc-text-3);
}
</style>
