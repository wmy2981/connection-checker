import { computed, ref, watch } from 'vue'

export type ThemeMode = 'auto' | 'light' | 'dark'

const STORAGE_KEY = 'cc-theme-mode'

const media = window.matchMedia('(prefers-color-scheme: dark)')
const systemDark = ref(media.matches)

// 用户选择保存在 localStorage，默认跟随系统
const saved = localStorage.getItem(STORAGE_KEY)
export const mode = ref<ThemeMode>(
  saved === 'light' || saved === 'dark' || saved === 'auto' ? saved : 'auto',
)

export const isDark = computed(
  () => mode.value === 'dark' || (mode.value === 'auto' && systemDark.value),
)

export function setMode(m: ThemeMode) {
  mode.value = m
  localStorage.setItem(STORAGE_KEY, m)
}

function applyDark(dark: boolean) {
  document.documentElement.classList.toggle('dark', dark)
  // 原生控件（滚动条、日期选择等）跟随主题
  document.documentElement.style.colorScheme = dark ? 'dark' : 'light'
}

applyDark(isDark.value)
watch(isDark, (v) => applyDark(v))

// 跟随系统模式下，系统主题变化实时生效
media.addEventListener('change', (e) => {
  systemDark.value = e.matches
})
