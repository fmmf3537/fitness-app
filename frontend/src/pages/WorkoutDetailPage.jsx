import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api } from '../api/client'
import HeartRateChart from '../components/HeartRateChart'
import NextAdviceSection from '../components/NextAdviceSection'
import SessionReviewSection from '../components/SessionReviewSection'
import { formatDuration, statusLabel } from '../utils/status'

const TABS = [
  { key: 'fused', label: '融合' },
  { key: 'xunji', label: '训记原始' },
  { key: 'garmin', label: '佳明原始' },
]

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
        <div key={item.label} className="rounded-lg bg-white p-4 shadow">
          <p className="text-sm text-gray-500">{item.label}</p>
          <p className="mt-1 text-lg font-bold text-gray-900">{item.value}</p>
        </div>
      ))}
    </div>
  )
}

function MovementsTable({ movements, setHr }) {
  if (!movements || movements.length === 0) {
    return <p className="text-sm text-gray-500">无动作数据</p>
  }
  const hrMap = new Map(
    (setHr || []).map((r) => [`${r.movement_name}|${r.set_index}`, r]),
  )
  const showHr = Array.isArray(setHr) && setHr.length > 0
  const fmt = (v) => (v == null ? '-' : v)
  return (
    <div className="space-y-4">
      {movements.map((mv, idx) => (
        <div key={`${mv.name}-${idx}`} className="rounded-lg bg-white p-4 shadow">
          <h3 className="mb-2 font-bold text-gray-900">{mv.name}</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-sm whitespace-nowrap">
            <thead>
              <tr className="text-left text-gray-500">
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
                  <tr key={i} className="border-t border-gray-100">
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
        </div>
      ))}
    </div>
  )
}

function RawJson({ data, testId }) {
  if (data == null) {
    return <p className="text-sm text-gray-500">无原始数据</p>
  }
  return (
    <pre
      data-testid={testId}
      className="max-h-[32rem] overflow-auto rounded-lg bg-gray-900 p-4 text-xs text-gray-100"
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

  useEffect(() => {
    setLoading(true)
    api(`/api/workouts/${id}`)
      .then(setWorkout)
      .catch((err) => setError(err.status === 404 ? '训练不存在' : err.message))
      .finally(() => setLoading(false))
  }, [id])

  // V3-11：软删除（原始数据保留，可在「设置 → 已删除的训练」恢复）
  const handleDelete = async () => {
    const ok = window.confirm(
      '确定删除这次训练吗？关联的 AI 点评与下次建议会一并删除，' +
        '原始数据保留，之后可在「设置 → 已删除的训练」中恢复。',
    )
    if (!ok) return
    setDeleting(true)
    try {
      await api(`/api/workouts/${id}`, { method: 'DELETE' })
      navigate('/')
    } catch (err) {
      setError(`删除失败：${err.detail || err.message}`)
      setDeleting(false)
    }
  }

  if (loading) return <p className="text-sm text-gray-500">加载中…</p>
  if (error) return <p role="alert" className="text-sm text-red-600">{error}</p>
  if (!workout) return null

  return (
    <div>
      <div className="mb-4 flex items-center gap-3">
        <Link to="/" className="text-sm text-indigo-600 hover:underline">
          ← 返回日历
        </Link>
        <h2 className="text-lg font-bold text-gray-900">
          {workout.title}
          <span className="ml-2 text-sm font-normal text-gray-500">
            {workout.date} · {statusLabel(workout.match_status)}
          </span>
        </h2>
      </div>

      <SummaryCard workout={workout} />

      <div className="mt-4 flex gap-1 border-b border-gray-200">
        {TABS.map((t) => (
          <button
            key={t.key}
            role="tab"
            aria-selected={tab === t.key}
            onClick={() => setTab(t.key)}
            className={`px-4 py-2 text-sm font-medium ${
              tab === t.key
                ? 'border-b-2 border-indigo-600 text-indigo-600'
                : 'text-gray-500 hover:text-gray-800'
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
              <div className="rounded-lg bg-white p-4 shadow">
                <HeartRateChart data={workout.heart_rate} />
              </div>
            ) : (
              <p className="text-sm text-gray-500">无心率数据</p>
            )}
            <SessionReviewSection workout={workout} />
            <NextAdviceSection workout={workout} />
          </div>
        )}
        {tab === 'xunji' && <RawJson data={workout.xunji_raw} testId="xunji-raw" />}
        {tab === 'garmin' && <RawJson data={workout.garmin_raw} testId="garmin-raw" />}
      </div>

      <div className="mt-8 border-t border-gray-200 pt-4">
        <button
          data-testid="delete-workout"
          onClick={handleDelete}
          disabled={deleting}
          className="rounded-md border border-red-300 px-3 py-1.5 text-sm text-red-600 hover:bg-red-50 disabled:opacity-50"
        >
          {deleting ? '删除中…' : '删除此训练'}
        </button>
      </div>
    </div>
  )
}
