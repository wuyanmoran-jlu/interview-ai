import { useState } from 'react'
import axios from 'axios'
import { setAuth } from './auth'

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'

export default function LoginModal({ open, onClose, onAuth }) {
  const [mode, setMode] = useState('login') // login | register
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  if (!open) return null

  const submit = async () => {
    if (!username.trim() || !password) {
      setError('请输入用户名和密码')
      return
    }
    setBusy(true)
    setError('')
    try {
      // 携带匿名 ID：登录/注册成功后后端会自动合并匿名期间的历史
      const anonymousId = localStorage.getItem('interview_user_id') || ''
      const path = mode === 'login' ? '/auth/login' : '/auth/register'
      const res = await axios.post(`${API_BASE}${path}`, {
        username: username.trim(),
        password,
        anonymous_id: anonymousId,
      })
      setAuth(res.data.token, res.data.user)
      localStorage.setItem('interview_user_id', res.data.user.id)
      onAuth(res.data.user)
      setPassword('')
      onClose()
    } catch (err) {
      setError(err.response?.data?.error || '操作失败，请重试')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="auth-modal" onClick={(e) => e.stopPropagation()}>
        <button className="modal-close" onClick={onClose} title="关闭">×</button>
        <h3>{mode === 'login' ? '登录' : '注册'}</h3>
        <p className="modal-hint">
          登录后你的面试历史将跟随账号保存，跨设备可见；匿名期间的记录会自动合并。
        </p>
        <input
          placeholder="用户名（3-20 位字母数字下划线）"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          autoFocus
        />
        <input
          type="password"
          placeholder="密码（至少 8 位）"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && submit()}
        />
        {error && <p className="modal-error">{error}</p>}
        <div className="modal-actions">
          <button onClick={submit} disabled={busy}>
            {busy ? '处理中...' : mode === 'login' ? '登录' : '注册并登录'}
          </button>
          <button
            className="ghost"
            onClick={() => { setMode(mode === 'login' ? 'register' : 'login'); setError('') }}
          >
            {mode === 'login' ? '没有账号？去注册' : '已有账号？去登录'}
          </button>
        </div>
      </div>
    </div>
  )
}
