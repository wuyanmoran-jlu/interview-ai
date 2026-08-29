import { useEffect, useState } from 'react'
import axios from 'axios'
import { clearAuth, resetAnonymousId } from './auth'

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'

export default function ProfileModal({ open, onClose, user, onLoggedOut, onPractice }) {
  const [stats, setStats] = useState(null)
  const [weaknesses, setWeaknesses] = useState(null)
  const [oldPassword, setOldPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState('')
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!open) return
    setStats(null)
    setWeaknesses(null)
    setMsg('')
    setError('')
    axios
      .get(`${API_BASE}/auth/stats`)
      .then((res) => setStats(res.data))
      .catch(() => setStats(null))
    axios
      .get(`${API_BASE}/auth/weaknesses`)
      .then((res) => setWeaknesses(res.data))
      .catch(() => setWeaknesses(null))
  }, [open])

  if (!open) return null

  const submitPassword = async () => {
    if (newPassword !== confirmPassword) {
      setError('两次输入的新密码不一致')
      return
    }
    setBusy(true)
    setError('')
    setMsg('')
    try {
      const res = await axios.post(`${API_BASE}/auth/password`, {
        old_password: oldPassword,
        new_password: newPassword,
      })
      setMsg(res.data.message || '密码已修改')
      setOldPassword('')
      setNewPassword('')
      setConfirmPassword('')
      // 后端已拉黑当前 token，本地清理并回到匿名模式
      clearAuth()
      resetAnonymousId()
      onLoggedOut()
    } catch (err) {
      setError(err.response?.data?.error || '修改失败，请重试')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="auth-modal profile-modal" onClick={(e) => e.stopPropagation()}>
        <button className="modal-close" onClick={onClose} title="关闭">×</button>
        <h3>个人中心</h3>
        <p className="modal-hint">👤 {user?.username}</p>

        <div className="profile-stats">
          <div className="profile-stat">
            <span className="profile-stat-num">{stats ? stats.total_sessions : '—'}</span>
            <span>面试场次</span>
          </div>
          <div className="profile-stat">
            <span className="profile-stat-num">{stats ? stats.total_ratings : '—'}</span>
            <span>题目评价</span>
          </div>
        </div>

        {stats && (Object.keys(stats.by_topic || {}).length > 0) && (
          <div className="profile-breakdown">
            <h4>方向分布</h4>
            {Object.entries(stats.by_topic).map(([t, c]) => (
              <span key={t} className="profile-chip">{t} × {c}</span>
            ))}
          </div>
        )}
        {stats && (Object.keys(stats.by_difficulty || {}).length > 0) && (
          <div className="profile-breakdown">
            <h4>难度分布</h4>
            {Object.entries(stats.by_difficulty).map(([d, c]) => (
              <span key={d} className="profile-chip">{d} × {c}</span>
            ))}
          </div>
        )}

        <div className="profile-divider" />
        <h4>薄弱方向</h4>
        {weaknesses && weaknesses.ready ? (
          <div className="weakness-list">
            {weaknesses.weaknesses.map((w) => (
              <div key={w.topic} className="weakness-item">
                <div className="weakness-info">
                  <span className="weakness-topic">{w.topic}</span>
                  <span className="weakness-score">均分 {w.avg_score}（{w.sessions} 场）</span>
                </div>
                <button className="weakness-practice" onClick={() => onPractice && onPractice(w.topic)}>
                  去练习
                </button>
              </div>
            ))}
          </div>
        ) : (
          <p className="modal-hint">
            {weaknesses?.message || '完成至少 3 场带评分的面试后，即可解锁薄弱方向分析。'}
          </p>
        )}

        <div className="profile-divider" />
        <h4>修改密码</h4>
        <input
          type="password"
          placeholder="原密码"
          value={oldPassword}
          onChange={(e) => setOldPassword(e.target.value)}
        />
        <input
          type="password"
          placeholder="新密码（至少 8 位）"
          value={newPassword}
          onChange={(e) => setNewPassword(e.target.value)}
        />
        <input
          type="password"
          placeholder="确认新密码"
          value={confirmPassword}
          onChange={(e) => setConfirmPassword(e.target.value)}
        />
        {error && <p className="modal-error">{error}</p>}
        {msg && <p className="modal-ok">{msg}</p>}
        <div className="modal-actions">
          <button onClick={submitPassword} disabled={busy}>
            {busy ? '提交中...' : '修改密码'}
          </button>
        </div>
      </div>
    </div>
  )
}
