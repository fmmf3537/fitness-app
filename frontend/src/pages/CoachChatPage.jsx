import { useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import SimpleMarkdown from '../components/SimpleMarkdown'
import useIsMobile from '../hooks/useIsMobile'
import { uuidv4 } from '../utils/uuid'

/**
 * V5-6 独立教练聊天页：不绑 report_id，支持历史 / 发送 / 清空。
 * UI 模式借鉴 ReportChatSection（气泡、回车发送、失败重试复用 client_request_id）。
 */
export default function CoachChatPage() {
  const isMobile = useIsMobile()
  const [messages, setMessages] = useState([])
  const [loaded, setLoaded] = useState(false)
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')
  const [failed, setFailed] = useState(null) // { text, requestId }
  const threadRef = useRef(null)

  const load = () => {
    setError('')
    return api('/api/coach/chat')
      .then((data) => {
        const list = data.messages || []
        list.sort((a, b) => String(a.created_at || '').localeCompare(String(b.created_at || '')))
        setMessages(list)
        setLoaded(true)
      })
      .catch((err) => {
        setError(err.status === 401 || err.status === 404 ? '未登录' : err.message || '加载失败')
        setLoaded(true)
      })
  }

  useEffect(() => {
    load()
  }, [])

  useEffect(() => {
    const el = threadRef.current
    if (el && typeof el.scrollTo === 'function') {
      el.scrollTo({ top: el.scrollHeight })
    }
  }, [messages, sending])

  const doSend = async (text, requestId) => {
    setSending(true)
    setError('')
    try {
      const data = await api('/api/coach/chat', {
        method: 'POST',
        body: JSON.stringify({ content: text, client_request_id: requestId }),
      })
      setMessages((prev) => [...prev, data.user_message, data.assistant_message])
      setInput('')
      setFailed(null)
    } catch (err) {
      setError(err.status === 401 || err.status === 404 ? '未登录' : err.message || '发送失败，请重试')
      setFailed({ text, requestId })
    } finally {
      setSending(false)
    }
  }

  const handleSend = () => {
    const text = input.trim()
    if (!text || sending) return
    doSend(text, uuidv4())
  }

  const handleRetry = () => {
    if (!failed || sending) return
    doSend(failed.text, failed.requestId)
  }

  const handleClear = async () => {
    if (!window.confirm('确定清空所有对话？此操作不可恢复')) return
    setError('')
    try {
      await api('/api/coach/chat', { method: 'DELETE' })
      setMessages([])
      setFailed(null)
    } catch (err) {
      setError(err.status === 401 || err.status === 404 ? '未登录' : err.message || '清空失败')
    }
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      handleSend()
    }
  }

  const metaLine = (m) => {
    const parts = []
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

  return (
    <div
      data-testid="coach-chat-page"
      className={`mx-auto flex h-full flex-col ${isMobile ? 'max-w-2xl' : 'max-w-3xl'}`}
    >
      <div className="flex items-center justify-between border-b bg-white px-4 py-3">
        <h1 className="text-xl font-bold text-gray-900">跟教练聊聊</h1>
        <button
          type="button"
          data-testid="chat-clear-btn"
          onClick={handleClear}
          className="rounded-md bg-red-600 px-3 py-2 text-sm font-medium text-white hover:bg-red-700"
        >
          清空对话
        </button>
      </div>

      <div
        ref={threadRef}
        data-testid="chat-thread"
        className="flex-1 space-y-3 overflow-y-auto p-4"
      >
        {!loaded && <p className="text-sm text-gray-500">加载中…</p>}
        {loaded && messages.length === 0 && !sending && (
          <p
            data-testid="chat-empty"
            className="py-12 text-center text-sm text-gray-500"
          >
            跟教练说点什么吧——比如「我深蹲时膝盖疼，下周训练怎么调？」
          </p>
        )}
        {messages.map((m) =>
          m.role === 'user' ? (
            <div key={m.id} className="flex justify-end" data-testid={`chat-msg-wrap-user-${m.id}`}>
              <div className="max-w-[85%]">
                <div
                  data-testid={`chat-msg-user-${m.id}`}
                  className="whitespace-pre-wrap rounded-2xl rounded-br-sm bg-indigo-600 px-3 py-2 text-sm text-white"
                >
                  {m.content}
                </div>
                {metaLine(m) && (
                  <p className="mt-0.5 text-right text-xs text-gray-400">{metaLine(m)}</p>
                )}
              </div>
            </div>
          ) : (
            <div
              key={m.id}
              className="flex justify-start"
              data-testid={`chat-msg-wrap-assistant-${m.id}`}
            >
              <div className="max-w-[85%]">
                <div
                  data-testid={`chat-msg-assistant-${m.id}`}
                  className="rounded-2xl rounded-bl-sm bg-gray-100 px-3 py-2 text-sm text-gray-800"
                >
                  <SimpleMarkdown text={m.content} />
                </div>
                {metaLine(m) && (
                  <p className="mt-0.5 text-xs text-gray-400">{metaLine(m)}</p>
                )}
              </div>
            </div>
          ),
        )}
        {sending && (
          <div className="flex justify-start">
            <div
              data-testid="chat-thinking"
              className="rounded-2xl rounded-bl-sm bg-gray-100 px-3 py-2 text-sm text-gray-500"
            >
              教练思考中…
            </div>
          </div>
        )}
      </div>

      {error && (
        <p role="alert" className="flex items-center gap-2 px-4 text-sm text-red-600">
          {error}
          {failed && (
            <button
              type="button"
              data-testid="chat-retry"
              onClick={handleRetry}
              disabled={sending}
              className="rounded border border-red-300 px-2 py-0.5 text-red-600 hover:bg-red-50 disabled:opacity-40"
            >
              重试
            </button>
          )}
        </p>
      )}

      <div className="flex items-end gap-2 border-t bg-white p-3">
        <textarea
          data-testid="chat-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          rows={3}
          maxLength={4000}
          placeholder="输入你的问题（回车发送，Shift+回车换行）"
          className="min-w-0 flex-1 resize-none rounded-md border border-gray-300 bg-white px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none"
        />
        <button
          type="button"
          data-testid="chat-send"
          onClick={handleSend}
          disabled={sending || !input.trim()}
          className="shrink-0 rounded-md bg-green-600 px-3 py-2 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-50"
        >
          {sending ? '发送中…' : '发送'}
        </button>
      </div>
    </div>
  )
}
