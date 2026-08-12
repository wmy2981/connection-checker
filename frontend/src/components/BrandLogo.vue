<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { api } from '@/api'

const icon = ref<string | null>(null)

onMounted(async () => {
  try {
    const s = await api.getAppSettings()
    icon.value = s.brand_icon
  } catch {
    /* 401 由 client 处理 */
  }
})
</script>

<template>
  <img :src="icon ?? '/favicon.svg'" alt="" class="brand-logo" @error="icon = null" />
</template>

<style scoped>
.brand-logo {
  width: 24px;
  height: 24px;
  object-fit: contain;
}
</style>
