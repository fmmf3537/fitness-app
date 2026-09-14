import { useContext, useEffect, useRef, useState } from 'react'
import { api, ApiError } from '../api/client'
import Button from './ui/Button'
import { ToastContext } from './ui/useToast'

const POLL_INTERVAL_MS = 3000

function today() {
  const d = new Date()
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  return `${d.getFullYear()}-${mm}-${dd}`
}

function failureText(msg) {
  const text = msg || '未知错误'
  if (/429|too many|too frequent/i.test(text)) {
    return `同步失败：${text}（佳明接口限频，请稍后重试）`
  }
  return `同步失败：${text}`
}

export default function SyncButton({ onSynced }) {
  // 生产路径由 Layout ToastProvider 注入；单测直接挂载时兜底 no-op
  const toastCtx = useContext(ToastContext)
  const toast = toastCtx?.toast
  const [syncing, setSyncing] = useState(false)
  const [error, setError] = useState('')
  const timerRef = useRef(null)

  useEffect(() => () => clearTimeout(timerRef.current), [])

  const poll = () => {
    timerRef.current = setTimeout(async () => {
      try {
        const st = await api('/api/sync/status')
        if (st.running) {
          poll()
          return
        }
        setSyncing(false)
        if (st.status === 'success') {
          const d = st.result?.detail || {}
          toast?.(`同步完成：训练 ${d.workouts ?? 0} 条，待确认 ${d.candidates ?? 0} 条`)
          onSynced?.()
        } else {
          setError(failureText(st.error))
        }
      } catch (err) {
        setSyncing(false)
        setError(failureText(err.message))
      }
    }, POLL_INTERVAL_MS)
  }

  const start = async () => {
    if (syncing) return
    setSyncing(true)
    setError('')
    try {
      await api(`/api/sync/${today()}`, { method: 'POST' })
      poll()
    } catch (err) {
      setSyncing(false)
      if (err instanceof ApiError && err.status === 409) {
        setError('已有同步任务进行中，请稍候')
      } else {
        setError(failureText(err.message))
      }
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button
        variant="primary"
        ariaLabel="立即同步"
        onClick={start}
        disabled={syncing}
      >
        {syncing ? '同步中…' : '立即同步'}
      </Button>
      {syncing && (
        <span role="status" className="text-sm text-gray-600">
          同步中（约 1-2 分钟，含 AI 点评生成）
        </span>
      )}
      {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
    </div>
  )
}
