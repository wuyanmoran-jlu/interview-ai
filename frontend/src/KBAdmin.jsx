import { useCallback, useEffect, useState } from 'react'
import axios from 'axios'

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'

const STATUS_LABELS = {
  draft: '草稿',
  failed: '未通过',
  new: '新题',
  published: '已转正',
  rejected: '已踢出',
}

const STATUS_OPTIONS = ['', 'draft', 'failed', 'new', 'published', 'rejected']

// 各状态允许的人工审核流转
const TRANSITIONS = {
  draft: [
    { to: 'new', label: '通过入库' },
    { to: 'failed', label: '质检打回' },
  ],
  failed: [{ to: 'draft', label: '修复回草稿' }],
  new: [
    { to: 'published', label: '转正' },
    { to: 'rejected', label: '踢出' },
  ],
  published: [{ to: 'rejected', label: '踢出' }],
  rejected: [{ to: 'draft', label: '捞回草稿' }],
}

export default function KBAdmin() {
  const [questions, setQuestions] = useState([])
  const [stats, setStats] = useState(null)
  const [statusFilter, setStatusFilter] = useState('')
  const [difficultyFilter, setDifficultyFilter] = useState('')
  const [topicFilter, setTopicFilter] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const loadStats = useCallback(async () => {
    try {
      const res = await axios.get(`${API_BASE}/kb/stats`)
      setStats(res.data)
    } catch {
      setStats(null) // 看板失败不影响主列表
    }
  }, [])

  const loadQuestions = useCallback(async () => {
    try {
      setLoading(true)
      setError('')
      const params = {}
      if (statusFilter) params.status = statusFilter
      if (difficultyFilter) params.difficulty = difficultyFilter
      if (topicFilter) params.topic = topicFilter
      const res = await axios.get(`${API_BASE}/kb/questions`, { params })
      setQuestions(res.data.questions || [])
    } catch (err) {
      setError('加载题库失败：' + (err.response?.data?.error || err.message))
    } finally {
      setLoading(false)
    }
  }, [statusFilter, difficultyFilter, topicFilter])

  useEffect(() => { loadQuestions() }, [loadQuestions])
  useEffect(() => { loadStats() }, [loadStats])

  const changeStatus = async (id, to) => {
    try {
      await axios.patch(`${API_BASE}/kb/questions/${id}/status`, { status: to })
      await loadQuestions()
    } catch (err) {
      alert('状态流转失败：' + (err.response?.data?.error || err.message))
    }
  }

  const removeQuestion = async (id) => {
    if (!confirm('确定删除这道题？')) return
    try {
      await axios.delete(`${API_BASE}/kb/questions/${id}`)
      await loadQuestions()
    } catch (err) {
      alert('删除失败：' + (err.response?.data?.error || err.message))
    }
  }

  return (
    <div className="kb-admin">
      <div className="kb-toolbar">
        <h2>题库管理</h2>
        <div className="kb-filters">
          <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
            <option value="">全部状态</option>
            {STATUS_OPTIONS.filter(Boolean).map(s => (
              <option key={s} value={s}>{STATUS_LABELS[s]}</option>
            ))}
          </select>
          <select value={difficultyFilter} onChange={(e) => setDifficultyFilter(e.target.value)}>
            <option value="">全部难度</option>
            {['简单', '中等', '困难'].map(d => <option key={d} value={d}>{d}</option>)}
          </select>
          <select value={topicFilter} onChange={(e) => setTopicFilter(e.target.value)}>
            <option value="">全部方向</option>
            {['算法', '数据结构', '系统设计', '数据库', '前端开发'].map(t => <option key={t} value={t}>{t}</option>)}
          </select>
          <button onClick={() => { loadQuestions(); loadStats() }} disabled={loading}>刷新</button>
        </div>
      </div>

      {stats && (
        <div className="kb-stats-bar">
          <div className="kb-stat"><span className="kb-stat-num">{stats.total}</span><span>总题数</span></div>
          <div className="kb-stat"><span className="kb-stat-num">{stats.active}</span><span>活跃题</span></div>
          <div className="kb-stat"><span className="kb-stat-num">{stats.by_status?.published || 0}</span><span>已转正</span></div>
          <div className="kb-stat"><span className="kb-stat-num">{stats.by_status?.new || 0}</span><span>新题</span></div>
          <div className="kb-stat">
            <span className="kb-stat-num">{stats.up_ratio != null ? (stats.up_ratio * 100).toFixed(0) + '%' : '—'}</span>
            <span>总好评率</span>
          </div>
          <div className={`kb-stat ${stats.needs_calibration > 0 ? 'kb-stat-warn' : ''}`}>
            <span className="kb-stat-num">{stats.needs_calibration}</span>
            <span>待校准难度</span>
          </div>
        </div>
      )}

      {error && <p className="kb-error">{error}</p>}

      <div className="kb-list">
        {!loading && questions.length === 0 && !error && (
          <p className="placeholder">题库为空，先运行批量生成或导入题目。</p>
        )}
        {questions.map(q => (
          <div key={q.id} className="kb-card">
            <div className="kb-card-header">
              <span className="kb-title">{q.title}</span>
              <span className={`kb-status kb-status-${q.status}`}>
                {STATUS_LABELS[q.status] || q.status}
              </span>
            </div>
            <div className="kb-meta">
              {q.language} · {q.difficulty} · {q.topic}
              {q.source === 'generated' && <span className="kb-tag">生成题</span>}
            </div>
            <div className="kb-stats">
              <span>使用 {q.usage_count} 次</span>
              <span>评价 {q.review_count} 条</span>
              <span>👍 {q.up_count}</span>
              <span>👎 {q.down_count}</span>
              {q.avg_score != null && (
                <span>均分 {q.avg_score}（{q.score_count} 次）</span>
              )}
            </div>
            {q.difficulty_hint && (
              <div className="kb-hint">⚠ {q.difficulty_hint}</div>
            )}
            <div className="kb-actions">
              {(TRANSITIONS[q.status] || []).map(t => (
                <button key={t.to} onClick={() => changeStatus(q.id, t.to)}>{t.label}</button>
              ))}
              <button className="kb-delete" onClick={() => removeQuestion(q.id)}>删除</button>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
