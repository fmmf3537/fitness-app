import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import BottomSheet from '../components/BottomSheet'
import ReportChatSection from '../components/ReportChatSection'
import ScoreBadge from '../components/ScoreBadge'
import SharePosterButton from '../components/SharePosterButton'
import SimpleMarkdown from '../components/SimpleMarkdown'
import Button from '../components/ui/Button'
import EmptyState from '../components/ui/EmptyState'
import ErrorState from '../components/ui/ErrorState'
import PillGroup from '../components/ui/PillGroup'
import Skeleton from '../components/ui/Skeleton'
import useIsMobile from '../hooks/useIsMobile'
import { fmtCost } from '../utils/format'

const MODE_OPTIONS = [
  { value: 'recent', label: '最近报告' },
  { value: 'bydate', label: '按日查询' },
]

const TYPE_OPTIONS = [
  { value: 'all', label: '全部' },
  { value: 'session_review', label: '单次点评' },
  { value: 'next_advice', label: '下次建议' },
]

const REGEN_POLL_INTERVAL_MS = 3000
const MAX_POLLS = 60

function formatDateInput(date) {
  return date.toISOString().slice(0, 10)
}

const TYPE_LABELS = {
  session_review: '单次点评',
  next_advice: '下次建议',
  weekly: '周报',
  monthly: '月报',
}

function typeLabel(type) {
  return TYPE_LABELS[type] || type || '-'
}

function ReportDetail({ report, onRegenerate, regenerating, regenError }) {
  return (
    <div
      data-testid="report-detail"
      className="max-w-none rounded-lg border border-gray-200 bg-white p-6 shadow-sm"
    >
      <div className="mb-4 border-b border-gray-100 pb-4 text-sm text-gray-600">
        <p className="flex flex-wrap items-center gap-2">
          训练：{report.workout_title || '-'}
          <ScoreBadge score={report.score} testId="detail-score-badge" />
        </p>
        <p>
          类型：{typeLabel(report.type)} · 日期：{report.date || '-'}
        </p>
        {report.one_liner && <p className="text-gray-700">一句话点评：{report.one_liner}</p>}
        <details data-testid="tech-details" className="mt-1">
          <summary className="min-h-[36px] cursor-pointer text-xs text-gray-600">
            技术详情（模型 / tokens / 成本）
          </summary>
          <p className="mt-1 rounded-lg bg-gray-50 p-2 text-xs text-gray-600">
            {`模型：${report.model || '-'} · tokens：${report.prompt_tokens || 0}/${report.completion_tokens || 0} · 成本：${fmtCost(report.cost_estimate)}`}
          </p>
        </details>
        {report.memory_refs &&
          (report.memory_refs.l1_count +
            report.memory_refs.l2_count +
            report.memory_refs.l3_count) >
            0 && (
            <p className="text-xs text-gray-600" data-testid="memory-refs">
              参考了 {report.memory_refs.l1_count} 条须知 ·{' '}
              {report.memory_refs.l2_count} 条对话记忆 ·{' '}
              {report.memory_refs.l3_count} 项统计
            </p>
          )}
        {report.type === 'session_review' && (
          <div className="mt-2">
            {/* V3-5：分享海报（抽屉与桌面详情共用此组件，未传 workout 时按 workout_id 拉取） */}
            <SharePosterButton report={report} />
          </div>
        )}
        {report.type === 'session_review' && report.score == null && onRegenerate && (
          <div className="mt-2">
            <Button
              variant="primary"
              testId="regen-report-btn"
              disabled={regenerating}
              onClick={onRegenerate}
              className="text-xs"
            >
              {regenerating ? '重新生成中…' : '重新生成（含评分）'}
            </Button>
            {regenError && <p className="mt-1 text-xs text-red-600">{regenError}</p>}
          </div>
        )}
      </div>
      <SimpleMarkdown text={report.content_md || '无内容'} />
      {/* V3-8：追问对话（抽屉与桌面详情共用此组件） */}
      <ReportChatSection reportId={report.id} />
    </div>
  )
}

export default function AIReportsPage() {
  const isMobile = useIsMobile()
  const [mode, setMode] = useState('recent') // recent / bydate
  const [typeFilter, setTypeFilter] = useState('all') // all / session_review / next_advice
  const [date, setDate] = useState(formatDateInput(new Date()))
  const [reports, setReports] = useState([])
  const [selected, setSelected] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [regenerating, setRegenerating] = useState(false)
  const [regenError, setRegenError] = useState('')

  const cancelledRef = useRef(false)
  useEffect(() => {
    cancelledRef.current = false
    return () => { cancelledRef.current = true }
  }, [])

  const load = useCallback(
    (keepSelection = false) => {
      setLoading(true)
      if (!keepSelection) setSelected(null)
      setError('')
      const typeParam = typeFilter === 'all' ? '' : `&type=${typeFilter}`
      const url =
        mode === 'recent'
          ? `/api/ai-reports?limit=50${typeParam}`
          : `/api/ai-reports?date=${date}${typeParam}`
      return api(url)
        .then((data) => {
          const list = data.reports || []
          setReports(list)
          return list
        })
        .catch((err) => setError(err.status === 401 ? '未登录' : err.message))
        .finally(() => setLoading(false))
    },
    [mode, date, typeFilter],
  )

  useEffect(() => {
    load()
  }, [load])

  // V3-4：存量无评分报告「重新生成」——删旧后后台重生成，轮询状态直至完成
  const handleRegenerate = async () => {
    if (!selected?.date || regenerating) return
    const targetDate = selected.date
    setRegenerating(true)
    setRegenError('')
    try {
      await api('/api/ai-reports/session-review/regenerate', {
        method: 'POST',
        body: JSON.stringify({ date: targetDate }),
      })
      // 轮询直至后台任务结束（最多 3 分钟；卸载后立即退出）
      let polls = 0
      while (polls++ < MAX_POLLS) {
        if (cancelledRef.current) break
        await new Promise((resolve) => setTimeout(resolve, REGEN_POLL_INTERVAL_MS))
        if (cancelledRef.current) break
        const st = await api(
          `/api/ai-reports/session-review/regenerate/status?date=${targetDate}`,
        )
        if (st.error) {
          setRegenError(st.error)
          break
        }
        if (!st.running) break
      }
      if (cancelledRef.current) return
      if (polls >= MAX_POLLS) setRegenError('生成超时（超过 3 分钟），请稍后重试')
      const list = await load(true)
      // 重新选中该日新的 session_review（旧 id 已删除）
      const next = (list || []).find(
        (r) => r.type === 'session_review' && r.date === targetDate,
      )
      setSelected(next || null)
    } catch (err) {
      if (cancelledRef.current) return
      setRegenError(
        err.status === 409 ? '该日期点评正在重新生成中，请稍候' : err.message || '重新生成失败',
      )
    } finally {
      setRegenerating(false)
    }
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
        <h1 className="text-xl font-bold text-gray-900">AI 训练点评</h1>
        <div className="flex flex-wrap items-center gap-2">
          <PillGroup
            options={MODE_OPTIONS}
            value={mode}
            onChange={setMode}
            testId="mode-tabs"
          />
          <PillGroup
            options={TYPE_OPTIONS}
            value={typeFilter}
            onChange={setTypeFilter}
            testId="type-filter-tabs"
          />
          {mode === 'bydate' && (
            <input
              type="date"
              value={date}
              onChange={(e) => setDate(e.target.value)}
              className="rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-100"
              data-testid="date-input"
            />
          )}
        </div>
      </div>

      {loading && (
        <div className="space-y-2">
          <Skeleton className="h-20" />
          <Skeleton className="h-20" />
        </div>
      )}
      {error && (
        <ErrorState message={error} onRetry={() => load()} testId="aireports-error" />
      )}

      {!loading && !error && reports.length === 0 && (
        <EmptyState
          title={mode === 'bydate' ? '当日暂无 AI 点评' : '暂无 AI 报告'}
          description="完成训练后即可查看 AI 点评与建议"
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
                {r.workout_title || '未命名训练'}
              </p>
              <p className="mt-1 flex items-center gap-2 text-xs text-gray-600">
                {typeLabel(r.type)} · {r.date || '-'}
                <ScoreBadge score={r.score} testId={`score-badge-${r.id}`} />
              </p>
            </button>
          ))}
        </div>

        {!isMobile && (
          <div className="md:col-span-2">
            {selected ? (
              <ReportDetail
                report={selected}
                onRegenerate={handleRegenerate}
                regenerating={regenerating}
                regenError={regenError}
              />
            ) : (
              <div className="flex h-48 items-center justify-center rounded-lg border border-dashed border-gray-300 bg-gray-50 text-sm text-gray-600">
                选择左侧报告查看详情
              </div>
            )}
          </div>
        )}
      </div>

      {isMobile && selected && (
        <BottomSheet
          title={selected.workout_title || '未命名训练'}
          onClose={() => setSelected(null)}
          footer={navFooter}
        >
          <ReportDetail
            report={selected}
            onRegenerate={handleRegenerate}
            regenerating={regenerating}
            regenError={regenError}
          />
        </BottomSheet>
      )}
    </div>
  )
}
