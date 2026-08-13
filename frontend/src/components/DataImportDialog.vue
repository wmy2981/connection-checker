<script setup lang="ts">
import { ref, watch } from 'vue'
import { NButton, NCard, NCheckbox, NModal, NSpace, useMessage } from 'naive-ui'

const props = defineProps<{
  show: boolean
  mode: 'import' | 'restore'
  backupName?: string | null
  loading?: boolean
}>()

const emit = defineEmits<{
  (e: 'update:show', v: boolean): void
  (
    e: 'confirm',
    payload: {
      file?: File
      include_records: boolean
      include_targets: boolean
      include_settings: boolean
    },
  ): void
}>()

const message = useMessage()

const fileInput = ref<HTMLInputElement | null>(null)
const file = ref<File | null>(null)
const includeRecords = ref(true)
const includeTargets = ref(true)
const includeSettings = ref(true)

// 关闭后重置文件选择与勾选状态
watch(
  () => props.show,
  (v) => {
    if (v) return
    file.value = null
    includeRecords.value = true
    includeTargets.value = true
    includeSettings.value = true
  },
)

function pickFile() {
  fileInput.value?.click()
}

function onFile(ev: Event) {
  const input = ev.target as HTMLInputElement
  file.value = input.files?.[0] ?? null
  input.value = '' // 允许重复选择同一文件
}

function submit() {
  if (props.mode === 'import' && !file.value) {
    message.warning('请选择要导入的 zip 数据包')
    return
  }
  emit('confirm', {
    file: file.value ?? undefined,
    include_records: includeRecords.value,
    include_targets: includeTargets.value,
    include_settings: includeSettings.value,
  })
}
</script>

<template>
  <n-modal :show="show" @update:show="(v: boolean) => emit('update:show', v)">
    <n-card
      style="width: 560px; max-width: 94vw"
      :title="mode === 'import' ? '导入数据' : '恢复备份'"
      :bordered="false"
      size="huge"
      role="dialog"
      aria-modal="true"
    >
      <n-space vertical size="large">
        <template v-if="mode === 'import'">
          <n-space align="center" :size="12" wrap>
            <n-button secondary @click="pickFile">选择 zip 数据包</n-button>
            <span class="hint">
              {{ file ? `${file.name}（${(file.size / 1024).toFixed(0)} KB）` : '未选择文件' }}
            </span>
            <input
              ref="fileInput"
              type="file"
              accept=".zip,application/zip"
              class="hidden-file"
              @change="onFile"
            />
          </n-space>
        </template>
        <span v-else class="hint">
          将从备份「{{ backupName }}」恢复；恢复前自动备份当前数据
        </span>
        <n-space vertical :size="8">
          <span class="label">导入内容（可多选）</span>
          <n-checkbox v-model:checked="includeRecords">检查记录（追加，按 id 去重）</n-checkbox>
          <n-checkbox v-model:checked="includeTargets">检查目标（按 id 合并）</n-checkbox>
          <n-checkbox v-model:checked="includeSettings">
            设置（逐键合并；日志不支持导入，将自动忽略）
          </n-checkbox>
        </n-space>
        <n-space justify="end">
          <n-button @click="emit('update:show', false)">取消</n-button>
          <n-button type="primary" :loading="loading" @click="submit">
            {{ mode === 'import' ? '导入' : '恢复' }}
          </n-button>
        </n-space>
      </n-space>
    </n-card>
  </n-modal>
</template>

<style scoped>
.hidden-file {
  display: none;
}
.hint {
  font-size: 13px;
  color: var(--cc-text-3);
}
.label {
  font-weight: 600;
}
</style>
