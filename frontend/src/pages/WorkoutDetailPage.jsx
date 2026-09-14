import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api } from '../api/client'
import HeartRateChart from '../components/HeartRateChart'
import NextAdviceSection from '../components/NextAdviceSection'
import SessionReviewSection from '../components/SessionReviewSection'
import Badge from '../components/ui/Badge'
import Button from '../components/ui/Button'
import Card from '../components/ui/Card'
import ConfirmDialog from '../components/ui/ConfirmDialog'
import ErrorState from '../components/ui/ErrorState'
import { SkeletonText } from '../components/ui/Skeleton'
import { formatDuration, statusLabel } from '../utils/status'

const TABS = [
  { key: 'fused', label: '融合' },
  { key: 'xunji', label: '训记原始' },
  { key: 'garmin', label: '佳明原始' },
]

/** match_status → Badge 变体（与日历图例语义对齐） */
const MATCH_BADGE = {
  auto_matched: 'green',
  manual_matched: 'indigo',
  pending: 'amber',
}

function matchBadgeVariant(status) {
  return MATCH_BADGE[status] || 'gray'
}

function SummaryCard({ workout }) {
  const items = [
    { label: '时长', value: formatDuration(workout.duration_s) },
    { label: '热量', value: workout.calories != null ? `${workout.calories} 千卡` : '-' },
    { label: '平均心率', value: workout.avg_hr != null ? `${workout.avg_hr} bpm` : '-' },
    { label: '最大心率', value: workout.max_hr != null ? `${workout.max_hr} bpm` : '-' },
  ]
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      {items.map((item) => (
        <Card key={item.label}>
          <p className="text-sm text-gray-600 dark:text-gray-400">{item.label}</p>
          <p className="mt-1 text-lg font-bold text-gray-900 dark:text-gray-100">{item.value}</p>
        </Card>
      ))}
    </div>
  )
}

function MovementsTable({ movements, setHr }) {
  if (!movements || movements.length === 0) {
    return <p className="text-sm text-gray-600 dark:text-gray-400">无动作数据</p>
  }
  const hrMap = new Map(
    (setHr || []).map((r) => [`${r.movement_name}|${r.set_index}`, r]),
  )
  const showHr = Array.isArray(setHr) && setHr.length > 0
  const fmt = (v) => (v == null ? '-' : v)
  return (
    <div className="space-y-4">
      {movements.map((mv, idx) => (
        <Card key={`${mv.name}-${idx}`}>
          <h3 className="mb-2 font-bold text-gray-900 dark:text-gray-100">{mv.name}</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-sm whitespace-nowrap">
            <thead>
              <tr className="text-left text-gray-600 dark:text-gray-400">
                <th className="py-1">组</th>
                <th className="py-1">重量 × 次数</th>
                <th className="py-1">RPE</th>
                <th className="py-1">完成</th>
                {showHr && <th className="py-1">心率 均/峰/恢复</th>}
              </tr>
            </thead>
            <tbody>
              {(mv.sets || []).map((s, i) => {
                const row = showHr ? hrMap.get(`${mv.name}|${i + 1}`) : null
                const cellText = row
                  ? `${row.confidence === 'low' ? '~' : ''}${fmt(row.hr_avg)}/${fmt(row.hr_max)}/${fmt(row.hr_recovery_30s)}`
                  : '-'
                const title =
                  row && row.confidence === 'low'
                    ? '低置信度：佳明动作识别与训记动作不一致，心率仅供参考'
                    : '组中心率 均值/峰值/组后30s恢复（bpm）'
                return (
                  <tr key={i} className="border-t border-gray-100 dark:border-gray-800">
                    <td className="py-1">{i + 1}</td>
                    <td className="py-1">
                      {s.weight}
                      {s.unit} × {s.reps}
                    </td>
                    <td className="py-1">{s.rpe != null ? `RPE ${s.rpe}` : '-'}</td>
                    <td className="py-1">{s.done ? '✓' : '✗'}</td>
                    {showHr && (
                      <td
                        className="py-1"
                        data-testid="set-hr-cell"
                        title={title}
                      >
                        {cellText}
                      </td>
                    )}
                  </tr>
                )
              })}
            </tbody>
            </table>
          </div>
        </Card>
      ))}
    </div>
  )
}

function RawJson({ data, testId }) {
  if (data == null) {
    return <p className="text-sm text-gray-600 dark:text-gray-400">无原始数据</p>
  }
  return (
    <pre
      data-testid={testId}
      className="max-h-[32rem] overflow-auto rounded-lg bg-gray-900 p-4 text-xs text-gray-100 dark:bg-black dark:text-gray-300"
    >
      {JSON.stringify(data, null, 2)}
    </pre>
  )
}

export default function WorkoutDetailPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [workout, setWorkout] = useState(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [tab, setTab] = useState('fused')
  const [deleting, setDeleting] = useState(false)
  const [confirmOpen, setConfirmOpen] = useState(false)

  const load = useCallback(() => {
    setLoading(true)
    setError('')
    api(`/api/workouts/${id}`)
      .then(setWorkout)
      .catch((err) => setError(err.status === 404 ? '训练不存在' : err.message))
      .finally(() => setLoading(false))
  }, [id])

  useEffect(() => {
    load()
  }, [load])

  // V3-11：软删除（原始数据保留，可在「设置 → 已删除的训练」恢复）
  const handleDelete = async () => {
    setConfirmOpen(false)
    setDeleting(true)
    try {
      await api(`/api/workouts/${id}`, { method: 'DELETE' })
      navigate('/')
    } catch (err) {
      setError(`删除失败：${err.detail || err.message}`)
      setDeleting(false)
    }
  }

  if (loading) {
    return (
      <div className="space-y-3">
        <SkeletonText lines={4} testId="detail-skeleton" />
      </div>
    )
  }
  if (error) {
    return (
      <ErrorState message={error} onRetry={load} testId="detail-error" />
    )
  }
  if (!workout) return null

  return (
    <div>
      <div className="mb-4 flex items-center gap-3">
        <Link to="/" className="text-sm text-indigo-600 hover:underline">
          ← 返回日历
        </Link>
        <h2 className="text-lg font-bold text-gray-900 dark:text-gray-100">
          {workout.title}
          <span className="ml-2 text-sm font-normal text-gray-600 dark:text-gray-400">
            {workout.date} ·{' '}
            <Badge variant={matchBadgeVariant(workout.match_status)}>
              {statusLabel(workout.match_status)}
            </Badge>
          </span>
        </h2>
      </div>

      <SummaryCard workout={workout} />

      <div className="mt-4 flex gap-1 border-b border-gray-200 dark:border-gray-700">
        {TABS.map((t) => (
          <button
            key={t.key}
            role="tab"
            aria-selected={tab === t.key}
            onClick={() => setTab(t.key)}
            className={`px-4 min-h-[44px] text-sm font-medium ${
              tab === t.key
                ? 'border-b-2 border-indigo-600 text-indigo-600'
                : 'text-gray-600 dark:text-gray-400 hover:text-gray-800'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="mt-4">
        {tab === 'fused' && (
          <div className="space-y-4">
            <MovementsTable movements={workout.movements} setHr={workout.set_hr} />
            {workout.heart_rate && workout.heart_rate.length > 0 ? (
              <Card>
                <HeartRateChart data={workout.heart_rate} />
              </Card>
            ) : (
              <p className="text-sm text-gray-600 dark:text-gray-400">无心率数据</p>
            )}
            <SessionReviewSection workout={workout} />
            <NextAdviceSection workout={workout} />
          </div>
        )}
        {tab === 'xunji' && <RawJson data={workout.xunji_raw} testId="xunji-raw" />}
        {tab === 'garmin' && <RawJson data={workout.garmin_raw} testId="garmin-raw" />}
      </div>

      <div className="mt-8 border-t border-gray-200 dark:border-gray-700 pt-4">
        <Button
          variant="danger"
          testId="delete-workout"
          disabled={deleting}
          onClick={() => setConfirmOpen(true)}
        >
          {deleting ? '删除中…' : '删除此训练'}
        </Button>
      </div>

      <ConfirmDialog
        open={confirmOpen}
        title="确定删除这次训练吗？"
        description="关联的 AI 点评与下次建议会一并删除，原始数据保留，之后可在「设置 → 已删除的训练」中恢复。"
        danger
        onConfirm={handleDelete}
        onCancel={() => setConfirmOpen(false)}
      />
    </div>
  )
}
