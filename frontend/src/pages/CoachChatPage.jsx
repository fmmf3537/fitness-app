import { useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import SimpleMarkdown from '../components/SimpleMarkdown'
import Button from '../components/ui/Button'
import Icon from '../components/ui/Icon'
import ConfirmDialog from '../components/ui/ConfirmDialog'
import EmptyState from '../components/ui/EmptyState'
import ErrorState from '../components/ui/ErrorState'
import Skeleton from '../components/ui/Skeleton'
import useIsMobile from '../hooks/useIsMobile'
import { uuidv4 } from '../utils/uuid'

const QUICK_QUESTIONS = [
  '复盘我最近一次训练',
  '解读我最近的睡眠表现',
  '下次训练应该注意什么？',
  '分析我的体重与体脂趋势',
]
const FAILED_DRAFT_KEY = 'fh_coach_failed_message'

function readFailedDraft() {
  try {
    const draft = JSON.parse(localStorage.getItem(FAILED_DRAFT_KEY) || 'null')
    return draft?.text && draft?.requestId && draft?.tempId ? draft : null
  } catch {
    return null
  }
}

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

function ContextRefs({ refs }) {
  if (!refs) return null
  const parts = []
  if (refs.recent_workouts) parts.push(`最近 ${refs.recent_workouts} 次训练`)
  if (refs.upcoming_plan_days) parts.push(`未来 ${refs.upcoming_plan_days} 个计划日`)
  if (refs.movement_records?.length) parts.push(`${refs.movement_records.join('、')}纪录`)
  if (refs.recovery_days) parts.push(`近 ${refs.recovery_days} 天恢复数据`)
  if (refs.preferences) parts.push(`${refs.preferences} 条须知`)
  if (refs.memories) parts.push(`${refs.memories} 条对话记忆`)
  if (!parts.length) return null
  return (
    <div data-testid="chat-context-refs" className="mt-1 rounded-lg bg-indigo-50 px-2 py-1.5 text-[11px] leading-5 text-indigo-700 dark:bg-indigo-950/50 dark:text-indigo-300">
      <span>参考：{parts.join(' · ')}</span>
      {(refs.training_data_through || refs.plan_fetched_at) && (
        <span className="block text-gray-500 dark:text-gray-400">
          {refs.training_data_through ? `训练数据截至 ${refs.training_data_through}` : ''}
          {refs.training_data_through && refs.plan_fetched_at ? ' · ' : ''}
          {refs.plan_fetched_at ? `计划更新于 ${refs.plan_fetched_at.replace('T', ' ').slice(0, 16)}` : ''}
        </span>
      )}
    </div>
  )
}

/**
 * V5-6 独立教练聊天页：不绑 report_id，支持历史 / 发送 / 清空。
 * UI 模式借鉴 ReportChatSection（气泡、回车发送、失败重试复用 client_request_id）。
 * UIX-06：embedded 时由 CoachHubPage 承载页首，本页仅渲染聊天视图。
 */
export default function CoachChatPage({ embedded = false }) {
  const isMobile = useIsMobile()
  const [messages, setMessages] = useState([])
  const [loaded, setLoaded] = useState(false)
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')
  const [failed, setFailed] = useState(null) // { text, requestId, tempId }
  const [clearOpen, setClearOpen] = useState(false)
  const threadRef = useRef(null)
  const inputRef = useRef(null)

  const resetTextareaHeight = () => {
    if (inputRef.current) inputRef.current.style.height = 'auto'
  }

  const load = () => {
    setError('')
    return api('/api/coach/chat')
      .then((data) => {
        const list = data.messages || []
        list.sort((a, b) => String(a.created_at || '').localeCompare(String(b.created_at || '')))
        const draft = readFailedDraft()
        setMessages(draft ? [...list, { id: draft.tempId, role: 'user', content: draft.text, failed: true }] : list)
        setFailed(draft)
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

  const doSend = async (text, requestId, tempId) => {
    setSending(true)
    setError('')
    // 重试时把该临时消息恢复为 pending
    setMessages((prev) =>
      prev.map((m) => (m.id === tempId ? { ...m, pending: true, failed: false } : m)),
    )
    try {
      const data = await api('/api/coach/chat', {
        method: 'POST',
        body: JSON.stringify({ content: text, client_request_id: requestId }),
      })
      // 用服务端消息替换临时气泡
      setMessages((prev) => [
        ...prev.filter((m) => m.id !== tempId),
        data.user_message,
        data.assistant_message,
      ])
      setFailed(null)
      localStorage.removeItem(FAILED_DRAFT_KEY)
      resetTextareaHeight()
    } catch {
      setMessages((prev) =>
        prev.map((m) => (m.id === tempId ? { ...m, pending: false, failed: true } : m)),
      )
      const draft = { text, requestId, tempId }
      setFailed(draft)
      localStorage.setItem(FAILED_DRAFT_KEY, JSON.stringify(draft))
    } finally {
      setSending(false)
    }
  }

  const handleSend = () => {
    const text = input.trim()
    if (!text || sending) return
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

  const handleClearConfirm = async () => {
    setClearOpen(false)
    setError('')
    try {
      await api('/api/coach/chat', { method: 'DELETE' })
      setMessages([])
      setFailed(null)
      localStorage.removeItem(FAILED_DRAFT_KEY)
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

  const metaLine = (m, isUser) => {
    const parts = []
    const time = formatMsgTime(m.created_at)
    if (time) parts.push(time)
    // assistant 仅标注来源，不上屏用量与费用
    if (!isUser) parts.push('由 AI 教练生成')
    return parts.length ? parts.join(' · ') : null
  }

  const userBubbleClass = (m) => {
    const base = 'whitespace-pre-wrap rounded-2xl rounded-br-sm px-3 py-2 text-sm text-white shadow-glow'
    if (m.failed) return `${base} border-2 border-red-300 bg-brand-600/70`
    if (m.pending) return `${base} bg-gradient-brand opacity-70`
    return `${base} bg-gradient-brand`
  }

  return (
    <div
      data-testid="coach-chat-page"
      className={`mx-auto flex h-full flex-col ${isMobile ? 'max-w-2xl' : 'max-w-3xl'}`}
    >
      {!embedded && (
        <div className="flex items-center justify-between border-b bg-white dark:bg-gray-900 px-4 py-3">
          <h1 className="text-xl font-bold text-gray-900 dark:text-gray-100">跟教练聊聊</h1>
          <Button variant="danger" testId="chat-clear-btn" onClick={() => setClearOpen(true)}>
            清空对话
          </Button>
        </div>
      )}

      {embedded && (
        <div className="flex justify-end pb-2">
          <Button variant="danger" testId="chat-clear-btn" onClick={() => setClearOpen(true)}>
            清空
          </Button>
        </div>
      )}

      <div
        ref={threadRef}
        data-testid="chat-thread"
        className="flex-1 space-y-3 overflow-y-auto py-2 sm:p-4"
      >
        {!loaded && (
          <div className="space-y-3" data-testid="chat-loading">
            <Skeleton className="h-10 w-2/3 rounded-2xl" />
            <Skeleton className="ml-auto h-10 w-1/2 rounded-2xl" />
            <Skeleton className="h-10 w-3/5 rounded-2xl" />
          </div>
        )}
        {loaded && messages.length === 0 && !sending && (
          <div className="mx-auto w-full max-w-xl py-2 sm:py-8">
            <div className="mb-4 rounded-[20px] border border-line bg-gradient-soft p-5 text-center shadow-card dark:border-gray-800 dark:from-indigo-950/60 dark:to-gray-900 sm:mb-6 sm:p-6">
              <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-brand text-white shadow-glow"><Icon name="sparkle" size={22} /></div>
            <EmptyState
              testId="chat-empty"
              title="跟教练说点什么吧"
              description="比如「我深蹲时膝盖疼，下周训练怎么调？」"
            />
            </div>
            <p className="mb-2 text-xs font-semibold text-ink-400 dark:text-gray-300">快捷提问</p>
            <div className="grid grid-cols-2 gap-2">
              {QUICK_QUESTIONS.map((question) => (
                <button key={question} type="button" onClick={() => setInput(question)} className="flex min-h-11 items-center gap-1 rounded-[14px] border border-line bg-white px-3 text-left text-xs font-medium text-ink-600 shadow-card transition hover:-translate-y-0.5 hover:border-brand-300 hover:text-brand-700 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-200 sm:text-sm">
                  {question} <span aria-hidden="true" className="float-right text-indigo-500">→</span>
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((m) =>
          m.role === 'user' ? (
            <div key={m.id} className="flex justify-end" data-testid={`chat-msg-wrap-user-${m.id}`}>
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
                  <p className="mt-0.5 text-right text-xs text-gray-600 dark:text-gray-400">{metaLine(m, true)}</p>
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
                  className="rounded-2xl rounded-bl-sm border border-line bg-white px-3 py-2 text-sm text-ink-900 shadow-card dark:border-gray-800 dark:bg-gray-900 dark:text-gray-200"
                >
                  <SimpleMarkdown text={m.content} />
                </div>
                <ContextRefs refs={m.context_refs} />
                {metaLine(m, false) && (
                  <p className="mt-0.5 text-xs text-gray-600 dark:text-gray-400">{metaLine(m, false)}</p>
                )}
              </div>
            </div>
          ),
        )}
        {sending && (
          <div className="flex justify-start">
            <div
              data-testid="chat-thinking"
              className="rounded-2xl rounded-bl-sm border border-line bg-white px-3 py-2 text-sm text-ink-400 shadow-card dark:border-gray-800 dark:bg-gray-900"
            >
              <span className="mr-2">教练思考中</span>
              <span className="inline-flex gap-1" aria-hidden="true"><i className="thinking-dot">●</i><i className="thinking-dot">●</i><i className="thinking-dot">●</i></span>
            </div>
          </div>
        )}
      </div>

      {error && (
        <div className="px-4">
          <ErrorState message={error} onRetry={load} testId="chat-load-error" />
        </div>
      )}

      <div className="sticky bottom-0 flex items-end gap-2 rounded-2xl border border-line bg-white p-2 shadow-lift dark:border-gray-800 dark:bg-gray-900">
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
          maxLength={4000}
          placeholder="输入你的问题（回车发送，Shift+回车换行）"
          className="max-h-36 min-h-[44px] min-w-0 flex-1 resize-none rounded-xl border-0 bg-transparent px-2 py-2 text-sm focus:outline-none"
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

      <ConfirmDialog
        open={clearOpen}
        title="清空所有对话？"
        description="此操作不可恢复，与教练的聊天记录将被删除；已经整理出的长期记忆不会自动删除。"
        confirmText="确认"
        danger
        onConfirm={handleClearConfirm}
        onCancel={() => setClearOpen(false)}
      />
    </div>
  )
}
