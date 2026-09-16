import { useCallback, useEffect, useState } from 'react'
import { api, download } from '../api/client'
import BottomSheet from '../components/BottomSheet'
import ReportChatSection from '../components/ReportChatSection'
import ReviewSections from '../components/ReviewSections'
import ScoreBadge from '../components/ScoreBadge'
import SharePosterButton from '../components/SharePosterButton'
import Button from '../components/ui/Button'
import ConfirmDialog from '../components/ui/ConfirmDialog'
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

/** 本地解析 YYYY-MM-DD 年月日，避免 Date 当 UTC 解析导致日期偏移 */
function parseIsoDateParts(iso) {
  if (!iso || typeof iso !== 'string') return null
  const m = iso.match(/^(\d{4})-(\d{1,2})-(\d{1,2})/)
  if (!m) return null
  return { month: Number(m[2]), day: Number(m[3]) }
}

/** 周期紧凑格式 M/D – M/D（去前导零）；来源 docs/prototypes/06-report.html 评分卡头 */
function formatPeriodRange(start, end) {
  const startParts = parseIsoDateParts(start)
  if (!startParts) return ''
  const startText = `${startParts.month}/${startParts.day}`
  const endParts = parseIsoDateParts(end)
  if (!endParts) return startText
  return `${startText} – ${endParts.month}/${endParts.day}`
}

/**
 * 海报兜底标题：周复盘 M/D–M/D / 月复盘 N月。
 * 周期段复用 formatPeriodRange，去掉 en-dash 两侧空格（与评分卡头同源、海报标题无空格）。
 */
function formatPosterFallbackTitle(report) {
  if (report?.type === 'monthly') {
    const parts = parseIsoDateParts(report.date)
    return parts ? `月复盘 ${parts.month}月` : '月复盘'
  }
  const range = formatPeriodRange(report?.date, report?.period_end).replace(
    ' – ',
    '–',
  )
  return range ? `周复盘 ${range}` : '周复盘'
}

/** 复盘详情：评分卡头 + 正文分卡 + 追问 CTA + 周海报，桌面分栏与移动端抽屉复用。 */
function ReviewDetail({ report, onExport, onRegenerate, regenerating }) {
  const periodText = formatPeriodRange(report.date, report.period_end)
  const posterLabel =
    report.type === 'monthly' ? '分享本月海报' : '分享本周海报'
  return (
    <div data-testid="report-detail" className="space-y-3">
      <section className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-4 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <ScoreBadge score={report.score} verdict={true} />
            {periodText ? (
              <span className="text-xs text-gray-600 dark:text-gray-400">
                {periodText}
              </span>
            ) : null}
          </div>
          <div className="flex gap-2">
            <Button
              variant="secondary"
              size="compact"
              testId="regenerate-review"
              disabled={regenerating}
              onClick={() => onRegenerate(report)}
            >
              {regenerating ? '重新生成中…' : '重新生成'}
            </Button>
            <Button
              variant="secondary"
              size="compact"
              testId="export-md"
              onClick={() => onExport('md')}
            >
              导出 Markdown
            </Button>
            <Button
              variant="secondary"
              size="compact"
              testId="export-pdf"
              onClick={() => onExport('pdf')}
            >
              导出 PDF
            </Button>
          </div>
        </div>
        <details data-testid="review-tech-details" className="mt-1">
          <summary className="min-h-[36px] cursor-pointer text-xs text-gray-600 dark:text-gray-400">
            技术详情（模型 / tokens / 成本）
          </summary>
          <p className="mt-1 rounded-lg bg-gray-50 dark:bg-gray-950 p-2 text-xs text-gray-600 dark:text-gray-400">
            {`模型：${report.model || '-'} · tokens：${report.prompt_tokens || 0}/${report.completion_tokens || 0} · 成本：${fmtCost(report.cost_estimate)}`}
          </p>
        </details>
      </section>
      <ReviewSections text={report.content_md || '无内容'} />
      <ReportChatSection reportId={report.id} />
      {/* 包装为块级全宽：组件本身保持 shrink 以免挤占训练点评页标题行 */}
      <div className="w-full [&>span]:flex [&>span]:w-full [&>span>button]:w-full">
        <SharePosterButton
          report={report}
          fallbackTitle={formatPosterFallbackTitle(report)}
          label={posterLabel}
        />
      </div>
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
  const [regeneratingId, setRegeneratingId] = useState(null)
  const [regenConfirm, setRegenConfirm] = useState(null)

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

  useEffect(() => {
    if (!regeneratingId) return undefined
    const timer = setInterval(() => {
      api(`/api/ai-reports/period/${regeneratingId}/regenerate/status`)
        .then((data) => {
          if (!data.running) {
            setRegeneratingId(null)
            if (data.error) {
              setError(`重新生成失败：${data.error}`)
            } else {
              setSelected(data.report)
              toast('复盘已按最新数据重新生成')
              load(tab)
            }
          }
        })
        .catch((err) => {
          setRegeneratingId(null)
          setError(err.message)
        })
    }, 3000)
    return () => clearInterval(timer)
  }, [regeneratingId, tab, load, toast])

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

  const handleRegenerateConfirm = () => {
    if (!regenConfirm) return
    const reportId = regenConfirm.id
    setRegenConfirm(null)
    setError('')
    api(`/api/ai-reports/period/${reportId}/regenerate`, { method: 'POST' })
      .then(() => setRegeneratingId(reportId))
      .catch((err) => setError(err.status === 409 ? '该复盘正在重新生成中' : err.message))
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
      <span className="text-xs text-gray-600 dark:text-gray-400">
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
        <h1 className="text-xl font-bold text-gray-900 dark:text-gray-100">复盘中心</h1>
        <div className="flex flex-wrap items-center gap-2">
          <PillGroup
            options={TABS.map((t) => ({ value: t.key, label: t.label }))}
            value={tab}
            onChange={setTab}
            testId="review-tabs"
            ariaLabel="复盘周期"
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
                  ? 'border-indigo-500 bg-indigo-50 dark:bg-indigo-950/50'
                  : 'border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 hover:bg-gray-50 dark:hover:bg-gray-800'
              }`}
            >
              <p className="font-medium text-gray-900 dark:text-gray-100">
                {r.date || '-'} ~ {r.period_end || r.date || '-'}
              </p>
              <p className="mt-1 flex items-center gap-2">
                <ScoreBadge score={r.score} />
                <span className="text-xs text-gray-600 dark:text-gray-400">
                  {TYPE_LABELS[r.type] || r.type || '-'}
                </span>
              </p>
            </button>
          ))}
        </div>

        {!isMobile && (
          <div className="md:col-span-2">
            {selected ? (
              <ReviewDetail
                report={selected}
                onExport={handleExport}
                onRegenerate={setRegenConfirm}
                regenerating={regeneratingId === selected.id}
              />
            ) : (
              <div className="flex h-48 items-center justify-center rounded-lg border border-dashed border-gray-300 dark:border-gray-600 bg-gray-50 dark:bg-gray-950 text-sm text-gray-500">
                选择左侧报告查看详情
              </div>
            )}
          </div>
        )}
      </div>

      {isMobile && selected && (
        <BottomSheet
          fullScreenMobile
          title={`${selected.date || '-'} ~ ${selected.period_end || selected.date || '-'}`}
          onClose={() => setSelected(null)}
          footer={navFooter}
        >
          <ReviewDetail
            report={selected}
            onExport={handleExport}
            onRegenerate={setRegenConfirm}
            regenerating={regeneratingId === selected.id}
          />
        </BottomSheet>
      )}
      <ConfirmDialog
        open={Boolean(regenConfirm)}
        title={`重新生成${regenConfirm?.type === 'monthly' ? '月复盘' : '周复盘'}？`}
        description="将读取该周期当前最新的真实数据。只有新报告生成成功后才会替换现有内容，已有追问记录会保留。"
        confirmText="重新生成"
        onConfirm={handleRegenerateConfirm}
        onCancel={() => setRegenConfirm(null)}
      />
    </div>
  )
}
