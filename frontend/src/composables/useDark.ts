import { ref } from 'vue'

const media = window.matchMedia('(prefers-color-scheme: dark)')
export const isDark = ref(media.matches)

media.addEventListener('change', (e) => {
  isDark.value = e.matches
})
