import { useEffect, useState } from 'react'
import { api } from '../api/client'

function formatDateInput(date) {
  return date.toISOString().slice(0, 10)
}

function SimpleMarkdown({ text }) {
  return (
    <div className="space-y-2">
      {(text || '').split('\n').map((line, i) => {
        if (line.startsWith('## ')) {
          return <h2 key={i} className="text-lg font-bold text-gray-900">{line.slice(3)}</h2>
        }
        if (line.startsWith('# ')) {
          return <h1 key={i} className="text-xl font-bold text-gray-900">{line.slice(2)}</h1>
        }
        if (line.trim() === '') {
          return <br key={i} />
        }
        return <p key={i} className="text-gray-800">{line}</p>
      })}
    </div>
  )
}

export default function AIReportsPage() {
  const [date, setDate] = useState(formatDateInput(new Date()))
  const [reports, setReports] = useState([])
  const [selected, setSelected] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    setLoading(true)
    setSelected(null)
    setError('')
    api(`/api/ai-reports?date=${date}`)
      .then((data) => {
        setReports(data.reports || [])
      })
      .catch((err) => setError(err.status === 401 ? '未登录' : err.message))
      .finally(() => setLoading(false))
  }, [date])

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold text-gray-900">AI 训练点评</h1>
        <input
          type="date"
          value={date}
          onChange={(e) => setDate(e.target.value)}
          className="rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none"
          data-testid="date-input"
        />
      </div>

      {loading && <p className="text-sm text-gray-500">加载中…</p>}
      {error && <p role="alert" className="text-sm text-red-600">{error}</p>}

      {!loading && !error && reports.length === 0 && (
        <p className="text-sm text-gray-500">当日暂无 AI 点评</p>
      )}

      <div className="grid gap-4 md:grid-cols-3">
        <div className="space-y-3 md:col-span-1">
          {reports.map((r) => (
            <button
              key={r.id}
              onClick={() => setSelected(r)}
              data-testid={`report-card-${r.id}`}
              className={`w-full rounded-lg border p-4 text-left shadow-sm transition ${
                selected?.id === r.id
                  ? 'border-indigo-500 bg-indigo-50'
                  : 'border-gray-200 bg-white hover:bg-gray-50'
              }`}
            >
              <p className="font-medium text-gray-900">
                {r.workout_title || '未命名训练'}
              </p>
              <p className="mt-1 text-xs text-gray-500">
                {r.model} · {r.prompt_tokens}+{r.completion_tokens} tokens
              </p>
            </button>
          ))}
        </div>

        <div className="md:col-span-2">
          {selected ? (
            <div
              data-testid="report-detail"
              className="max-w-none rounded-lg border border-gray-200 bg-white p-6 shadow-sm"
            >
              <div className="mb-4 border-b border-gray-100 pb-4 text-sm text-gray-500">
                <p>训练：{selected.workout_title || '-'}</p>
                <p>模型：{selected.model || '-'}</p>
                <p>
                  tokens：{selected.prompt_tokens || 0} / {selected.completion_tokens || 0}
                  {selected.cost_estimate != null && ` · 约 ¥${selected.cost_estimate.toFixed(6)}`}
                </p>
              </div>
              <SimpleMarkdown text={selected.content_md || '无内容'} />
            </div>
          ) : (
            <div className="flex h-48 items-center justify-center rounded-lg border border-dashed border-gray-300 bg-gray-50 text-sm text-gray-500">
              选择左侧报告查看详情
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
