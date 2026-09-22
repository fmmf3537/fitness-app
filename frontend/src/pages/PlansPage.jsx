import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError } from '../api/client'
import PageHeader from '../components/PageHeader'
import ReviewContent from '../components/ReviewContent'
import Button from '../components/ui/Button'
import Icon from '../components/ui/Icon'
import EmptyState from '../components/ui/EmptyState'
import ErrorState from '../components/ui/ErrorState'
import Skeleton from '../components/ui/Skeleton'
import { useToast } from '../components/ui/useToast'
import { fieldLabel, parsePlanReview } from '../utils/planReview'

function todayStr() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

const WEEKDAY_CHARS = '日一二三四五六'

const POLL_INTERVAL_MS = 3000
const READONLY_NOTICE = '计划接口只读，请在训记 App 中手动调整'

function formatTargetSets(targetSets) {
  const sets = targetSets || []
  if (sets.length === 0) return ''
  const first = sets[0] || {}
  const parts = [`目标 ${sets.length} 组`]
  if (first.weight != null && first.reps != null) {
    parts.push(`（${first.weight}${first.unit || 'kg'}×${first.reps}）`)
  }
  return parts.join('')
}

/** 单个计划日的 AI 点评展示区：Markdown 正文 + 修改建议表格 + 只读提示。 */
function PlanReviewBlock({ report }) {
  const { markdown, review } = parsePlanReview(report?.content_md)
  return (
    <div data-testid={`review-${report.date}`} className="mt-3 space-y-3 border-t border-gray-100 dark:border-gray-800 pt-3">
      {markdown && <ReviewContent text={markdown} />}
      {review && review.modifications.length > 0 && (
        <div>
          <h4 className="mb-1 text-sm font-bold text-gray-900 dark:text-gray-100">修改建议</h4>
          <div className="overflow-x-auto">
            <table
              data-testid={`modifications-${report.date}`}
              className="w-full border-collapse text-xs whitespace-nowrap"
            >
            <thead>
              <tr className="border-b border-gray-300 dark:border-gray-600 text-left text-gray-600 dark:text-gray-400">
                <th className="py-1 pr-2 font-medium">动作</th>
                <th className="py-1 pr-2 font-medium">调整项</th>
                <th className="py-1 pr-2 font-medium">原计划</th>
                <th className="py-1 pr-2 font-medium">建议改为</th>
                <th className="py-1 font-medium">理由</th>
              </tr>
            </thead>
            <tbody>
              {review.modifications.map((m, i) => (
                <tr key={i} className="border-b border-gray-100 dark:border-gray-800 text-gray-700 dark:text-gray-300">
                  <td className="py-1 pr-2">{m.movement}</td>
                  <td className="py-1 pr-2">{fieldLabel(m.field)}</td>
                  <td className="py-1 pr-2">{m.from ?? '—'}</td>
                  <td className="py-1 pr-2">{m.to ?? '—'}</td>
                  <td className="py-1">{m.reason}</td>
                </tr>
              ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
      <p className="rounded-md bg-amber-50 dark:bg-amber-950/50 p-2 text-xs font-medium text-amber-800">
        {READONLY_NOTICE}
      </p>
    </div>
  )
}

export default function PlansPage() {
  const { toast } = useToast()
  const [days, setDays] = useState(null)
  const [loadError, setLoadError] = useState('')
  const [refreshing, setRefreshing] = useState(false)
  const [refreshMsg, setRefreshMsg] = useState('')
  const [reviews, setReviews] = useState({}) // date -> report | null
  const [generating, setGenerating] = useState({}) // date -> bool
  const [genErrors, setGenErrors] = useState({}) // date -> string
  const timerRef = useRef(null)

  useEffect(() => () => clearTimeout(timerRef.current), [])

  const loadReviews = useCallback(async (dayList) => {
    const entries = await Promise.all(
      (dayList || [])
        .filter((d) => !d.is_rest)
        .map(async (d) => {
          try {
            const report = await api(`/api/plans/review/${d.date}`)
            return [d.date, report]
          } catch {
            return [d.date, null]
          }
        }),
    )
    setReviews(Object.fromEntries(entries))
  }, [])

  const loadPlans = useCallback(async () => {
    setLoadError('')
    try {
      const data = await api('/api/plans/upcoming?days=30')
      setDays(data.days || [])
      loadReviews(data.days || [])
    } catch (e) {
      setLoadError(`加载计划失败：${e.message}`)
    }
  }, [loadReviews])

  useEffect(() => {
    loadPlans()
  }, [loadPlans])

  const pollRefresh = useCallback(() => {
    timerRef.current = setTimeout(async () => {
      try {
        const st = await api('/api/plans/refresh/status')
        if (st.running) {
          pollRefresh()
          return
        }
        setRefreshing(false)
        if (st.status === 'success') {
          toast('计划缓存已刷新')
          loadPlans()
        } else {
          setRefreshMsg(`刷新失败：${st.error || '未知错误'}`)
        }
      } catch (e) {
        setRefreshing(false)
        setRefreshMsg(`刷新失败：${e.message}`)
      }
    }, POLL_INTERVAL_MS)
  }, [loadPlans, toast])

  const handleRefresh = async () => {
    if (refreshing) return
    setRefreshing(true)
    setRefreshMsg('')
    try {
      await api('/api/plans/refresh', { method: 'POST' })
      pollRefresh()
    } catch (e) {
      setRefreshing(false)
      setRefreshMsg(
        e instanceof ApiError && e.status === 409
          ? '计划缓存刷新正在进行中，请稍候'
          : `刷新失败：${e.message}`,
      )
    }
  }

  const pollReview = useCallback((dayDate) => {
    timerRef.current = setTimeout(async () => {
      try {
        const st = await api(`/api/plans/review/${dayDate}/status`)
        if (st.running) {
          pollReview(dayDate)
          return
        }
        setGenerating((prev) => ({ ...prev, [dayDate]: false }))
        if (st.error) {
          setGenErrors((prev) => ({ ...prev, [dayDate]: `点评生成失败：${st.error}` }))
          return
        }
        const report = await api(`/api/plans/review/${dayDate}`)
        setReviews((prev) => ({ ...prev, [dayDate]: report }))
      } catch (e) {
        setGenerating((prev) => ({ ...prev, [dayDate]: false }))
        setGenErrors((prev) => ({ ...prev, [dayDate]: `点评生成失败：${e.message}` }))
      }
    }, POLL_INTERVAL_MS)
  }, [])

  const handleReview = async (dayDate) => {
    if (generating[dayDate]) return
    setGenerating((prev) => ({ ...prev, [dayDate]: true }))
    setGenErrors((prev) => ({ ...prev, [dayDate]: '' }))
    try {
      await api(`/api/plans/review/${dayDate}`, { method: 'POST' })
      pollReview(dayDate)
    } catch (e) {
      setGenerating((prev) => ({ ...prev, [dayDate]: false }))
      if (e instanceof ApiError && e.status === 409) {
        setGenErrors((prev) => ({ ...prev, [dayDate]: '该日期点评正在生成中，请稍候' }))
      } else if (e instanceof ApiError && e.status === 404) {
        setGenErrors((prev) => ({ ...prev, [dayDate]: '该日为休息日或无计划安排' }))
      } else {
        setGenErrors((prev) => ({ ...prev, [dayDate]: `点评生成失败：${e.message}` }))
      }
    }
  }

  return (
    <div className="space-y-4">
      <PageHeader title="训练计划" subtitle="未来两周安排" />
      <div className="mt-4 flex flex-wrap items-center gap-2">
        <Button
          variant="primary"
          testId="refresh-button"
          onClick={handleRefresh}
          disabled={refreshing}
        >
          {refreshing ? '刷新中…' : '刷新计划'}
        </Button>
        {refreshMsg && <p role="status" className="text-sm text-ink-500 dark:text-gray-400">{refreshMsg}</p>}
      </div>

      {loadError && (
        <ErrorState message={loadError} onRetry={loadPlans} testId="plans-error" />
      )}
      {days === null && !loadError && (
        <div className="space-y-3">
          <Skeleton className="h-24" />
          <Skeleton className="h-24" />
          <Skeleton className="h-24" />
        </div>
      )}
      {days !== null && days.length === 0 && (
        <EmptyState
          title="暂无计划数据"
          description="点击下方按钮拉取训记官方计划"
          action={
            <Button variant="primary" onClick={handleRefresh} disabled={refreshing}>
              刷新计划
            </Button>
          }
        />
      )}

      <ul className="space-y-3">
        {(days || []).map((day) => {
          const [py, pm, pd] = day.date.split('-').map(Number)
          const weekday = WEEKDAY_CHARS[new Date(py, pm - 1, pd).getDay()]
          const isToday = day.date === todayStr()
          return day.is_rest ? (
            <li
              key={day.date}
              data-testid={`rest-day-${day.date}`}
              className="flex items-center gap-3 rounded-2xl bg-line/70 px-4 py-3 text-sm text-ink-500 dark:bg-gray-900 dark:text-gray-400"
            >
              <span className="w-14 shrink-0 font-bold">{pd}<span className="ml-1 text-[10px] font-normal">周{weekday}</span></span>
              <span className="flex items-center gap-1.5"><Icon name="moon" size={14} />休息日</span>
            </li>
          ) : (
            <li key={day.date} className={`rounded-[20px] border border-line bg-white p-4 shadow-card dark:border-gray-800 dark:bg-gray-900 ${isToday ? 'bg-gradient-soft ring-2 ring-brand-500' : ''}`}>
              <div className="flex items-start justify-between gap-2">
                <div className="flex min-w-0 items-start gap-3">
                  <div className="w-12 shrink-0 border-r border-line pr-3 text-center">
                    <p className="text-xl font-black text-ink-900 dark:text-white">{pd}</p>
                    <p className="mt-0.5 text-[10px] text-ink-400">周{weekday}{isToday ? ' · 今天' : ''}</p>
                  </div>
                  <div className="min-w-0">
                    <p className="text-sm font-bold text-ink-900 dark:text-gray-100">
                      {day.plan_name || day.plan_ref || '未命名计划'}
                    </p>
                    {day.title && <p className="mt-0.5 text-xs text-ink-500 dark:text-gray-400">{day.title}</p>}
                    <ul className="mt-2 space-y-1">
                      {(day.movements || []).map((mv, i) => (
                        <li
                          key={i}
                          data-testid={`movement-${day.date}-${i}`}
                          className="flex items-center gap-2 text-sm text-ink-600 dark:text-gray-300"
                        >
                          <span aria-hidden="true" className="h-1.5 w-1.5 shrink-0 rounded-[3px] bg-brand-500" />
                          {mv.name}
                          <span className="text-xs text-ink-400 dark:text-gray-400">
                            {formatTargetSets(mv.target_sets)}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
                <Button
                  variant="primary"
                  size="compact"
                  testId={`review-button-${day.date}`}
                  onClick={() => handleReview(day.date)}
                  disabled={!!generating[day.date]}
                  className="shrink-0"
                >
                  {generating[day.date] ? '生成中…' : 'AI 点评'}
                </Button>
              </div>
              {genErrors[day.date] && (
                <p role="alert" className="mt-2 text-xs text-red-600">
                  {genErrors[day.date]}
                </p>
              )}
              {reviews[day.date] && <PlanReviewBlock report={reviews[day.date]} />}
            </li>
          )
        })}
      </ul>
    </div>
  )
}
