import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import BottomSheet from '../components/BottomSheet'
import ReportChatSection from '../components/ReportChatSection'
import ScoreBadge from '../components/ScoreBadge'
import SharePosterButton from '../components/SharePosterButton'
import SimpleMarkdown from '../components/SimpleMarkdown'
import useIsMobile from '../hooks/useIsMobile'

const REGEN_POLL_INTERVAL_MS = 3000

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
      <div className="mb-4 border-b border-gray-100 pb-4 text-sm text-gray-500">
        <p className="flex flex-wrap items-center gap-2">
          训练：{report.workout_title || '-'}
          <ScoreBadge score={report.score} testId="detail-score-badge" />
        </p>
        <p>
          类型：{typeLabel(report.type)} · 日期：{report.date || '-'}
        </p>
        {report.one_liner && <p className="text-gray-700">一句话点评：{report.one_liner}</p>}
        <p>模型：{report.model || '-'}</p>
        <p>
          tokens：{report.prompt_tokens || 0} / {report.completion_tokens || 0}
          {report.cost_estimate != null && ` · 约 ¥${report.cost_estimate.toFixed(6)}`}
        </p>
        {report.type === 'session_review' && (
          <div className="mt-2">
            {/* V3-5：分享海报（抽屉与桌面详情共用此组件，未传 workout 时按 workout_id 拉取） */}
            <SharePosterButton report={report} />
          </div>
        )}
        {report.type === 'session_review' && report.score == null && onRegenerate && (
          <div className="mt-2">
            <button
              type="button"
              data-testid="regen-report-btn"
              disabled={regenerating}
              onClick={onRegenerate}
              className="rounded-md bg-green-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-green-700 disabled:opacity-50"
            >
              {regenerating ? '重新生成中…' : '重新生成（含评分）'}
            </button>
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
      // 轮询直至后台任务结束
      for (;;) {
        await new Promise((resolve) => setTimeout(resolve, REGEN_POLL_INTERVAL_MS))
        const st = await api(
          `/api/ai-reports/session-review/regenerate/status?date=${targetDate}`,
        )
        if (!st.running) {
          if (st.error) setRegenError(st.error)
          break
        }
      }
      const list = await load(true)
      // 重新选中该日新的 session_review（旧 id 已删除）
      const next = (list || []).find(
        (r) => r.type === 'session_review' && r.date === targetDate,
      )
      setSelected(next || null)
    } catch (err) {
      setRegenError(
        err.status === 409 ? '该日期点评正在重新生成中，请稍候' : err.message || '重新生成失败',
      )
    } finally {
      setRegenerating(false)
    }
  }

  const pillClass = (active) =>
    `rounded-md px-3 py-2 text-sm font-medium ${
      active ? 'bg-indigo-600 text-white' : 'text-gray-700 hover:bg-gray-200'
    }`

  const selectedIndex = reports.findIndex((r) => selected != null && r.id === selected.id)

  const navFooter = (
    <div className="flex items-center justify-between gap-2">
      <button
        type="button"
        data-testid="sheet-prev"
        disabled={selectedIndex <= 0}
        onClick={() => setSelected(reports[selectedIndex - 1])}
        className="rounded-md border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-100 disabled:opacity-40"
      >
        上一篇
      </button>
      <span className="text-xs text-gray-400">
        {selectedIndex + 1} / {reports.length}
      </span>
      <button
        type="button"
        data-testid="sheet-next"
        disabled={selectedIndex < 0 || selectedIndex >= reports.length - 1}
        onClick={() => setSelected(reports[selectedIndex + 1])}
        className="rounded-md border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-100 disabled:opacity-40"
      >
        下一篇
      </button>
    </div>
  )

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-xl font-bold text-gray-900">AI 训练点评</h1>
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex gap-1">
            <button
              data-testid="mode-recent"
              onClick={() => setMode('recent')}
              className={pillClass(mode === 'recent')}
            >
              最近报告
            </button>
            <button
              data-testid="mode-bydate"
              onClick={() => setMode('bydate')}
              className={pillClass(mode === 'bydate')}
            >
              按日查询
            </button>
          </div>
          <div className="flex gap-1">
            <button
              data-testid="type-filter-all"
              onClick={() => setTypeFilter('all')}
              className={pillClass(typeFilter === 'all')}
            >
              全部
            </button>
            <button
              data-testid="type-filter-session"
              onClick={() => setTypeFilter('session_review')}
              className={pillClass(typeFilter === 'session_review')}
            >
              单次点评
            </button>
            <button
              data-testid="type-filter-advice"
              onClick={() => setTypeFilter('next_advice')}
              className={pillClass(typeFilter === 'next_advice')}
            >
              下次建议
            </button>
          </div>
          {mode === 'bydate' && (
            <input
              type="date"
              value={date}
              onChange={(e) => setDate(e.target.value)}
              className="rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none"
              data-testid="date-input"
            />
          )}
        </div>
      </div>

      {loading && <p className="text-sm text-gray-500">加载中…</p>}
      {error && <p role="alert" className="text-sm text-red-600">{error}</p>}

      {!loading && !error && reports.length === 0 && (
        <p className="text-sm text-gray-500">
          {mode === 'bydate' ? '当日暂无 AI 点评' : '暂无 AI 报告'}
        </p>
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
              <p className="mt-1 flex items-center gap-2 text-xs text-gray-500">
                {typeLabel(r.type)} · {r.date || '-'}
                <ScoreBadge score={r.score} testId={`score-badge-${r.id}`} />
              </p>
              <p className="mt-1 text-xs text-gray-500">
                {r.model} · {r.prompt_tokens}+{r.completion_tokens} tokens
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
              <div className="flex h-48 items-center justify-center rounded-lg border border-dashed border-gray-300 bg-gray-50 text-sm text-gray-500">
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
