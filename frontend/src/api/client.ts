const BASE = '/api/v1'

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers)
  if (options.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  const res = await fetch(BASE + path, { ...options, headers })

  // 会话失效时跳转登录页（登录/会话查询接口除外，避免死循环）
  if (res.status === 401 && !path.startsWith('/auth/')) {
    window.location.href = '/login'
    throw new ApiError(401, '未授权访问')
  }
  if (!res.ok) {
    let detail = res.statusText
    try {
      const data = await res.json()
      if (typeof data.detail === 'string') detail = data.detail
    } catch {
      /* 非 JSON 响应，保留默认信息 */
    }
    throw new ApiError(res.status, detail)
  }
  if (res.status === 204) {
    return undefined as T
  }
  return (await res.json()) as T
}
