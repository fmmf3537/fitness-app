import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import PageHeader from '../components/PageHeader'
import SyncButton from '../components/SyncButton'
import Button from '../components/ui/Button'
import ErrorState from '../components/ui/ErrorState'
import IconChip from '../components/ui/IconChip'
import Skeleton from '../components/ui/Skeleton'
import { statusColor } from '../utils/status'
import { useCandidateQueue } from '../components/useCandidateQueue'
import usePullToRefresh from '../hooks/usePullToRefresh'

function currentMonth() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

function todayStr() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
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
  const today = todayStr()
  const { pulling, bind: pullBind } = usePullToRefresh(load)

  return (
    <div {...pullBind}>
      {pulling && <p role="status" className="mb-2 text-center text-xs text-brand-600">正在刷新日历…</p>}
      <PageHeader
        title="健身看板"
        subtitle={`${month.replace('-', ' 年 ')} 月 · 已训练 ${days.length} 天`}
      />

      <div
        data-testid="calendar-header"
        className="mb-3 mt-4 flex flex-wrap items-center justify-between gap-2"
      >
        <div className="flex min-w-0 items-center gap-1.5">
          <Button
            variant="secondary"
            ariaLabel="上个月"
            onClick={() => setMonth((m) => shiftMonth(m, -1))}
            className="h-9 w-9 rounded-xl px-0 text-lg shadow-card"
          >‹</Button>
          <h2 data-testid="current-month" className="shrink-0 whitespace-nowrap px-1 text-lg font-black tracking-tight text-ink-900 dark:text-white sm:px-2 sm:text-xl">
            {month.replace('-', ' 年 ')} 月
          </h2>
          <Button
            variant="secondary"
            ariaLabel="下个月"
            onClick={() => setMonth((m) => shiftMonth(m, 1))}
            className="h-9 w-9 rounded-xl px-0 text-lg shadow-card"
          >›</Button>
          {!isCurrentMonth && <Button variant="ghost" onClick={() => setMonth(currentMonth())} className="px-2">今</Button>}
        </div>
        <div data-testid="sync-row" className="min-w-0 max-md:w-full md:max-w-[55%]">
          <SyncButton onSynced={load} />
        </div>
      </div>

      {!loading && !error && (
        <div className="mb-4 grid grid-cols-3 gap-2.5 sm:gap-3" data-testid="calendar-stats">
          {[
            { label: '训练天数', value: days.length, icon: 'dumbbell', chip: 'violet' },
            { label: '训练次数', value: workoutCount, icon: 'flame', chip: 'blue' },
            { label: '待确认', value: pendingCount == null ? '—' : pendingCount, icon: 'alert', chip: 'amber' },
          ].map(({ label, value, icon, chip }) => (
            <div key={label} className="rounded-[18px] border border-line bg-white p-3 shadow-card dark:border-gray-800 dark:bg-gray-900">
              <IconChip icon={icon} variant={chip} />
              <p className="mt-2 text-lg font-black text-ink-900 dark:text-white sm:text-xl">{value}</p>
              <p className="mt-0.5 text-[11px] text-ink-500 dark:text-gray-300">{label}</p>
            </div>
          ))}
        </div>
      )}

      {pendingCount > 0 && (
        <div className="mb-4 flex items-center justify-between gap-3 rounded-2xl border border-amber-200 bg-amber-50 dark:bg-amber-950/50 p-3 text-sm text-amber-900 dark:text-amber-200">
          <span><strong>{pendingCount} 条记录待确认</strong><span className="block text-xs">请检查是否为同一次训练</span></span>
          <Link className="shrink-0 rounded-xl px-3 py-2 font-semibold text-amber-800 dark:text-amber-200 hover:bg-amber-100 dark:hover:bg-amber-900" to="/candidates">
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
          <div className="mb-2 flex flex-wrap gap-1.5 text-[11px] text-ink-500 dark:text-gray-300 sm:gap-2 sm:text-xs">
            <span className="rounded-full bg-emerald-50 px-2 py-1 text-emerald-700 dark:bg-emerald-950/50"><span aria-hidden="true">● </span>已匹配</span>
            <span className="rounded-full bg-indigo-50 px-2 py-1 text-indigo-700 dark:bg-indigo-950/50"><span aria-hidden="true">● </span>仅单源</span>
            <span className="rounded-full bg-amber-50 px-2 py-1 text-amber-700 dark:bg-amber-950/50"><span aria-hidden="true">● </span>待确认</span>
          </div>
          <div className="grid grid-cols-7 gap-1 sm:gap-1.5">
            {WEEKDAYS.map((w) => (
              <div key={w} className="py-1 text-center text-xs font-medium text-ink-400 sm:text-sm">
                {w}
              </div>
            ))}
            {cells.map((date, i) =>
              date === null ? (
                <div key={`empty-${i}`} />
              ) : (
                (() => {
                  const trained = (dayMap[date]?.workouts?.length || 0) > 0
                  const isToday = date === today
                  return (
                    <button
                      key={date}
                      data-testid={`day-${date}`}
                      onClick={() => navigate(`/workouts?date=${date}`)}
                      className={`flex min-h-14 min-w-0 flex-col items-start rounded-xl border p-1 text-xs transition sm:min-h-20 sm:rounded-xl sm:p-1.5 sm:text-sm ${
                        trained
                          ? 'border-brand-200 bg-gradient-to-br from-indigo-50 to-brand-50 font-semibold text-brand-800 hover:shadow-card dark:border-brand-800 dark:bg-brand-950/50 dark:text-brand-200'
                          : 'border-line bg-white text-ink-600 hover:-translate-y-0.5 hover:border-brand-300 hover:shadow-card dark:border-gray-800 dark:bg-gray-900'
                      } ${
                        isToday
                          ? 'ring-2 ring-brand-600 ring-offset-1 dark:ring-brand-400 dark:ring-offset-gray-950'
                          : ''
                      }`}
                    >
                      <span className={isToday ? 'font-black text-brand-700 dark:text-brand-300' : ''}>{Number(date.slice(-2))}</span>
                      <span className="mt-1 w-full space-y-0.5 overflow-hidden text-left">
                        {(dayMap[date]?.workouts || []).slice(0, 1).map((w) => (
                          <span
                            key={w.id}
                            title={w.title}
                            className="flex min-w-0 items-center gap-1 text-[10px] font-medium text-ink-600 dark:text-gray-200"
                          ><span data-testid={`dot-${date}-${w.match_status}`} className={`h-1.5 w-1.5 shrink-0 rounded-full ${statusColor(w.match_status)}` } /><span className="hidden truncate sm:inline">{w.title}</span></span>
                        ))}
                        {(dayMap[date]?.workouts?.length || 0) > 1 && <span className="block pl-2.5 text-[10px] text-brand-600">+{dayMap[date].workouts.length - 1}</span>}
                      </span>
                    </button>
                  )
                })()
              ),
            )}
          </div>
        </>
      )}
    </div>
  )
}
