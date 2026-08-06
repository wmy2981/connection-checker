import { reactive } from 'vue'

import { api } from '@/api'

export const authState = reactive({
  checked: false,
  authenticated: false,
})

export async function checkAuth(): Promise<boolean> {
  try {
    const res = await api.me()
    authState.authenticated = res.authenticated
  } catch {
    authState.authenticated = false
  }
  authState.checked = true
  return authState.authenticated
}
