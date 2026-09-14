import { useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import { uuidv4 } from '../utils/uuid'
import Button from './ui/Button'
import SimpleMarkdown from './SimpleMarkdown'

/** 将 created_at 格式化为「今天 HH:mm」或「MM-dd HH:mm」 */
function formatMsgTime(createdAt) {
  if (!createdAt) return null
  const d = new Date(createdAt)
  if (Number.isNaN(d.getTime())) return null
  const now = new Date()
  const hh = String(d.getHours()).padStart(2, '0')
  const mm = String(d.getMinutes()).padStart(2, '0')
  const isToday =
    d.getFullYear() === now.getFullYear() &&
    d.getMonth() === now.getMonth() &&
    d.getDate() === now.getDate()
  if (isToday) return `今天 ${hh}:${mm}`
  const mo = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${mo}-${day} ${hh}:${mm}`
}

function FailIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className="shrink-0"
    >
      <circle cx="12" cy="12" r="10" />
      <line x1="12" y1="8" x2="12" y2="12" />
      <line x1="12" y1="16" x2="12.01" y2="16" />
    </svg>
  )
}

function ChatExpandIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className="shrink-0"
    >
      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
    </svg>
  )
}

/**
 * V3-8 报告追问对话区块：内嵌于报告详情（桌面分栏与移动端 BottomSheet 共用）。
 *
 * - 空态折叠入口，展开时拉取对话历史；
 * - 用户右气泡 / assistant 左气泡（SimpleMarkdown 渲染）；
 * - 回车发送、Shift+回车换行；发送中 loading 禁用；失败可重试
 *   （重试复用同一 client_request_id，服务端幂等不会重复调 LLM）。
 */
export default function ReportChatSection({ reportId }) {
  const [expanded, setExpanded] = useState(false)
  const [messages, setMessages] = useState([])
  const [loaded, setLoaded] = useState(false)
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')
  const [failed, setFailed] = useState(null) // { text, requestId, tempId }
  const threadRef = useRef(null)
  const inputRef = useRef(null)

  const resetTextareaHeight = () => {
    if (inputRef.current) inputRef.current.style.height = 'auto'
  }

  // 切换报告时重置对话状态
  useEffect(() => {
    setExpanded(false)
    setMessages([])
    setLoaded(false)
    setInput('')
    setSending(false)
    setError('')
    setFailed(null)
  }, [reportId])

  // 展开时拉取历史
  useEffect(() => {
    if (!expanded || loaded) return
    api(`/api/ai-reports/${reportId}/messages`)
      .then((data) => {
        setMessages(data.messages || [])
        setLoaded(true)
      })
      .catch((err) => setError(err.status === 401 ? '未登录' : err.message || '加载失败'))
  }, [expanded, loaded, reportId])

  // 新消息上屏后滚动到底部（jsdom 无 scrollIntoView，防御性判断）
  useEffect(() => {
    const el = threadRef.current
    if (el && typeof el.scrollTo === 'function') {
      el.scrollTo({ top: el.scrollHeight })
    }
  }, [messages, sending])

  const doSend = async (text, requestId, tempId) => {
    setSending(true)
    setMessages((prev) =>
      prev.map((m) => (m.id === tempId ? { ...m, pending: true, failed: false } : m)),
    )
    try {
      const data = await api(`/api/ai-reports/${reportId}/messages`, {
        method: 'POST',
        body: JSON.stringify({ content: text, client_request_id: requestId }),
      })
      setMessages((prev) => [
        ...prev.filter((m) => m.id !== tempId),
        data.user_message,
        data.assistant_message,
      ])
      setFailed(null)
      resetTextareaHeight()
    } catch {
      setMessages((prev) =>
        prev.map((m) => (m.id === tempId ? { ...m, pending: false, failed: true } : m)),
      )
      setFailed({ text, requestId, tempId })
    } finally {
      setSending(false)
    }
  }

  const handleSend = () => {
    const text = input.trim()
    if (!text || sending) return
    // V3-8b：HTTP 明文 WebView 无 crypto.randomUUID（安全上下文限定），走兼容实现
    const requestId = uuidv4()
    const tempId = `pending-${requestId}`
    setMessages((prev) => [
      ...prev,
      { id: tempId, role: 'user', content: text, pending: true },
    ])
    setInput('')
    resetTextareaHeight()
    doSend(text, requestId, tempId)
  }

  const handleRetry = () => {
    if (!failed || sending) return
    doSend(failed.text, failed.requestId, failed.tempId)
  }

  const handleKeyDown = (e) => {
    // 回车发送、Shift+回车换行；输入法组合中不触发发送
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      handleSend()
    }
  }

  const metaLine = (m, _isUser) => {
    const parts = []
    const time = formatMsgTime(m.created_at)
    if (time) parts.push(time)
    if (m.prompt_tokens != null || m.completion_tokens != null) {
      const p = m.prompt_tokens ?? 0
      const c = m.completion_tokens ?? 0
      parts.push(`${p + c} tokens`)
    }
    if (m.cost_estimate != null && m.cost_estimate !== '') {
      parts.push(`¥${m.cost_estimate}`)
    }
    return parts.length ? parts.join(' · ') : null
  }

  const userBubbleClass = (m) => {
    const base = 'max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-sm px-3 py-2 text-sm text-white'
    if (m.failed) return `${base} border-2 border-red-300 bg-indigo-600/70`
    if (m.pending) return `${base} bg-indigo-600 opacity-70`
    return `${base} bg-indigo-600`
  }

  if (!expanded) {
    return (
      <button
        type="button"
        data-testid="chat-expand-btn"
        onClick={() => setExpanded(true)}
        className="mt-4 flex min-h-[44px] w-full items-center justify-center gap-1.5 rounded-lg border border-dashed border-indigo-300 bg-indigo-50 px-4 py-3 text-sm font-medium text-indigo-700 hover:bg-indigo-100"
      >
        <ChatExpandIcon />
        追问 AI 教练
      </button>
    )
  }

  return (
    <div
      data-testid="chat-section"
      className="mt-4 rounded-lg border border-indigo-200 bg-indigo-50/50 p-4"
    >
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-900">追问 AI 教练</h3>
        <button
          type="button"
          data-testid="chat-collapse-btn"
          onClick={() => setExpanded(false)}
          className="text-xs text-gray-600 hover:text-gray-700"
        >
          收起
        </button>
      </div>

      <div
        ref={threadRef}
        data-testid="chat-thread"
        className="mb-3 max-h-80 space-y-2 overflow-y-auto pr-1"
      >
        <p className="text-xs text-gray-600" data-testid="chat-memory-hint">
          AI 回答会参考你的长期记忆（须知 / 对话要点 / 训练统计）
        </p>
        {messages.length === 0 && !sending && (
          <p className="text-xs text-gray-600">
            对报告有疑问？直接提问，教练会结合报告内容解答。
          </p>
        )}
        {error && !failed && (
          <p role="alert" className="text-xs text-red-600">{error}</p>
        )}
        {messages.map((m) =>
          m.role === 'user' ? (
            <div key={m.id} className="flex justify-end">
              <div className="max-w-[85%]">
                <div
                  data-testid={`chat-msg-user-${m.id}`}
                  className={userBubbleClass(m)}
                >
                  {m.content}
                </div>
                {m.failed && (
                  <div className="mt-0.5 flex items-center justify-end gap-1.5 text-xs text-red-600">
                    <FailIcon />
                    发送失败
                    <button
                      type="button"
                      data-testid="chat-retry"
                      onClick={handleRetry}
                      disabled={sending}
                      className="min-h-[36px] rounded-lg px-2 font-medium underline disabled:opacity-40"
                    >
                      重试
                    </button>
                  </div>
                )}
                {metaLine(m, true) && (
                  <p className="mt-0.5 text-right text-xs text-gray-600">{metaLine(m, true)}</p>
                )}
              </div>
            </div>
          ) : (
            <div key={m.id} className="flex justify-start">
              <div className="max-w-[85%]">
                <div
                  data-testid={`chat-msg-assistant-${m.id}`}
                  className="rounded-2xl rounded-bl-sm border border-gray-200 bg-white px-3 py-2 text-sm text-gray-800"
                >
                  <SimpleMarkdown text={m.content} />
                </div>
                {metaLine(m, false) && (
                  <p className="mt-0.5 text-xs text-gray-600">{metaLine(m, false)}</p>
                )}
              </div>
            </div>
          ),
        )}
        {sending && (
          <div className="flex justify-start">
            <div
              data-testid="chat-thinking"
              className="rounded-2xl rounded-bl-sm border border-gray-200 bg-white px-3 py-2 text-sm text-gray-500"
            >
              教练思考中…
            </div>
          </div>
        )}
      </div>

      <div className="flex items-end gap-2">
        <textarea
          ref={inputRef}
          data-testid="chat-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onInput={(e) => {
            e.target.style.height = 'auto'
            e.target.style.height = `${Math.min(e.target.scrollHeight, 6 * 24)}px`
          }}
          onKeyDown={handleKeyDown}
          rows={1}
          maxLength={1000}
          placeholder="输入你的问题（回车发送，Shift+回车换行）"
          className="max-h-36 min-h-[44px] min-w-0 flex-1 resize-none rounded-md border border-gray-300 bg-white px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none"
        />
        <Button
          variant="primary"
          testId="chat-send"
          onClick={handleSend}
          disabled={sending || !input.trim()}
        >
          {sending ? '发送中…' : '发送'}
        </Button>
      </div>
    </div>
  )
}
