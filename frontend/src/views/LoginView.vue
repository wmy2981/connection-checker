<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { NAlert, NButton, NCard, NInput, useMessage } from 'naive-ui'

import { api } from '@/api'
import ThemeToggle from '@/components/ThemeToggle.vue'

const router = useRouter()
const message = useMessage()
const code = ref('')
const loading = ref(false)
const error = ref('')

async function submit() {
  if (!code.value) {
    error.value = '请输入访问码'
    return
  }
  loading.value = true
  error.value = ''
  try {
    await api.login(code.value)
    message.success('登录成功')
    router.push('/dashboard')
  } catch (e) {
    error.value = e instanceof Error ? e.message : '登录失败'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-wrap">
    <div class="theme-btn"><ThemeToggle /></div>
    <n-card title="连接检查工具" class="login-card">
      <p class="tip">请输入访问码以进入系统</p>
      <n-input
        v-model:value="code"
        type="password"
        show-password-on="click"
        placeholder="访问码"
        :disabled="loading"
        @keyup.enter="submit"
      />
      <n-alert v-if="error" type="error" class="err" :title="error" />
      <n-button type="primary" block class="submit" :loading="loading" @click="submit">登录</n-button>
    </n-card>
  </div>
</template>

<style scoped>
.login-wrap {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
  background: var(--cc-bg);
  position: relative;
}
.theme-btn {
  position: absolute;
  top: 16px;
  right: 20px;
}
.login-card {
  width: 360px;
  max-width: 100%;
}
.tip {
  color: var(--cc-text-3);
  margin: 0 0 16px;
}
.err {
  margin: 12px 0;
}
.submit {
  margin-top: 16px;
}
</style>
