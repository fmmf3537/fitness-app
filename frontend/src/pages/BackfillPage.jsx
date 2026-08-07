import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'

const PHASE_LABELS = {
  idle: '空闲',
  xunji: '训记导入中',
  garmin_activities: '佳明活动导入中',
  garmin_daily: '佳明健康导入中',
  fusion: '数据融合中',
  done: '已完成',
  error: '出错',
}

const SOURCES = [
  { key: 'xunji', testId: 'progress-xunji', label: '训记训练' },
  { key: 'garmin_activities', testId: 'progress-garmin_activity', label: '佳明活动' },
  { key: 'garmin_daily', testId: 'progress-garmin_daily', label: '佳明每日健康' },
  { key: 'fusion', testId: 'progress-fusion', label: '数据融合' },
]

function formatEta(seconds) {
  if (seconds == null || seconds <= 0) return '-'
  const mins = Math.round(seconds / 60)
  if (mins < 60) return `约 ${mins} 分钟`
  return `约 ${Math.floor(mins / 60)} 小时 ${mins % 60} 分钟`
}

function sourceProgress(key, detail) {
  if (!detail) return { text: '-', percent: 0 }
  if (key === 'garmin_activities') {
    return {
      text: detail.finished
        ? `已完成 · ${detail.pages} 页 / ${detail.activities} 条活动`
        : `未完成 · ${detail.pages} 页 / ${detail.activities} 条活动`,
      percent: detail.finished ? 100 : 0,
    }
  }
  const total = detail.total || 0
  const done = detail.done || 0
  return {
    text: `${done} / ${total}`,
    percent: total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 0,
  }
}

export default function BackfillPage() {
  const [status, setStatus] = useState(null)
  const [polling, setPolling] = useState(false)
  const [starting, setStarting] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')

  const fetchStatus = useCallback(() => {
    return api('/api/backfill/status')
      .then((data) => {
        setStatus(data)
        if (!data.running) setPolling(false)
      })
      .catch((err) => setError(err.status === 401 ? '未登录' : err.message))
  }, [])

  useEffect(() => {
    fetchStatus()
  }, [fetchStatus])

  useEffect(() => {
    if (!polling) return undefined
    const timer = setInterval(fetchStatus, 3000)
    return () => clearInterval(timer)
  }, [polling, fetchStatus])

  const handleStart = () => {
    setStarting(true)
    setError('')
    setMessage('')
    api('/api/backfill/start', { method: 'POST' })
      .then((data) => {
        setMessage(data.message || '已启动')
        setPolling(true)
      })
      .catch((err) => setError(err.status === 401 ? '未登录' : err.message))
      .finally(() => setStarting(false))
  }

  const running = Boolean(status?.running)

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold text-gray-900">历史数据导入</h1>
        <button
          data-testid="backfill-start"
          onClick={handleStart}
          disabled={starting || running}
          className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {running ? '导入中…' : '开始导入'}
        </button>
      </div>

      {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
      {message && <p className="text-sm text-green-600">{message}</p>}

      {status && (
        <div
          data-testid="backfill-status"
          className="space-y-4 rounded-lg border border-gray-200 bg-white p-4 shadow-sm"
        >
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-gray-700">
            <span>
              整体状态：
              <span className="font-medium text-gray-900">
                {running ? '运行中' : PHASE_LABELS[status.phase] || status.phase || '-'}
              </span>
            </span>
            <span>阶段：{PHASE_LABELS[status.phase] || status.phase || '-'}</span>
            <span>总进度：{status.percent ?? 0}%</span>
            <span>预计剩余：{formatEta(status.eta_seconds)}</span>
          </div>

          <div className="h-2 w-full overflow-hidden rounded-full bg-gray-200">
            <div
              className="h-full bg-indigo-600 transition-all"
              style={{ width: `${status.percent ?? 0}%` }}
            />
          </div>

          <div className="space-y-3">
            {SOURCES.map(({ key, testId, label }) => {
              const progress = sourceProgress(key, status.details?.[key])
              return (
                <div key={key} data-testid={testId} className="text-sm">
                  <div className="mb-1 flex items-center justify-between text-gray-700">
                    <span className="font-medium text-gray-900">{label}</span>
                    <span>{progress.text}</span>
                  </div>
                  <div className="h-1.5 w-full overflow-hidden rounded-full bg-gray-200">
                    <div
                      className="h-full bg-indigo-500 transition-all"
                      style={{ width: `${progress.percent}%` }}
                    />
                  </div>
                </div>
              )
            })}
          </div>

          {status.errors?.length > 0 && (
            <div className="rounded-md bg-red-50 p-3 text-xs text-red-700">
              <p className="mb-1 font-medium">错误（{status.errors.length}）：</p>
              <ul className="list-inside list-disc space-y-0.5">
                {status.errors.map((e, i) => (
                  <li key={i}>{e}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
