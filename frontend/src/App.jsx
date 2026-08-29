import { useState, useEffect, useCallback } from 'react'
import Editor from '@monaco-editor/react'
import ReactMarkdown from 'react-markdown'
import axios from 'axios'
import './App.css'
import KBAdmin from './KBAdmin'
import LoginModal from './LoginModal'
import ProfileModal from './ProfileModal'
import { clearAuth, getCurrentUser, getEffectiveUserId, resetAnonymousId, streamPost } from './auth'

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'

const DEFAULT_RUBRIC = `### 1. 代码正确性（权重 30%）
- 10 分：通过所有测试用例，输出完全符合预期
- 7-9 分：主要用例通过，有 1-2 个小瑕疵
- 4-6 分：核心思路正确但存在明显 bug
- 1-3 分：代码无法运行或逻辑严重偏离

### 2. 算法效率（权重 25%）
- 10 分：时间/空间复杂度均为最优解
- 7-9 分：复杂度在可接受范围（如 O(n log n)）
- 4-6 分：使用了暴力解法，存在优化空间
- 1-3 分：完全没有复杂度意识

### 3. 代码质量（权重 20%）
- 10 分：命名规范、结构清晰、有适当注释
- 7-9 分：总体清晰，个别可改进
- 4-6 分：结构混乱，变量名无意义
- 1-3 分：难以阅读和维护

### 4. 边界处理（权重 15%）
- 10 分：全面处理空输入、极值、异常数据
- 7-9 分：考虑了主要边界
- 4-6 分：仅处理正常输入
- 1-3 分：完全没有边界处理

### 5. 沟通与思维（权重 10%）
- 10 分：思路清晰，主动改进，连贯性强
- 7-9 分：基本能表达思路
- 4-6 分：思路模糊，回答被动
- 1-3 分：无法解释自己的代码

最终得分 = 正确性×30% + 算法×25% + 代码质量×20% + 边界×15% + 沟通×10%`
const LANGUAGES = [
  { value: 'python', label: 'Python' },
  { value: 'javascript', label: 'JavaScript' },
  { value: 'java', label: 'Java' },
  { value: 'cpp', label: 'C++' },
]

const TOPICS = [
  { value: '算法', label: '算法' },
  { value: '数据结构', label: '数据结构' },
  { value: '系统设计', label: '系统设计' },
  { value: '数据库', label: '数据库' },
  { value: '前端开发', label: '前端开发' },
]

const DIFFICULTIES = [
  { value: '简单', label: '简单' },
  { value: '中等', label: '中等' },
  { value: '困难', label: '困难' },
]

function App() {
  const [currentUser, setCurrentUser] = useState(getCurrentUser)
  const [showLogin, setShowLogin] = useState(false)
  const [showProfile, setShowProfile] = useState(false)
  const [sessions, setSessions] = useState([])
  const [sessionId, setSessionId] = useState(null)
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [view, setView] = useState('interview')

  const [question, setQuestion] = useState('')
  const [code, setCode] = useState('# 在这里写代码\n')
  const [output, setOutput] = useState('')
  const [review, setReview] = useState('')
  const [loading, setLoading] = useState(false)
  const [language, setLanguage] = useState('python')
  const [topic, setTopic] = useState('算法')
  const [difficulty, setDifficulty] = useState('中等')
  const [answerText, setAnswerText] = useState('')
  const [stdin, setStdin] = useState('')
  const [sessionError, setSessionError] = useState('')
  const [showRubric, setShowRubric] = useState(false)
  const [reviewRound, setReviewRound] = useState(0)

  const [questionId, setQuestionId] = useState(null)
  const [rated, setRated] = useState(false)
  const [ratingMsg, setRatingMsg] = useState('')
  const [rubricText, setRubricText] = useState(null)
  const [verdict, setVerdict] = useState(null)

  const loadSessions = useCallback(async () => {
    try {
      setSessionError('')
      const res = await axios.get(`${API_BASE}/interview/sessions`, {
        params: { user_id: getEffectiveUserId() },
      })
      setSessions(res.data.sessions || [])
    } catch (err) {
      setSessionError('Failed to load sessions: ' + (err.response?.data?.detail || err.message))
    }
  }, [])

  useEffect(() => { loadSessions() }, [loadSessions])

  const switchSession = async (id) => {
    try {
      setLoading(true)
      const res = await axios.get(`${API_BASE}/interview/session/${id}`)
      setSessionId(id)
      const msgs = res.data.messages || []
      const firstQ = msgs.find(m => m.role === 'assistant')
      setQuestion(firstQ ? firstQ.content : '')
      const lastAI = [...msgs].reverse().find(m => m.role === 'assistant')
      setReview(lastAI && lastAI.content !== (firstQ ? firstQ.content : '')
        ? lastAI.content : '')
      setOutput('')
      setReviewRound(0)
      setAnswerText('')
      setStdin('')
      setRated(false)
      setRatingMsg('')
      setVerdict(null)
      if (res.data.meta) {
        if (res.data.meta.language) setLanguage(res.data.meta.language)
        if (res.data.meta.topic) setTopic(res.data.meta.topic)
        if (res.data.meta.difficulty) setDifficulty(res.data.meta.difficulty)
        setQuestionId(res.data.meta.question_id || null)
      } else {
        setQuestionId(null)
      }    } catch (err) {
      alert('加载会话失败：' + err.message)
    } finally {
      setLoading(false)
    }
  }

  const deleteSession = async (id) => {
    if (!confirm('确定删除这个会话？')) return
    try {
      await axios.delete(`${API_BASE}/interview/session/${id}`, {
        params: { user_id: getEffectiveUserId() },
      })
      if (sessionId === id) {
        setSessionId(null)
        setQuestion('')
        setReview('')
        setOutput('')
        setQuestionId(null)
        setRated(false)
        setRatingMsg('')
      }
      await loadSessions()
    } catch (err) {
      alert('删除失败：' + err.message)
    }
  }

  const startInterview = async () => {
    try {
      setLoading(true)
      const res = await axios.post(`${API_BASE}/interview/start`, {
        topic: topic,
        difficulty: difficulty,
        language: language,
        user_id: getEffectiveUserId(),
      })
      setSessionId(res.data.session_id)
      setQuestion(res.data.question)
      setOutput('')
      setReview('')
      setAnswerText('')
      setStdin('')
      setReviewRound(0)
      setQuestionId(res.data.question_id || null)
      setRated(false)
      setRatingMsg('')
      setVerdict(null)
      await loadSessions()
    } catch (err) {
      alert('启动面试失败：' + err.message)
    } finally {
      setLoading(false)
    }
  }

  const runCode = async () => {
    if (!sessionId) return alert('请先选择或开始一个面试')
    try {
      setLoading(true)
      const res = await axios.post(`${API_BASE}/interview/run`, {
        session_id: sessionId,
        source_code: code,
        language: language,
        stdin: stdin,
      })
      const r = res.data
      setOutput(
        '=== 标准输出 ===\n' + (r.stdout || '(无)') +
        '\n\n=== 错误输出 ===\n' + (r.stderr || '(无)') +
        (r.signal ? '\n\n=== 信号 ===\n' + r.signal : '') +
        (r.code !== null && r.code !== 0 ? '\n\n=== 退出码 ===\n' + r.code : '')
      )
    } catch (err) {
      setOutput('运行失败：' + err.message)
    } finally {
      setLoading(false)
    }
  }

  const verifyCode = async () => {
    if (!sessionId) return alert('请先选择或开始一个面试')
    try {
      setLoading(true)
      const res = await axios.post(`${API_BASE}/interview/verify`, {
        session_id: sessionId,
        source_code: code,
        language: language,
      })
      if (res.data.available) {
        setVerdict(res.data)
      } else {
        setVerdict(null)
        alert('当前题目不支持自动判题（AI 生成题），请直接运行并提交点评。')
      }
    } catch (err) {
      setVerdict(null)
      alert('判题失败：' + (err.response?.data?.error || err.message))
    } finally {
      setLoading(false)
    }
  }

  const reviewCode = async () => {
    if (!sessionId) return alert('请先选择或开始一个面试')
    try {
      setLoading(true)
      setReview('')
      await streamPost('/interview/review', {
        session_id: sessionId,
        source_code: code,
        language: language,
      }, {
        onMeta: (meta) => {
          if (meta.review_round) setReviewRound(meta.review_round)
          const r = meta.run_result
          if (r) {
            setOutput(
              '=== 标准输出 ===\n' + (r.stdout || '(无)') +
              '\n\n=== 错误输出 ===\n' + (r.stderr || '(无)') +
              (r.signal ? '\n\n=== 信号 ===\n' + r.signal : '') +
              (r.code !== null && r.code !== 0 ? '\n\n=== 退出码 ===\n' + r.code : '')
            )
          }
        },
        onDelta: (d) => setReview((prev) => prev + d),
      })
    } catch (err) {
      setReview('获取点评失败：' + err.message)
    } finally {
      setLoading(false)
    }
  }

  const sendAnswer = async () => {
    if (!sessionId) return alert('没有进行中的面试')
    if (!answerText.trim()) return alert('请输入你的回答')
    try {
      setLoading(true)
      setReview('')
      await streamPost('/interview/answer', {
        session_id: sessionId,
        answer: answerText,
      }, {
        onDelta: (d) => setReview((prev) => prev + d),
      })
      setAnswerText('')
    } catch (err) {
      alert('发送回答失败：' + err.message)
    } finally {
      setLoading(false)
    }
  }

  const endInterview = async () => {
    if (!sessionId) return alert('没有进行中的面试')
    try {
      setLoading(true)
      setReview('')
      await streamPost('/interview/evaluate', {
        session_id: sessionId,
      }, {
        onDelta: (d) => setReview((prev) => prev + d),
      })
      setQuestion('')
    } catch (err) {
      alert('获取评价失败：' + err.message)
    } finally {
      setLoading(false)
    }
  }

  const rateQuestion = async (value) => {
    if (!questionId) return
    try {
      await axios.post(`${API_BASE}/kb/questions/${questionId}/rating`, {
        user_id: getEffectiveUserId(),
        value: value,
        dimension: 'overall',
      })
      setRated(true)
      setRatingMsg(value ? '谢谢你的认可！' : '已收到你的反馈，我们会改进这道题。')
    } catch (err) {
      alert('评价提交失败：' + (err.response?.data?.error || err.message))
    }
  }

  const toggleRubric = async () => {
    const next = !showRubric
    setShowRubric(next)
    if (next && !rubricText) {
      try {
        const res = await axios.get(`${API_BASE}/interview/rubric`)
        setRubricText(res.data.rubric || DEFAULT_RUBRIC)
      } catch {
        setRubricText(DEFAULT_RUBRIC)
      }
    }
  }

  const handleLogout = async () => {
    try {
      await axios.post(`${API_BASE}/auth/logout`)
    } catch {
      // token 已失效等情况忽略，继续本地清理
    }
    clearAuth()
    resetAnonymousId()  // 登出后回到匿名模式，生成新的匿名 ID
    setCurrentUser(null)
    setSessionId(null)
    setQuestion('')
    setReview('')
    setOutput('')
    setQuestionId(null)
    setRated(false)
    setRatingMsg('')
    await loadSessions()
  }

  // token 失效（401）时的全局处理
  useEffect(() => {
    const handler = () => {
      setCurrentUser(null)
      resetAnonymousId()
      setSessionId(null)
      setQuestion('')
      setReview('')
      alert('登录已失效，请重新登录。')
    }
    window.addEventListener('auth-expired', handler)
    return () => window.removeEventListener('auth-expired', handler)
  }, [])

  const monacoLang = language === 'cpp' ? 'cpp' : language

  return (
    <div className="app">
      <header className="header">
        <div className="header-left">
          <button className="toggle-sidebar" onClick={() => setSidebarOpen(!sidebarOpen)}
            title="切换侧边栏">☰</button>
          <h1>AI 面试模拟器</h1>
          <div className="view-tabs">
            <button className={view === 'interview' ? 'view-tab active' : 'view-tab'}
              onClick={() => setView('interview')}>面试模拟</button>
            <button className={view === 'kb' ? 'view-tab active' : 'view-tab'}
              onClick={() => setView('kb')}>题库管理</button>
          </div>
        </div>
        <div className="header-controls">
          <div className="lang-selector">
            <label>方向：</label>
            <select value={topic} onChange={(e) => setTopic(e.target.value)}>
              {TOPICS.map(t => (
                <option key={t.value} value={t.value}>{t.label}</option>
              ))}
            </select>
          </div>
          <div className="lang-selector">
            <label>难度：</label>
            <select value={difficulty} onChange={(e) => setDifficulty(e.target.value)}>
              {DIFFICULTIES.map(d => (
                <option key={d.value} value={d.value}>{d.label}</option>
              ))}
            </select>
          </div>
          <div className="lang-selector">
            <label>语言：</label>
            <select value={language} onChange={(e) => setLanguage(e.target.value)}>
              {LANGUAGES.map(l => (
                <option key={l.value} value={l.value}>{l.label}</option>
              ))}
            </select>
          </div>
          <button onClick={startInterview} disabled={loading}>+ 新面试</button>
          <button className="rubric-toggle" onClick={toggleRubric}
            title="查看评分细则">
            {showRubric ? '隐藏细则' : '评分细则'}
          </button>
          <div className="user-area">
            {currentUser ? (
              <>
                <button className="user-name user-name-btn" onClick={() => setShowProfile(true)}>
                  👤 {currentUser.username}
                </button>
                <button className="user-btn" onClick={handleLogout}>登出</button>
              </>
            ) : (
              <button className="user-btn" onClick={() => setShowLogin(true)}>登录 / 注册</button>
            )}
          </div>
        </div>
      </header>
      {view === 'interview' ? (
      <div className="main">        <div className={`sidebar ${sidebarOpen ? 'open' : 'closed'}`}>
          <div className="sidebar-header"><span>会话记录</span></div>
          <div className="session-list">
            {sessionError && (
              <div className="session-error">
                <span>{sessionError}</span>
                <button onClick={loadSessions}>Retry</button>
              </div>
            )}
            {sessions.length === 0 && !sessionError && (
              <p className="placeholder" style={{ padding: '12px' }}>暂无会话</p>
            )}
            {sessions.map(s => (
              <div key={s.id}
                className={`session-item ${sessionId === s.id ? 'active' : ''}`}
                onClick={() => switchSession(s.id)}>
                <div className="session-info">
                  <span className="session-title">{s.title}</span>
                  <span className="session-meta">{s.language} · {s.difficulty} · {s.created_at ? s.created_at.slice(0, 10) : ''}</span>
                </div>
                <button className="delete-btn" onClick={(e) => { e.stopPropagation(); deleteSession(s.id) }}
                  title="删除">×</button>
              </div>
            ))}
          </div>
        </div>
        <div className="content-area">
          <div className="left-panel">
            <div className="question-box">
              <h3>📋 题目</h3>
              <div className="markdown-content">
                {question ? (
                  <ReactMarkdown>{question}</ReactMarkdown>
                ) : (
                  <p className="placeholder">点击"+ 新面试"获取题目</p>
                )}
              </div>
            </div>
            {questionId && (
              <div className="question-rating">
                <span>这道题质量如何？</span>
                {rated ? (
                  <span className="rating-msg">{ratingMsg}</span>
                ) : (
                  <>
                    <button onClick={() => rateQuestion(1)} disabled={loading} title="好评">👍</button>
                    <button onClick={() => rateQuestion(0)} disabled={loading} title="差评">👎</button>
                  </>
                )}
              </div>
            )}
            <div className="stdin-box">
              <h3>⌨ 自定义输入 (stdin)</h3>
              <textarea className="stdin-input" rows={3}
                placeholder="输入测试数据..."
                value={stdin} onChange={(e) => setStdin(e.target.value)} disabled={loading} />
            </div>
            <div className="output-box">
              <h3>🖥 运行输出</h3>
              <pre>{output || '点击 ▶ 运行 查看代码执行结果'}</pre>
            </div>
          </div>
          <div className="right-panel">
            <div className="editor-container">
              <Editor height="50vh" language={monacoLang} value={code}
                onChange={(val) => setCode(val)} theme="vs-dark" />
            </div>
            <div className="button-group">
              <button onClick={runCode} disabled={loading || !sessionId}>▶ 运行</button>
              <button onClick={verifyCode} disabled={loading || !sessionId} title="用题库隐藏用例判定通过率">✅ 判题</button>
              <button onClick={reviewCode} disabled={loading || !sessionId}>🧠 提交并获取点评</button>
              <button onClick={endInterview} disabled={loading || !sessionId}>🏁 结束面试</button>
            </div>
            {verdict && (
              <div className="verdict-box">
                <div className="verdict-header">
                  <span className={verdict.passed === verdict.total ? 'verdict-pass' : 'verdict-fail'}>
                    {verdict.passed === verdict.total ? '✅ 全部通过' : `❌ 通过 ${verdict.passed}/${verdict.total}`}
                  </span>
                  <button className="verdict-clear" onClick={() => setVerdict(null)}>×</button>
                </div>
                <div className="verdict-cases">
                  {verdict.results.map((r, i) => (
                    <div key={i} className={`verdict-case ${r.passed ? 'case-pass' : 'case-fail'}`}>
                      <span className="case-mark">{r.passed ? '✓' : '✗'}</span>
                      <div className="case-detail">
                        <span>输入: {r.stdin || '(空)'}</span>
                        <span>期望: {r.expected}</span>
                        {!r.passed && <span>实际: {r.actual || r.signal || '(无输出)'}</span>}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
            <div className="review-box">
              <h3>🤖 AI 点评</h3>
              {reviewRound > 0 && (
                <p className="placeholder" style={{ marginBottom: '8px' }}>
                  当前是第 {reviewRound} 轮修改反馈，你可以继续改代码后再次提交。
                </p>
              )}
              <div className="markdown-content">
                {review ? (
                  <ReactMarkdown>{review}</ReactMarkdown>
                ) : (
                  <p className="placeholder">提交代码后 AI 面试官会在这里给出点评</p>
                )}
              </div>
            </div>
            {sessionId && (
              <div className="answer-box">
                <h3>💬 回答面试官追问</h3>
                <textarea className="answer-input" rows={4}
                  placeholder="在这里输入你对面试官追问的回答..."
                  value={answerText} onChange={(e) => setAnswerText(e.target.value)} disabled={loading} />
                <button className="answer-btn" onClick={sendAnswer}
                  disabled={loading || !answerText.trim()}>📤 发送回答</button>
              </div>
            )}
          </div>
        </div>

        {showRubric && (
          <div className="rubric-panel">
            <div className="rubric-content">
              <h3>评分细则</h3>
              <ReactMarkdown>{rubricText || DEFAULT_RUBRIC}</ReactMarkdown>
            </div>
          </div>
        )}
      </div>
      ) : (
        <KBAdmin />
      )}
      <LoginModal
        open={showLogin}
        onClose={() => setShowLogin(false)}
        onAuth={(user) => { setCurrentUser(user); loadSessions() }}
      />
      <ProfileModal
        open={showProfile}
        onClose={() => setShowProfile(false)}
        user={currentUser}
        onPractice={(topic) => {
          setTopic(topic)
          setView('interview')
          setShowProfile(false)
        }}
        onLoggedOut={() => {
          setCurrentUser(null)
          setSessionId(null)
          setQuestion('')
          setReview('')
          setOutput('')
          setQuestionId(null)
          setRated(false)
          setRatingMsg('')
          setShowProfile(false)
          loadSessions()
        }}
      />
    </div>
  )
}

export default App