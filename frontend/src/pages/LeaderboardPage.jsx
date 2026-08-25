import { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import { useCurrentUser } from '../contexts/CurrentUserContext'

const METRICS = [
  { id: 'frequency', label: '训练频率' },
  { id: 'volume', label: '总容量' },
  { id: 'calories', label: '总热量' },
  { id: 'streak', label: '连续天数' },
]

const WINDOWS = [
  { id: '7d', label: '7 天' },
  { id: '30d', label: '30 天' },
]

export default function LeaderboardPage() {
  const currentUser = useCurrentUser()
  const [searchParams, setSearchParams] = useSearchParams()
  const metric = searchParams.get('metric') || 'frequency'
  const window = searchParams.get('window') || '7d'
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const setQuery = (key, value) => {
    const next = new URLSearchParams(searchParams)
    next.set(key, value)
    setSearchParams(next)
  }

  const load = useCallback(() => {
    setLoading(true)
    setError('')
    return api(`/api/leaderboard?metric=${metric}&window=${window}`)
      .then(setData)
      .catch((err) => {
        if (err.status === 400) setError('参数无效')
        else if (err.status === 401) setError('请重新登录')
        else setError(err.message || '加载失败')
      })
      .finally(() => setLoading(false))
  }, [metric, window])

  useEffect(() => {
    load()
  }, [load])

  const entries = data?.entries || []
  const myEntry = currentUser
    ? entries.find((e) => e.user_id === currentUser.user_id)
    : null
  const others = entries.filter((e) => e.user_id !== currentUser?.user_id)

  return (
    <div className="space-y-4" data-testid="leaderboard-page">
      <h1 className="text-xl font-bold text-gray-900">排行榜</h1>

      <div className="flex flex-wrap gap-2" data-testid="metric-tabs">
        {METRICS.map((m) => (
          <button
            key={m.id}
            type="button"
            data-testid={`metric-tab-${m.id}`}
            onClick={() => setQuery('metric', m.id)}
            className={`rounded-md px-3 py-1.5 text-sm font-medium ${
              metric === m.id
                ? 'bg-indigo-600 text-white'
                : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
            }`}
          >
            {m.label}
          </button>
        ))}
      </div>

      <div className="flex gap-2" data-testid="window-tabs">
        {WINDOWS.map((w) => (
          <button
            key={w.id}
            type="button"
            data-testid={`window-tab-${w.id}`}
            onClick={() => setQuery('window', w.id)}
            className={`rounded-md px-3 py-1.5 text-sm ${
              window === w.id
                ? 'border border-indigo-600 text-indigo-700'
                : 'border border-gray-300 text-gray-600'
            }`}
          >
            {w.label}
          </button>
        ))}
      </div>

      {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
      {loading && <p className="text-sm text-gray-500">加载中…</p>}

      {!loading && !error && myEntry && (
        <div
          data-testid="my-rank-card"
          className="rounded-lg border-2 border-indigo-400 bg-indigo-50 p-4"
        >
          <p className="text-xs font-medium text-indigo-700">我的排名</p>
          <p className="text-lg font-bold text-indigo-900">
            #{myEntry.rank} · {myEntry.username} · {myEntry.value}
          </p>
        </div>
      )}

      {!loading && !error && (
        <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white shadow-sm">
          <table className="w-full text-left text-sm" data-testid="leaderboard-table">
            <thead className="border-b border-gray-200 bg-gray-50 text-gray-600">
              <tr>
                <th className="px-3 py-2">排名</th>
                <th className="px-3 py-2">用户</th>
                <th className="px-3 py-2">数值</th>
              </tr>
            </thead>
            <tbody>
              {others.map((e) => (
                <tr key={e.user_id} className="border-b border-gray-100">
                  <td className="px-3 py-2">{e.rank}</td>
                  <td className="px-3 py-2">{e.username}</td>
                  <td className="px-3 py-2">{e.value}</td>
                </tr>
              ))}
              {others.length === 0 && !myEntry && (
                <tr>
                  <td colSpan={3} className="px-3 py-4 text-center text-gray-500">
                    暂无数据
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
