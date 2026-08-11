<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { NConfigProvider, NDialogProvider, NMessageProvider, dateZhCN, zhCN, darkTheme } from 'naive-ui'
import type { GlobalTheme } from 'naive-ui'

import { isDark } from '@/composables/useDark'
import { loadAppTz } from '@/composables/useAppTime'

const theme = computed<GlobalTheme | null>(() => (isDark.value ? darkTheme : null))

onMounted(() => {
  void loadAppTz()
})
</script>

<template>
  <n-config-provider :theme="theme" :locale="zhCN" :date-locale="dateZhCN">
    <n-message-provider>
      <n-dialog-provider>
        <router-view />
      </n-dialog-provider>
    </n-message-provider>
  </n-config-provider>
</template>

<style>
/* 自定义主题变量：Naive 组件自带深浅色适配，此处供自定义样式的容器使用 */
:root {
  --cc-bg: #f5f6f8;
  --cc-panel-border: #e2e4e8;
  --cc-hover: #eceef1;
  --cc-text-3: #9aa0a6;
}
html.dark {
  --cc-bg: #101014;
  --cc-panel-border: #2c2c33;
  --cc-hover: #1f1f26;
  --cc-text-3: #8a8a93;
}
body {
  margin: 0;
  background: var(--cc-bg);
}
/* 下拉弹出列表可宽于触发器，完整显示长选项文本（通过 popup-class 使用） */
.wide-popup {
  min-width: 360px;
}
</style>
