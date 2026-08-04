import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { formatDateTime } from '../utils/status'

function Side({ title, lines }) {
  return (
    <div className="flex-1 rounded-md bg-gray-50 p-3">
      <p className="mb-1 text-xs font-medium text-gray-500">{title}</p>
      {lines.map((line, i) => (
        <p key={i} className="text-sm text-gray-800">
          {line}
        </p>
      ))}
    </div>
  )
}

function CandidateCard({ candidate, onResolve }) {
  const [resolving, setResolving] = useState(false)
  const [error, setError] = useState('')
  const { xunji_train: xt, garmin_activity: ga } = candidate

  const handleResolve = async (action) => {
    setResolving(true)
    setError('')
    try {
      await api(`/api/match-candidates/${candidate.id}/resolve`, {
        method: 'POST',
        body: JSON.stringify({ action }),
      })
      onResolve(candidate.id)
    } catch (err) {
      setError(err.status === 409 ? '该候选已被处理' : err.message)
      setResolving(false)
    }
  }

  return (
    <li data-testid={`candidate-${candidate.id}`} className="rounded-lg bg-white p-4 shadow">
      <div className="flex flex-col gap-3 sm:flex-row">
        {xt ? (
          <Side title="训记" lines={[xt.title, formatDateTime(xt.start_ms)]} />
        ) : (
          <Side title="训记" lines={['无训记记录']} />
        )}
        <div className="flex items-center justify-center text-gray-400">⇄</div>
        {ga ? (
          <Side
            title="佳明"
            lines={[ga.name, formatDateTime(ga.start_ts)]}
          />
        ) : (
          <Side title="佳明" lines={['无佳明记录']} />
        )}
      </div>
      <p className="mt-2 text-xs text-gray-500">原因：{candidate.reason}</p>
      {error && (
        <p role="alert" className="mt-2 text-sm text-red-600">
          {error}
        </p>
      )}
      <div className="mt-3 flex gap-2">
        {xt && (
          <button
            onClick={() => handleResolve('merge')}
            disabled={resolving}
            className="rounded-md bg-indigo-600 px-4 py-1.5 text-sm text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            合并
          </button>
        )}
        <button
          onClick={() => handleResolve('split')}
          disabled={resolving}
          className="rounded-md bg-gray-200 px-4 py-1.5 text-sm text-gray-800 hover:bg-gray-300 disabled:opacity-50"
        >
          保持分开
        </button>
      </div>
    </li>
  )
}

export default function CandidatesPage() {
  const [candidates, setCandidates] = useState([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api('/api/match-candidates')
      .then((data) =>
        setCandidates((data.candidates || []).filter((c) => c.status === 'pending')),
      )
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }, [])

  const handleResolved = (id) => {
    setCandidates((list) => list.filter((c) => c.id !== id))
  }

  return (
    <div>
      <h2 className="mb-4 text-lg font-bold text-gray-900">待确认队列</h2>
      {error && <p role="alert" className="mb-4 text-sm text-red-600">加载失败：{error}</p>}
      {loading ? (
        <p className="text-sm text-gray-500">加载中…</p>
      ) : candidates.length === 0 ? (
        <p className="text-sm text-gray-500">没有待确认的候选</p>
      ) : (
        <ul className="space-y-3">
          {candidates.map((c) => (
            <CandidateCard key={c.id} candidate={c} onResolve={handleResolved} />
          ))}
        </ul>
      )}
    </div>
  )
}
