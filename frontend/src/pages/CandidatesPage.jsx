import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import Button from '../components/ui/Button'
import Card from '../components/ui/Card'
import EmptyState from '../components/ui/EmptyState'
import ErrorState from '../components/ui/ErrorState'
import Skeleton from '../components/ui/Skeleton'
import { formatDateTime } from '../utils/status'

function Side({ title, lines }) {
  return (
    <div className="flex-1 rounded-md bg-gray-50 p-3">
      <p className="mb-1 text-xs font-medium text-gray-600">{title}</p>
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
    <li>
      <Card testId={`candidate-${candidate.id}`}>
        <div className="flex flex-col gap-3 sm:flex-row">
          {xt ? (
            <Side title="训记" lines={[xt.title, formatDateTime(xt.start_ms)]} />
          ) : (
            <Side title="训记" lines={['无训记记录']} />
          )}
          <div className="flex items-center justify-center text-gray-500 sm:rotate-0 rotate-90">
            ⇄
          </div>
          {ga ? (
            <Side
              title="佳明"
              lines={[ga.name, formatDateTime(ga.start_ts)]}
            />
          ) : (
            <Side title="佳明" lines={['无佳明记录']} />
          )}
        </div>
        <p className="mt-2 text-xs text-gray-600">原因：{candidate.reason}</p>
        {error && (
          <p role="alert" className="mt-2 text-sm text-red-600">
            {error}
          </p>
        )}
        <div className="mt-3 flex gap-2">
          {xt && (
            <Button
              variant="primary"
              onClick={() => handleResolve('merge')}
              disabled={resolving}
            >
              合并
            </Button>
          )}
          <Button
            variant="secondary"
            onClick={() => handleResolve('split')}
            disabled={resolving}
          >
            保持分开
          </Button>
        </div>
      </Card>
    </li>
  )
}

export default function CandidatesPage() {
  const [candidates, setCandidates] = useState([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  const load = useCallback(() => {
    setLoading(true)
    setError('')
    api('/api/match-candidates')
      .then((data) =>
        setCandidates((data.candidates || []).filter((c) => c.status === 'pending')),
      )
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const handleResolved = (id) => {
    setCandidates((list) => list.filter((c) => c.id !== id))
  }

  return (
    <div>
      <h2 className="mb-4 text-lg font-bold text-gray-900">待确认队列</h2>
      {error && (
        <ErrorState
          message={`加载失败：${error}`}
          onRetry={load}
          testId="candidates-error"
        />
      )}
      {loading ? (
        <div className="space-y-3">
          <Skeleton className="h-28" />
          <Skeleton className="h-28" />
        </div>
      ) : candidates.length === 0 && !error ? (
        <EmptyState
          title="没有待确认的候选"
          description="训记与佳明记录已全部匹配完成"
        />
      ) : candidates.length > 0 ? (
        <ul className="space-y-3">
          {candidates.map((c) => (
            <CandidateCard key={c.id} candidate={c} onResolve={handleResolved} />
          ))}
        </ul>
      ) : null}
    </div>
  )
}
