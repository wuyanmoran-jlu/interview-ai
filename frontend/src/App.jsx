import { useState } from 'react'
import Editor from '@monaco-editor/react'
import ReactMarkdown from 'react-markdown'
import axios from 'axios'
import './App.css'

const LANGUAGES = [
  { value: 'python', label: 'Python' },
  { value: 'javascript', label: 'JavaScript' },
  { value: 'java', label: 'Java' },
  { value: 'cpp', label: 'C++' },
]

function App() {
  const [sessionId, setSessionId] = useState(null)
  const [question, setQuestion] = useState('')
  const [code, setCode] = useState('# 在这里写代码\n')
  const [output, setOutput] = useState('')
  const [review, setReview] = useState('')
  const [loading, setLoading] = useState(false)
  const [language, setLanguage] = useState('python')
  const [answerText, setAnswerText] = useState('')
  const [stdin, setStdin] = useState('')

  const startInterview = async () => {
    try {
      setLoading(true)
      const res = await axios.post('http://localhost:8000/interview/start', {
        topic: '算法',
        difficulty: '中等',
        language: language,
      })
      setSessionId(res.data.session_id)
      setQuestion(res.data.question)
      setOutput('')
      setReview('')
      setAnswerText('')
      setStdin('')
    } catch (err) {
      alert('启动面试失败：' + err.message)
    } finally {
      setLoading(false)
    }
  }

  const runCode = async () => {
    if (!sessionId) return alert('请先开始面试')
    try {
      setLoading(true)
      const res = await axios.post('http://localhost:8000/interview/run', {
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

  const reviewCode = async () => {
    if (!sessionId) return alert('请先开始面试')
    try {
      setLoading(true)
      const res = await axios.post('http://localhost:8000/interview/review', {
        session_id: sessionId,
        source_code: code,
        language: language,
      })
      setReview(res.data.review)
      const r = res.data.run_result
      setOutput(
        '=== 标准输出 ===\n' + (r.stdout || '(无)') +
        '\n\n=== 错误输出 ===\n' + (r.stderr || '(无)') +
        (r.signal ? '\n\n=== 信号 ===\n' + r.signal : '') +
        (r.code !== null && r.code !== 0 ? '\n\n=== 退出码 ===\n' + r.code : '')
      )
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
      const res = await axios.post('http://localhost:8000/interview/answer', {
        session_id: sessionId,
        answer: answerText,
      })
      setReview(res.data.reply)
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
      const res = await axios.post('http://localhost:8000/interview/evaluate', {
        session_id: sessionId,
      })
      setReview(res.data.evaluation)
      setQuestion('')
    } catch (err) {
      alert('获取评价失败：' + err.message)
    } finally {
      setLoading(false)
    }
  }

  const monacoLang = language === 'cpp' ? 'cpp' : language

  return (
    <div className="app">
      <header className="header">
        <h1>AI 面试模拟器</h1>
        <div className="header-controls">
          <div className="lang-selector">
            <label>语言：</label>
            <select value={language} onChange={(e) => setLanguage(e.target.value)}>
              {LANGUAGES.map(l => (
                <option key={l.value} value={l.value}>{l.label}</option>
              ))}
            </select>
          </div>
          <button onClick={startInterview} disabled={loading}>
            开始新面试
          </button>
        </div>
      </header>
      <div className="main">
        <div className="left-panel">
          <div className="question-box">
            <h3>📋 题目</h3>
            <div className="markdown-content">
              {question ? (
                <ReactMarkdown>{question}</ReactMarkdown>
              ) : (
                <p className="placeholder">点击"开始新面试"获取题目</p>
              )}
            </div>
          </div>
          <div className="stdin-box">
            <h3>⌨ 自定义输入 (stdin)</h3>
            <textarea
              className="stdin-input"
              rows={3}
              placeholder="输入测试数据（对应题目中的示例输入），每行一个值..."
              value={stdin}
              onChange={(e) => setStdin(e.target.value)}
              disabled={loading}
            />
          </div>
          <div className="output-box">
            <h3>🖥 运行输出</h3>
            <pre>{output || '点击 ▶ 运行 查看代码执行结果'}</pre>
          </div>
        </div>
        <div className="right-panel">
          <div className="editor-container">
            <Editor
              height="50vh"
              language={monacoLang}
              value={code}
              onChange={(val) => setCode(val)}
              theme="vs-dark"
            />
          </div>
          <div className="button-group">
            <button onClick={runCode} disabled={loading || !sessionId}>▶ 运行</button>
            <button onClick={reviewCode} disabled={loading || !sessionId}>🧠 提交并获取点评</button>
            <button onClick={endInterview} disabled={loading || !sessionId}>🏁 结束面试</button>
          </div>
          <div className="review-box">
            <h3>🤖 AI 点评</h3>
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
              <textarea
                className="answer-input"
                rows={4}
                placeholder="在这里输入你对面试官追问的回答..."
                value={answerText}
                onChange={(e) => setAnswerText(e.target.value)}
                disabled={loading}
              />
              <button
                className="answer-btn"
                onClick={sendAnswer}
                disabled={loading || !answerText.trim()}
              >
                📤 发送回答
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default App