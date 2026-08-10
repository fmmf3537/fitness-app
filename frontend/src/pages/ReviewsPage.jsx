import { useCallback, useEffect, useState } from 'react'
import { api, download } from '../api/client'
import ReviewContent from '../components/ReviewContent'

const TABS = [
  { key: 'weekly', label: '周复盘' },
  { key: 'monthly', label: '月复盘' },
]

export default function ReviewsPage() {
  const [tab, setTab] = useState('weekly')
  const [reports, setReports] = useState([])
  const [selected, setSelected] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [generating, setGenerating] = useState(false)
  const [toast, setToast] = useState('')

  const load = useCallback(
    (currentTab) => {
      setLoading(true)
      setError('')
      return api(`/api/ai-reports?type=${currentTab}&limit=50`)
        .then((data) => setReports(data.reports || []))
        .catch((err) => setError(err.status === 401 ? '未登录' : err.message))
        .finally(() => setLoading(false))
    },
    [],
  )

  useEffect(() => {
    setSelected(null)
    setToast('')
    load(tab)
  }, [tab, load])

  // 生成完成轮询（复用导入页模式）
  useEffect(() => {
    if (!generating) return undefined
    const timer = setInterval(() => {
      api(`/api/ai-reports/generate/status?type=${tab}`)
        .then((data) => {
          if (!data.running) {
            setGenerating(false)
            if (data.error) {
              setError(`生成失败：${data.error}`)
            } else {
              setToast('复盘生成完成')
              load(tab)
            }
          }
        })
        .catch(() => {})
    }, 3000)
    return () => clearInterval(timer)
  }, [generating, tab, load])

  const handleGenerate = () => {
    setToast('')
    setError('')
    api('/api/ai-reports/generate', {
      method: 'POST',
      body: JSON.stringify({ type: tab }),
    })
      .then((data) => {
        if (data.status === 'exists') {
          setToast('该周期复盘已存在')
        } else {
          setGenerating(true)
        }
      })
      .catch((err) =>
        setError(err.status === 409 ? '正在生成中，请稍候' : err.message),
      )
  }

  const handleExport = (format) => {
    if (!selected) return
    const start = selected.date || 'unknown'
    const end = selected.period_end || start
    download(
      `/api/ai-reports/${selected.id}/export?format=${format}`,
      `${selected.type}_${start}_${end}.${format}`,
    ).catch((err) => setError(err.message))
  }

  const pillClass = (active) =>
    `rounded-md px-3 py-2 text-sm font-medium ${
      active ? 'bg-indigo-600 text-white' : 'text-gray-700 hover:bg-gray-200'
    }`

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-xl font-bold text-gray-900">复盘中心</h1>
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex gap-1">
            {TABS.map((t) => (
              <button
                key={t.key}
                data-testid={`tab-${t.key}`}
                onClick={() => setTab(t.key)}
                className={pillClass(tab === t.key)}
              >
                {t.label}
              </button>
            ))}
          </div>
          <button
            data-testid="generate-button"
            onClick={handleGenerate}
            disabled={generating}
            className="rounded-md bg-green-600 px-3 py-2 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-50"
          >
            {generating ? '生成中…' : '立即生成'}
          </button>
        </div>
      </div>

      {toast && (
        <p role="status" className="text-sm text-green-600">
          {toast}
        </p>
      )}
      {loading && <p className="text-sm text-gray-500">加载中…</p>}
      {error && (
        <p role="alert" className="text-sm text-red-600">
          {error}
        </p>
      )}

      {!loading && !error && reports.length === 0 && (
        <p className="text-sm text-gray-500">暂无复盘报告，可点击「立即生成」。</p>
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
                {r.date || '-'} ~ {r.period_end || r.date || '-'}
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
              <div className="mb-4 flex flex-wrap items-start justify-between gap-2 border-b border-gray-100 pb-4 text-sm text-gray-500">
                <div>
                  <p>
                    周期：{selected.date || '-'} ~ {selected.period_end || '-'}
                  </p>
                  <p>模型：{selected.model || '-'}</p>
                </div>
                <div className="flex gap-2">
                  <button
                    data-testid="export-md"
                    onClick={() => handleExport('md')}
                    className="rounded-md border border-gray-300 px-3 py-1 text-sm text-gray-700 hover:bg-gray-100"
                  >
                    导出 Markdown
                  </button>
                  <button
                    data-testid="export-pdf"
                    onClick={() => handleExport('pdf')}
                    className="rounded-md border border-gray-300 px-3 py-1 text-sm text-gray-700 hover:bg-gray-100"
                  >
                    导出 PDF
                  </button>
                </div>
              </div>
              <ReviewContent text={selected.content_md || '无内容'} />
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
