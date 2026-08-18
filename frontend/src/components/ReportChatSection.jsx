import { useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import SimpleMarkdown from './SimpleMarkdown'

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
  const [failed, setFailed] = useState(null) // { text, requestId }
  const threadRef = useRef(null)

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

  const doSend = async (text, requestId) => {
    setSending(true)
    setError('')
    try {
      const data = await api(`/api/ai-reports/${reportId}/messages`, {
        method: 'POST',
        body: JSON.stringify({ content: text, client_request_id: requestId }),
      })
      setMessages((prev) => [...prev, data.user_message, data.assistant_message])
      setInput('')
      setFailed(null)
    } catch (err) {
      setError(err.status === 401 ? '未登录' : err.message || '发送失败，请重试')
      setFailed({ text, requestId })
    } finally {
      setSending(false)
    }
  }

  const handleSend = () => {
    const text = input.trim()
    if (!text || sending) return
    doSend(text, crypto.randomUUID())
  }

  const handleRetry = () => {
    if (!failed || sending) return
    doSend(failed.text, failed.requestId)
  }

  const handleKeyDown = (e) => {
    // 回车发送、Shift+回车换行；输入法组合中不触发发送
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      handleSend()
    }
  }

  if (!expanded) {
    return (
      <button
        type="button"
        data-testid="chat-expand-btn"
        onClick={() => setExpanded(true)}
        className="mt-4 w-full rounded-lg border border-dashed border-indigo-300 bg-indigo-50 px-4 py-3 text-sm font-medium text-indigo-700 hover:bg-indigo-100"
      >
        💬 追问 AI 教练
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
          className="text-xs text-gray-500 hover:text-gray-700"
        >
          收起
        </button>
      </div>

      <div
        ref={threadRef}
        data-testid="chat-thread"
        className="mb-3 max-h-80 space-y-2 overflow-y-auto pr-1"
      >
        {messages.length === 0 && !sending && (
          <p className="text-xs text-gray-500">
            对报告有疑问？直接提问，教练会结合报告内容解答。
          </p>
        )}
        {messages.map((m) =>
          m.role === 'user' ? (
            <div key={m.id} className="flex justify-end">
              <div
                data-testid={`chat-msg-user-${m.id}`}
                className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-sm bg-indigo-600 px-3 py-2 text-sm text-white"
              >
                {m.content}
              </div>
            </div>
          ) : (
            <div key={m.id} className="flex justify-start">
              <div
                data-testid={`chat-msg-assistant-${m.id}`}
                className="max-w-[85%] rounded-2xl rounded-bl-sm border border-gray-200 bg-white px-3 py-2 text-sm text-gray-800"
              >
                <SimpleMarkdown text={m.content} />
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

      {error && (
        <p role="alert" className="mb-2 flex items-center gap-2 text-xs text-red-600">
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

      <div className="flex items-end gap-2">
        <textarea
          data-testid="chat-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          rows={2}
          maxLength={1000}
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
