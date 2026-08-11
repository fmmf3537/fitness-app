import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError } from '../api/client'
import ReviewContent from '../components/ReviewContent'
import { fieldLabel, parsePlanReview } from '../utils/planReview'

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
    <div data-testid={`review-${report.date}`} className="mt-3 space-y-3 border-t border-gray-100 pt-3">
      {markdown && <ReviewContent text={markdown} />}
      {review && review.modifications.length > 0 && (
        <div>
          <h4 className="mb-1 text-sm font-bold text-gray-900">修改建议</h4>
          <table
            data-testid={`modifications-${report.date}`}
            className="w-full border-collapse text-xs"
          >
            <thead>
              <tr className="border-b border-gray-300 text-left text-gray-600">
                <th className="py-1 pr-2 font-medium">动作</th>
                <th className="py-1 pr-2 font-medium">调整项</th>
                <th className="py-1 pr-2 font-medium">原计划</th>
                <th className="py-1 pr-2 font-medium">建议改为</th>
                <th className="py-1 font-medium">理由</th>
              </tr>
            </thead>
            <tbody>
              {review.modifications.map((m, i) => (
                <tr key={i} className="border-b border-gray-100 text-gray-700">
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
      )}
      <p className="rounded-md bg-amber-50 p-2 text-xs font-medium text-amber-800">
        {READONLY_NOTICE}
      </p>
    </div>
  )
}

export default function PlansPage() {
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
          setRefreshMsg('计划缓存已刷新')
          loadPlans()
        } else {
          setRefreshMsg(`刷新失败：${st.error || '未知错误'}`)
        }
      } catch (e) {
        setRefreshing(false)
        setRefreshMsg(`刷新失败：${e.message}`)
      }
    }, POLL_INTERVAL_MS)
  }, [loadPlans])

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
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg font-bold text-gray-900">训练计划</h2>
        <div className="flex items-center gap-2">
          <button
            type="button"
            data-testid="refresh-button"
            onClick={handleRefresh}
            disabled={refreshing}
            className="rounded-md bg-indigo-600 px-3 py-1.5 text-sm text-white shadow hover:bg-indigo-500 disabled:opacity-50"
          >
            {refreshing ? '刷新中…' : '刷新计划'}
          </button>
          {refreshMsg && <p role="status" className="text-sm text-gray-600">{refreshMsg}</p>}
        </div>
      </div>

      {loadError && <p role="alert" className="text-sm text-red-600">{loadError}</p>}
      {days === null && !loadError && <p className="text-sm text-gray-500">加载中…</p>}
      {days !== null && days.length === 0 && (
        <p className="text-sm text-gray-500">暂无计划数据，请点击「刷新计划」拉取训记官方计划</p>
      )}

      <ul className="space-y-3">
        {(days || []).map((day) =>
          day.is_rest ? (
            <li
              key={day.date}
              data-testid={`rest-day-${day.date}`}
              className="rounded-lg bg-gray-100 p-3 text-sm text-gray-400"
            >
              {day.date} · 休息日
            </li>
          ) : (
            <li key={day.date} className="rounded-lg bg-white p-4 shadow">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <p className="text-sm font-bold text-gray-900">
                    {day.date} · {day.plan_name || day.plan_ref || '未命名计划'}
                  </p>
                  {day.title && <p className="mt-0.5 text-xs text-gray-500">{day.title}</p>}
                </div>
                <button
                  type="button"
                  data-testid={`review-button-${day.date}`}
                  onClick={() => handleReview(day.date)}
                  disabled={!!generating[day.date]}
                  className="shrink-0 rounded-md bg-green-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-green-700 disabled:opacity-50"
                >
                  {generating[day.date] ? '生成中…' : 'AI 点评'}
                </button>
              </div>
              <ul className="mt-2 space-y-1">
                {(day.movements || []).map((mv, i) => (
                  <li
                    key={i}
                    data-testid={`movement-${day.date}-${i}`}
                    className="text-sm text-gray-700"
                  >
                    {mv.name}
                    <span className="ml-2 text-xs text-gray-500">
                      {formatTargetSets(mv.target_sets)}
                    </span>
                  </li>
                ))}
              </ul>
              {genErrors[day.date] && (
                <p role="alert" className="mt-2 text-xs text-red-600">
                  {genErrors[day.date]}
                </p>
              )}
              {reviews[day.date] && <PlanReviewBlock report={reviews[day.date]} />}
            </li>
          ),
        )}
      </ul>
    </div>
  )
}
