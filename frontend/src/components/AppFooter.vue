<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { NIcon } from 'naive-ui'
import { LogoGithub } from '@vicons/ionicons5'

import { api } from '@/api'

const version = ref('')

onMounted(async () => {
  try {
    const meta = await api.meta()
    version.value = meta.version
  } catch {
    /* 网络失败时隐藏版本号 */
  }
})
</script>

<template>
  <footer class="app-footer">
    <a
      href="https://github.com/wmy2981/connection-checker"
      target="_blank"
      rel="noopener noreferrer"
      class="footer-link"
    >
      <span>Connection Checker{{ version ? ` v${version}` : '' }}</span>
      <n-icon :size="15"><LogoGithub /></n-icon>
    </a>
  </footer>
</template>

<style scoped>
.app-footer {
  padding: 24px 0 32px;
  text-align: center;
}
.footer-link {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--cc-text-3);
  text-decoration: none;
  transition: color 0.2s;
}
.footer-link:hover {
  color: #0ca30c;
}
</style>
