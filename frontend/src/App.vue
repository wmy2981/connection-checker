<script setup lang="ts">
import { computed } from 'vue'
import { NConfigProvider, NDialogProvider, NMessageProvider, dateZhCN, zhCN, darkTheme } from 'naive-ui'
import type { GlobalTheme } from 'naive-ui'

import { isDark } from '@/composables/useDark'

const theme = computed<GlobalTheme | null>(() => (isDark.value ? darkTheme : null))
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
