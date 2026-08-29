import axios from 'axios'

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
