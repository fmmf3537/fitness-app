import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import SyncButton from '../components/SyncButton'
import Button from '../components/ui/Button'
import ErrorState from '../components/ui/ErrorState'
import Skeleton from '../components/ui/Skeleton'
import { statusColor } from '../utils/status'
import { useCandidateQueue } from '../components/useCandidateQueue'
import usePullToRefresh from '../hooks/usePullToRefresh'

function currentMonth() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

function shiftMonth(month, delta) {
  const [y, m] = month.split('-').map(Number)
  const d = new Date(y, m - 1 + delta, 1)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

const WEEKDAYS = ['一', '二', '三', '四', '五', '六', '日']

export default function CalendarPage({ initialMonth }) {
  const navigate = useNavigate()
  const { pendingCount, error: candidateError } = useCandidateQueue()
  const [month, setMonth] = useState(initialMonth || currentMonth())
  const [days, setDays] = useState([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  const load = useCallback(() => {
    setLoading(true)
    setError('')
    return api(`/api/workouts/calendar?month=${month}`)
      .then((data) => setDays(data.days || []))
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }, [month])

  useEffect(() => {
    load()
  }, [load])

  const dayMap = useMemo(() => {
    const map = {}
    for (const d of days) map[d.date] = d
    return map
  }, [days])

  const cells = useMemo(() => {
    const [y, m] = month.split('-').map(Number)
    const first = new Date(y, m - 1, 1)
    // Monday-first offset
    const offset = (first.getDay() + 6) % 7
    const daysInMonth = new Date(y, m, 0).getDate()
    const result = []
    for (let i = 0; i < offset; i++) result.push(null)
    for (let d = 1; d <= daysInMonth; d++) {
      result.push(`${month}-${String(d).padStart(2, '0')}`)
    }
    return result
  }, [month])

  const workoutCount = useMemo(
    () => days.reduce((total, day) => total + (day.workouts?.length || 0), 0),
    [days],
  )
  const isCurrentMonth = month === currentMonth()
  const { pulling, bind: pullBind } = usePullToRefresh(load)

  return (
    <div {...pullBind}>
      {pulling && <p role="status" className="mb-2 text-center text-xs text-indigo-600">正在刷新日历…</p>}
      <div
        data-testid="calendar-header"
        className="mb-3 flex items-center justify-between gap-2"
      >
        <div className="flex min-w-0 items-center gap-1">
          <Button
            variant="secondary"
            ariaLabel="上个月"
            onClick={() => setMonth((m) => shiftMonth(m, -1))}
            className="w-10 px-0 text-xl"
          >‹</Button>
          <h2 data-testid="current-month" className="shrink-0 whitespace-nowrap px-1 text-lg font-black tracking-tight text-gray-950 dark:text-white sm:px-2 sm:text-xl">
            {month.replace('-', ' 年 ')} 月
          </h2>
          <Button
            variant="secondary"
            ariaLabel="下个月"
            onClick={() => setMonth((m) => shiftMonth(m, 1))}
            className="w-10 px-0 text-xl"
          >›</Button>
          {!isCurrentMonth && <Button variant="ghost" onClick={() => setMonth(currentMonth())} className="px-2">今</Button>}
        </div>
        <div data-testid="sync-row" className="flex shrink-0 items-center gap-2">
          <SyncButton onSynced={load} />
        </div>
      </div>

      {!loading && !error && (
        <div className="mb-3 grid grid-cols-3 overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-sm dark:border-gray-800 dark:bg-gray-900">
          {[
            ['训练天数', days.length],
            ['训练次数', workoutCount],
            ['待确认', pendingCount == null ? '—' : pendingCount],
          ].map(([label, value]) => (
            <div key={label} className="border-r border-gray-100 px-2 py-2.5 text-center last:border-r-0 dark:border-gray-800 sm:px-3 sm:py-4">
              <p className="text-lg font-black text-gray-950 dark:text-white sm:text-xl">{value}</p>
              <p className="mt-0.5 text-xs text-gray-600 dark:text-gray-300">{label}</p>
            </div>
          ))}
        </div>
      )}

      {pendingCount > 0 && (
        <div className="mb-4 flex items-center justify-between gap-3 rounded-lg border border-amber-200 bg-amber-50 dark:bg-amber-950/50 p-3 text-sm text-amber-900 dark:text-amber-200">
          <span><strong>{pendingCount} 条记录待确认</strong><span className="block text-xs">请检查是否为同一次训练</span></span>
          <Link className="shrink-0 rounded-lg px-3 py-2 font-medium text-amber-900 dark:text-amber-200 hover:bg-amber-100 dark:hover:bg-amber-900" to="/candidates">
            去处理 →
          </Link>
        </div>
      )}
      {pendingCount === null && candidateError && (
        <p role="status" className="mb-4 text-sm text-amber-700 dark:text-amber-300">
          待确认数量暂时无法刷新
        </p>
      )}

      {error ? (
        <ErrorState
          testId="calendar-error"
          message={`加载失败：${error}`}
          onRetry={load}
        />
      ) : loading ? (
        <div className="grid grid-cols-7 gap-1">
          {Array.from({ length: 35 }, (_, i) => (
            <Skeleton key={i} className="h-16" />
          ))}
        </div>
      ) : (
        <>
          <div className="mb-2 flex flex-wrap gap-1.5 text-[11px] text-gray-600 dark:text-gray-300 sm:gap-2 sm:text-xs">
            <span className="rounded-full bg-green-50 px-2 py-1 dark:bg-green-950/50"><span aria-hidden="true">● </span>已匹配</span>
            <span className="rounded-full bg-indigo-50 px-2 py-1 dark:bg-indigo-950/50"><span aria-hidden="true">● </span>仅单源</span>
            <span className="rounded-full bg-amber-50 px-2 py-1 dark:bg-amber-950/50"><span aria-hidden="true">● </span>待确认</span>
          </div>
          <div className="grid grid-cols-7 gap-1">
            {WEEKDAYS.map((w) => (
              <div key={w} className="py-1 text-center text-sm font-medium text-gray-500">
                {w}
              </div>
            ))}
            {cells.map((date, i) =>
              date === null ? (
                <div key={`empty-${i}`} />
              ) : (
                <button
                  key={date}
                  data-testid={`day-${date}`}
                  onClick={() => navigate(`/workouts?date=${date}`)}
                  className={`flex min-h-14 min-w-0 flex-col items-start rounded-lg border border-gray-200 bg-white p-1 text-xs transition hover:-translate-y-0.5 hover:border-indigo-400 hover:shadow-sm dark:border-gray-700 dark:bg-gray-900 sm:min-h-20 sm:rounded-xl sm:p-1.5 sm:text-sm ${
                    (dayMap[date]?.workouts?.length || 0) > 0 ? 'border-indigo-200 bg-indigo-50/70 dark:border-indigo-800 dark:bg-indigo-950/50' : ''
                  }`}
                >
                  <span className="text-gray-800 dark:text-gray-200">{Number(date.slice(-2))}</span>
                  <span className="mt-1 w-full space-y-0.5 overflow-hidden text-left">
                    {(dayMap[date]?.workouts || []).slice(0, 1).map((w) => (
                      <span
                        key={w.id}
                        title={w.title}
                        className="flex min-w-0 items-center gap-1 text-[10px] font-medium text-gray-700 dark:text-gray-200"
                      ><span data-testid={`dot-${date}-${w.match_status}`} className={`h-1.5 w-1.5 shrink-0 rounded-full ${statusColor(w.match_status)}`} /><span className="hidden truncate sm:inline">{w.title}</span></span>
                    ))}
                    {(dayMap[date]?.workouts?.length || 0) > 1 && <span className="block pl-2.5 text-[10px] text-indigo-600">+{dayMap[date].workouts.length - 1}</span>}
                  </span>
                </button>
              ),
            )}
          </div>
        </>
      )}
    </div>
  )
}
