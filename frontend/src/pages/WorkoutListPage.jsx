import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import PageHeader from '../components/PageHeader'
import Badge from '../components/ui/Badge'
import EmptyState from '../components/ui/EmptyState'
import ErrorState from '../components/ui/ErrorState'
import Skeleton from '../components/ui/Skeleton'
import { statusLabel } from '../utils/status'

/** match_status → Badge 变体（与日历图例语义对齐） */
const MATCH_BADGE = {
  auto_matched: 'green',
  manual_matched: 'indigo',
  pending: 'amber',
}

function matchBadgeVariant(status) {
  return MATCH_BADGE[status] || 'gray'
}

export default function WorkoutListPage() {
  const [searchParams] = useSearchParams()
  const date = searchParams.get('date') || ''
  const month = date.slice(0, 7)
  const [workouts, setWorkouts] = useState([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  const load = useCallback(() => {
    if (!month) {
      setLoading(false)
      return
    }
    setLoading(true)
    setError('')
    api(`/api/workouts/calendar?month=${month}`)
      .then((data) => {
        const day = (data.days || []).find((d) => d.date === date)
        setWorkouts(day?.workouts || [])
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }, [month, date])

  useEffect(() => {
    load()
  }, [load])

  // 无 date 参数时兜底，避免渲染空标题
  if (!date) {
    return (
      <EmptyState
        testId="no-date"
        title="未指定日期"
        description="请从训练日历选择一天查看"
        action={
          <Link
            to="/"
            className="inline-flex min-h-[44px] items-center text-brand-600 hover:underline"
          >
            ← 返回日历
          </Link>
        }
      />
    )
  }

  return (
    <div>
      <PageHeader
        title={`${date} 训练`}
        subtitle="当日全部训练记录"
        back
      />
      <div className="mb-4 mt-4">
        <Link to="/" className="text-sm font-semibold text-brand-600 hover:underline">
          ← 返回日历
        </Link>
      </div>
      {error && (
        <ErrorState
          message={`加载失败：${error}`}
          onRetry={load}
          testId="list-error"
        />
      )}
      {loading ? (
        <div className="space-y-2">
          <Skeleton className="h-14" />
          <Skeleton className="h-14" />
          <Skeleton className="h-14" />
        </div>
      ) : workouts.length === 0 && !error ? (
        <EmptyState
          title="当日没有训练记录"
          description="换个日期看看，或回到日历同步数据"
        />
      ) : workouts.length > 0 ? (
        <ul className="space-y-2.5">
          {workouts.map((w) => (
            <li key={w.id}>
              <Link
                to={`/workouts/${w.id}`}
                className="flex items-center justify-between rounded-[18px] border border-line bg-white px-4 py-3.5 shadow-card transition hover:-translate-y-0.5 hover:border-brand-300 hover:shadow-lift dark:border-gray-800 dark:bg-gray-900"
              >
                <span className="font-semibold text-ink-900 dark:text-gray-100">{w.title}</span>
                <Badge variant={matchBadgeVariant(w.match_status)}>
                  {statusLabel(w.match_status)}
                </Badge>
              </Link>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}
