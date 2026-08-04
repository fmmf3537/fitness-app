import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import { statusLabel } from '../utils/status'

export default function WorkoutListPage() {
  const [searchParams] = useSearchParams()
  const date = searchParams.get('date') || ''
  const month = date.slice(0, 7)
  const [workouts, setWorkouts] = useState([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!month) {
      setLoading(false)
      return
    }
    setLoading(true)
    api(`/api/workouts/calendar?month=${month}`)
      .then((data) => {
        const day = (data.days || []).find((d) => d.date === date)
        setWorkouts(day?.workouts || [])
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }, [month, date])

  return (
    <div>
      <div className="mb-4 flex items-center gap-3">
        <Link to="/" className="text-sm text-indigo-600 hover:underline">
          ← 返回日历
        </Link>
        <h2 className="text-lg font-bold text-gray-900">{date} 训练列表</h2>
      </div>
      {error && <p role="alert" className="mb-4 text-sm text-red-600">加载失败：{error}</p>}
      {loading ? (
        <p className="text-sm text-gray-500">加载中…</p>
      ) : workouts.length === 0 ? (
        <p className="text-sm text-gray-500">当日没有训练记录</p>
      ) : (
        <ul className="space-y-2">
          {workouts.map((w) => (
            <li key={w.id}>
              <Link
                to={`/workouts/${w.id}`}
                className="flex items-center justify-between rounded-md border border-gray-200 bg-white px-4 py-3 shadow-sm hover:border-indigo-400"
              >
                <span className="font-medium text-gray-900">{w.title}</span>
                <span className="text-sm text-gray-500">{statusLabel(w.match_status)}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
