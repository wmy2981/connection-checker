import { ref, watch } from 'vue'

const media = window.matchMedia('(prefers-color-scheme: dark)')

function applyDark(dark: boolean) {
  document.documentElement.classList.toggle('dark', dark)
  // 原生控件（滚动条、日期选择等）跟随主题
  document.documentElement.style.colorScheme = dark ? 'dark' : 'light'
}

export const isDark = ref(media.matches)
applyDark(isDark.value)

watch(isDark, (v) => applyDark(v))

media.addEventListener('change', (e) => {
  isDark.value = e.matches
})
