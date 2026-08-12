<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { api } from '@/api'

const icon = ref<string | null>(null)

// 品牌图标同步到浏览器 tab favicon（保持标签页与页面内一致）
function applyFavicon(src: string) {
  let link = document.querySelector<HTMLLinkElement>('link[rel="icon"]')
  if (!link) {
    link = document.createElement('link')
    link.rel = 'icon'
    document.head.appendChild(link)
  }
  link.href = src
}

onMounted(async () => {
  try {
    const s = await api.getAppSettings()
    icon.value = s.brand_icon
    if (s.brand_icon) applyFavicon(s.brand_icon)
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
