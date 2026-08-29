import axios from 'axios'

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'
const TOKEN_KEY = 'interview_token'
const USER_KEY = 'interview_current_user'

export function getToken() {
  return localStorage.getItem(TOKEN_KEY)
}

export function getCurrentUser() {
  try {
    return JSON.parse(localStorage.getItem(USER_KEY))
  } catch {
    return null
  }
}

export function setAuth(token, user) {
  localStorage.setItem(TOKEN_KEY, token)
  localStorage.setItem(USER_KEY, JSON.stringify(user))
}

export function clearAuth() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
}

export function getEffectiveUserId() {
  let uid = localStorage.getItem('interview_user_id')
  if (!uid) {
    uid = 'user-' + crypto.randomUUID()
    localStorage.setItem('interview_user_id', uid)
  }
  return uid
}

export function resetAnonymousId() {
  const id = 'user-' + crypto.randomUUID()
  localStorage.setItem('interview_user_id', id)
  return id
}

// 请求拦截器：自动附加 Bearer Token
axios.interceptors.request.use((config) => {
  const token = getToken()
  if (token) {
    config.headers = config.headers || {}
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// 响应拦截器：token 失效（登录接口自身的 401 除外）时清理登录态并通知
axios.interceptors.response.use(
  (res) => res,
  (err) => {
    const url = err.config?.url || ''
    if (err.response?.status === 401 && !url.includes('/auth/login')) {
      clearAuth()
      window.dispatchEvent(new CustomEvent('auth-expired'))
    }
    return Promise.reject(err)
  }
)

/**
 * SSE 流式 POST：POST JSON 并逐段解析 server-sent events。
 * - onMeta: 首事件（元数据）回调
 * - onDelta: 每个文本增量回调
 * 返回完整响应流解析完成后的 Promise。
 */
export async function streamPost(url, body, { onMeta, onDelta } = {}) {
  const headers = { 'Content-Type': 'application/json' }
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`

  const res = await fetch(`${API_BASE}${url}`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
  })

  if (res.status === 401) {
    clearAuth()
    window.dispatchEvent(new CustomEvent('auth-expired'))
    throw new Error('登录已失效')
  }
  if (!res.ok) {
    let detail = `请求失败（${res.status}）`
    try {
      const data = await res.json()
      if (data?.error) detail = data.error
    } catch {
      /* 非 JSON 错误体 */
    }
    throw new Error(detail)
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let currentEvent = 'message'

  const handleEvent = (eventName, dataText) => {
    let payload
    try {
      payload = JSON.parse(dataText)
    } catch {
      return
    }
    if (eventName === 'meta') {
      if (onMeta) onMeta(payload)
    } else if (eventName !== 'done' && payload && payload.delta != null) {
      if (onDelta) onDelta(payload.delta)
    }
  }

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    const chunks = buffer.split('\n\n')
    buffer = chunks.pop() // 最后一个可能不完整
    for (const chunk of chunks) {
      for (const line of chunk.split('\n')) {
        if (line.startsWith('event:')) {
          currentEvent = line.slice(6).trim()
        } else if (line.startsWith('data:')) {
          handleEvent(currentEvent, line.slice(5).trim())
        }
      }
    }
  }
}
