import { useCallback, useEffect, useState } from 'react'
import { api, download } from '../api/client'
import BottomSheet from '../components/BottomSheet'
import ReviewContent from '../components/ReviewContent'
import ScoreBadge from '../components/ScoreBadge'
import Button from '../components/ui/Button'
import EmptyState from '../components/ui/EmptyState'
import ErrorState from '../components/ui/ErrorState'
import PillGroup from '../components/ui/PillGroup'
import Skeleton from '../components/ui/Skeleton'
import { useToast } from '../components/ui/useToast'
import useIsMobile from '../hooks/useIsMobile'
import { fmtCost } from '../utils/format'

const TABS = [
  { key: 'weekly', label: '周复盘' },
  { key: 'monthly', label: '月复盘' },
]

const TYPE_LABELS = {
  weekly: '周复盘',
  monthly: '月复盘',
}

/** 复盘详情：头部元信息 + 导出按钮 + ReviewContent，桌面分栏与移动端抽屉复用。 */
function ReviewDetail({ report, onExport }) {
  return (
    <div
      data-testid="report-detail"
      className="max-w-none rounded-lg border border-gray-200 bg-white p-6 shadow-sm"
    >
      <div className="mb-4 flex flex-wrap items-start justify-between gap-2 border-b border-gray-100 pb-4 text-sm text-gray-500">
        <div>
          <p>
            周期：{report.date || '-'} ~ {report.period_end || '-'}
          </p>
          <details data-testid="review-tech-details" className="mt-1">
            <summary className="min-h-[36px] cursor-pointer text-xs text-gray-600">
              技术详情（模型 / tokens / 成本）
            </summary>
            <p className="mt-1 rounded-lg bg-gray-50 p-2 text-xs text-gray-600">
              {`模型：${report.model || '-'} · tokens：${report.prompt_tokens || 0}/${report.completion_tokens || 0} · 成本：${fmtCost(report.cost_estimate)}`}
            </p>
          </details>
        </div>
        <div className="flex gap-2">
          <Button
            variant="secondary"
            testId="export-md"
            onClick={() => onExport('md')}
          >
            导出 Markdown
          </Button>
          <Button
            variant="secondary"
            testId="export-pdf"
            onClick={() => onExport('pdf')}
          >
            导出 PDF
          </Button>
        </div>
      </div>
      <ReviewContent text={report.content_md || '无内容'} />
    </div>
  )
}

export default function ReviewsPage() {
  const isMobile = useIsMobile()
  const { toast } = useToast()
  const [tab, setTab] = useState('weekly')
  const [reports, setReports] = useState([])
  const [selected, setSelected] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [generating, setGenerating] = useState(false)

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
              toast('复盘生成完成')
              load(tab)
            }
          }
        })
        .catch(() => {})
    }, 3000)
    return () => clearInterval(timer)
  }, [generating, tab, load, toast])

  const handleGenerate = () => {
    setError('')
    api('/api/ai-reports/generate', {
      method: 'POST',
      body: JSON.stringify({ type: tab }),
    })
      .then((data) => {
        if (data.status === 'exists') {
          toast('该周期复盘已存在', 'info')
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

  const selectedIndex = reports.findIndex((r) => selected != null && r.id === selected.id)

  const navFooter = (
    <div className="flex items-center justify-between gap-2">
      <Button
        variant="secondary"
        testId="sheet-prev"
        disabled={selectedIndex <= 0}
        onClick={() => setSelected(reports[selectedIndex - 1])}
      >
        上一篇
      </Button>
      <span className="text-xs text-gray-600">
        {selectedIndex + 1} / {reports.length}
      </span>
      <Button
        variant="secondary"
        testId="sheet-next"
        disabled={selectedIndex < 0 || selectedIndex >= reports.length - 1}
        onClick={() => setSelected(reports[selectedIndex + 1])}
      >
        下一篇
      </Button>
    </div>
  )

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-xl font-bold text-gray-900">复盘中心</h1>
        <div className="flex flex-wrap items-center gap-2">
          <PillGroup
            options={TABS.map((t) => ({ value: t.key, label: t.label }))}
            value={tab}
            onChange={setTab}
            testId="review-tabs"
          />
          <Button
            variant="primary"
            testId="generate-button"
            onClick={handleGenerate}
            disabled={generating}
          >
            {generating ? '生成中…' : '立即生成'}
          </Button>
        </div>
      </div>

      {loading && (
        <div className="space-y-2">
          <Skeleton className="h-20" />
          <Skeleton className="h-20" />
        </div>
      )}
      {error && (
        <ErrorState
          message={error}
          onRetry={() => load(tab)}
          testId="reviews-error"
        />
      )}

      {!loading && !error && reports.length === 0 && (
        <EmptyState
          title="暂无复盘报告"
          description="点击「立即生成」创建本周期复盘"
          action={
            <Button variant="primary" onClick={handleGenerate} disabled={generating}>
              立即生成
            </Button>
          }
        />
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
              <p className="mt-1 flex items-center gap-2">
                <ScoreBadge score={r.score} />
                <span className="text-xs text-gray-600">
                  {TYPE_LABELS[r.type] || r.type || '-'}
                </span>
              </p>
            </button>
          ))}
        </div>

        {!isMobile && (
          <div className="md:col-span-2">
            {selected ? (
              <ReviewDetail report={selected} onExport={handleExport} />
            ) : (
              <div className="flex h-48 items-center justify-center rounded-lg border border-dashed border-gray-300 bg-gray-50 text-sm text-gray-500">
                选择左侧报告查看详情
              </div>
            )}
          </div>
        )}
      </div>

      {isMobile && selected && (
        <BottomSheet
          title={`${selected.date || '-'} ~ ${selected.period_end || selected.date || '-'}`}
          onClose={() => setSelected(null)}
          footer={navFooter}
        >
          <ReviewDetail report={selected} onExport={handleExport} />
        </BottomSheet>
      )}
    </div>
  )
}
