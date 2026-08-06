<script setup lang="ts">
import { NButton } from 'naive-ui'

import { isDark } from '@/composables/useDark'
</script>

<template>
  <n-button quaternary size="small" :title="isDark ? '切换到浅色' : '切换到深色'" @click="isDark = !isDark">
    {{ isDark ? '浅色' : '深色' }}
  </n-button>
</template>
