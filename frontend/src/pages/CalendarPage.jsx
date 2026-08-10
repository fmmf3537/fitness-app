import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import SyncButton from '../components/SyncButton'
import { statusColor } from '../utils/status'

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
  const [month, setMonth] = useState(initialMonth || currentMonth())
  const [days, setDays] = useState([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  const load = useCallback(() => {
    setLoading(true)
    setError('')
    api(`/api/workouts/calendar?month=${month}`)
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

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <button
          aria-label="上个月"
          onClick={() => setMonth((m) => shiftMonth(m, -1))}
          className="rounded-md bg-white px-3 py-1.5 shadow hover:bg-gray-100"
        >
          ← 上个月
        </button>
        <h2 data-testid="current-month" className="text-lg font-bold text-gray-900">
          {month}
        </h2>
        <div className="flex items-center gap-2">
          <SyncButton onSynced={load} />
          <button
            aria-label="下个月"
            onClick={() => setMonth((m) => shiftMonth(m, 1))}
            className="rounded-md bg-white px-3 py-1.5 shadow hover:bg-gray-100"
          >
            下个月 →
          </button>
        </div>
      </div>

      {error && <p role="alert" className="mb-4 text-sm text-red-600">加载失败：{error}</p>}
      {loading && <p className="mb-4 text-sm text-gray-500">加载中…</p>}

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
              className={`flex min-h-16 flex-col items-center rounded-md border border-gray-200 bg-white p-1 text-sm hover:border-indigo-400 ${
                (dayMap[date]?.workouts?.length || 0) > 0 ? 'bg-indigo-50' : ''
              }`}
            >
              <span className="text-gray-800">{Number(date.slice(-2))}</span>
              <span className="mt-1 flex flex-wrap justify-center gap-1">
                {(dayMap[date]?.workouts || []).map((w) => (
                  <span
                    key={w.id}
                    data-testid={`dot-${date}-${w.match_status}`}
                    title={w.title}
                    className={`h-2 w-2 rounded-full ${statusColor(w.match_status)}`}
                  />
                ))}
              </span>
            </button>
          ),
        )}
      </div>

      <div className="mt-4 flex flex-wrap gap-3 text-xs text-gray-600">
        <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-green-500" />自动匹配</span>
        <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-blue-500" />手动匹配</span>
        <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-yellow-400" />仅训记</span>
        <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-purple-500" />仅佳明</span>
        <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-orange-500" />待确认</span>
      </div>
    </div>
  )
}
