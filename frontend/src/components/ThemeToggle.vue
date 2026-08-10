<script setup lang="ts">
import { computed, h } from 'vue'
import { NButton, NDropdown, NIcon } from 'naive-ui'
import { DesktopOutline, MoonOutline, SunnyOutline } from '@vicons/ionicons5'

import { mode, setMode } from '@/composables/useDark'
import type { ThemeMode } from '@/composables/useDark'

const options = computed(() => [
  {
    label: '跟随系统',
    key: 'auto',
    icon: () => h(NIcon, { size: 16 }, { default: () => h(DesktopOutline) }),
    extra: mode.value === 'auto' ? '✓' : undefined,
  },
  {
    label: '浅色',
    key: 'light',
    icon: () => h(NIcon, { size: 16 }, { default: () => h(SunnyOutline) }),
    extra: mode.value === 'light' ? '✓' : undefined,
  },
  {
    label: '深色',
    key: 'dark',
    icon: () => h(NIcon, { size: 16 }, { default: () => h(MoonOutline) }),
    extra: mode.value === 'dark' ? '✓' : undefined,
  },
])

const currentIcon = computed(() => {
  if (mode.value === 'light') return SunnyOutline
  if (mode.value === 'dark') return MoonOutline
  return DesktopOutline
})

function onSelect(key: string) {
  setMode(key as ThemeMode)
}
</script>

<template>
  <n-dropdown :options="options" trigger="click" @select="onSelect">
    <n-button quaternary size="small" title="主题模式">
      <template #icon>
        <n-icon :size="16">
          <component :is="currentIcon" />
        </n-icon>
      </template>
    </n-button>
  </n-dropdown>
</template>
