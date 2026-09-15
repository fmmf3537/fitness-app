import { useState } from 'react'
import { api } from '../api/client'
import Button from '../components/ui/Button'
import Card from '../components/ui/Card'
import EmptyState from '../components/ui/EmptyState'
import ErrorState from '../components/ui/ErrorState'
import Skeleton from '../components/ui/Skeleton'
import BottomSheet from '../components/BottomSheet'
import { formatDateTime, formatDuration } from '../utils/status'
import { useCandidateQueue } from '../components/useCandidateQueue'

const SOURCE_LABELS = { xunji: '训记', garmin: '佳明' }

function Metric({ label, value, source }) {
  return (
    <div className="rounded-lg bg-gray-50 dark:bg-gray-950 p-3">
      <p className="text-xs text-gray-500 dark:text-gray-400">{label} · {SOURCE_LABELS[source] || source}</p>
      <p className="mt-1 font-semibold text-gray-900 dark:text-gray-100">{value ?? '无数据'}</p>
    </div>
  )
}

function HeartRatePreview({ points }) {
  if (!points?.length) return <p className="text-sm text-gray-500 dark:text-gray-400">佳明没有可用的心率序列</p>
  const values = points.map((point) => point.hr)
  const min = Math.min(...values)
  const max = Math.max(...values)
  const range = Math.max(1, max - min)
  const coords = values.map((value, index) => {
    const x = values.length === 1 ? 50 : (index / (values.length - 1)) * 100
    const y = 36 - ((value - min) / range) * 30
    return `${x},${y}`
  }).join(' ')
  return (
    <div>
      <svg viewBox="0 0 100 42" className="h-24 w-full" role="img" aria-label={`心率曲线，共 ${points.length} 个采样点`}>
        <polyline points={coords} fill="none" stroke="currentColor" strokeWidth="2" className="text-rose-500" vectorEffect="non-scaling-stroke" />
      </svg>
      <p className="text-xs text-gray-500 dark:text-gray-400">真实佳明心率序列 · {points.length} 个采样点</p>
    </div>
  )
}

function MergePreview({ preview, resolving, error, onCancel, onConfirm }) {
  const workout = preview?.workout
  const sources = preview?.field_sources || {}
  return (
    <BottomSheet
      open={Boolean(preview)}
      onClose={resolving ? undefined : onCancel}
      title="合并预览"
      footer={(
        <div className="flex gap-2">
          <Button variant="secondary" className="flex-1" onClick={onCancel} disabled={resolving}>取消</Button>
          <Button variant="primary" className="flex-1" onClick={onConfirm} disabled={resolving}>
            {resolving ? '正在合并…' : '确认合并'}
          </Button>
        </div>
      )}
    >
      {workout && <div className="space-y-4" data-testid="merge-preview">
        <p className="text-sm text-gray-600 dark:text-gray-300">以下内容由服务器按正式融合规则生成，确认后才会写入训练档案。</p>
        {error && <p role="alert" className="text-sm text-red-600">合并失败：{error}</p>}
        <div className="grid grid-cols-2 gap-2">
          <Metric label="标题" value={workout.title} source={sources.title} />
          <Metric label="日期" value={workout.date} source={sources.date} />
          <Metric label="时长" value={formatDuration(workout.duration_s)} source={sources.duration_s} />
          <Metric label="热量" value={workout.calories != null ? `${workout.calories} kcal` : null} source={sources.calories} />
          <Metric label="平均心率" value={workout.avg_hr != null ? `${workout.avg_hr} bpm` : null} source={sources.avg_hr} />
          <Metric label="最高心率" value={workout.max_hr != null ? `${workout.max_hr} bpm` : null} source={sources.max_hr} />
        </div>
        <section>
          <h3 className="mb-2 text-sm font-semibold text-gray-900 dark:text-gray-100">动作列表 · {SOURCE_LABELS[sources.movements]}</h3>
          {workout.movements?.length ? (
            <ul className="space-y-2">
              {workout.movements.map((movement, index) => (
                <li key={`${movement.name || '动作'}-${index}`} className="rounded-lg border border-gray-200 dark:border-gray-700 p-3 text-sm">
                  <span className="font-medium">{movement.name || `动作 ${index + 1}`}</span>
                  <span className="ml-2 text-gray-500 dark:text-gray-400">{movement.sets?.length || 0} 组</span>
                </li>
              ))}
            </ul>
          ) : <p className="text-sm text-gray-500 dark:text-gray-400">训记没有可用的动作数据</p>}
        </section>
        <section>
          <h3 className="mb-2 text-sm font-semibold text-gray-900 dark:text-gray-100">心率曲线 · {SOURCE_LABELS[sources.heart_rate]}</h3>
          <HeartRatePreview points={workout.heart_rate} />
        </section>
      </div>}
    </BottomSheet>
  )
}

function Side({ title, lines }) {
  return (
    <div className="flex-1 rounded-md bg-gray-50 dark:bg-gray-950 p-3">
      <p className="mb-1 text-xs font-medium text-gray-600 dark:text-gray-400">{title}</p>
      {lines.map((line, i) => (
        <p key={i} className="text-sm text-gray-800 dark:text-gray-200">
          {line}
        </p>
      ))}
    </div>
  )
}

function CandidateCard({ candidate, onResolve, onStale }) {
  const [resolving, setResolving] = useState(false)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [preview, setPreview] = useState(null)
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
      setError(err.status === 409 ? '该候选已被处理' : err.detail || err.message)
      setResolving(false)
      if (err.status === 404 || err.status === 409) onStale()
    }
  }

  const openMergePreview = async () => {
    setPreviewLoading(true)
    setError('')
    try {
      const data = await api(`/api/match-candidates/${candidate.id}/preview`)
      setPreview(data)
    } catch (err) {
      setError(err.status === 409 ? '该候选已被处理' : err.detail || err.message)
      if (err.status === 404 || err.status === 409) onStale()
    } finally {
      setPreviewLoading(false)
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
        <p className="mt-2 text-xs text-gray-600 dark:text-gray-400">原因：{candidate.reason}</p>
        {error && !preview && (
          <p role="alert" className="mt-2 text-sm text-red-600">
            {error}
          </p>
        )}
        <div className="mt-3 flex gap-2">
          {xt && (
            <Button
              variant="primary"
              onClick={openMergePreview}
              disabled={resolving || previewLoading}
            >
              {previewLoading ? '正在读取预览…' : '合并'}
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
        <MergePreview
          preview={preview}
          resolving={resolving}
          error={error}
          onCancel={() => setPreview(null)}
          onConfirm={() => handleResolve('merge')}
        />
      </Card>
    </li>
  )
}

export default function CandidatesPage() {
  const { candidates, loading, refreshing, error, refresh, removeCandidate } = useCandidateQueue()

  const handleResolved = (id) => {
    removeCandidate(id)
    refresh()
  }

  return (
    <div>
      <h2 className="mb-4 text-lg font-bold text-gray-900 dark:text-gray-100">待确认队列</h2>
      {refreshing && <p role="status" className="mb-3 text-sm text-gray-600 dark:text-gray-400">正在刷新待确认记录…</p>}
      {error && (
        <ErrorState
          message={`加载失败：${error}`}
          onRetry={refresh}
          testId="candidates-error"
        />
      )}
      {loading ? (
        <div className="space-y-3">
          <Skeleton className="h-28" />
          <Skeleton className="h-28" />
        </div>
      ) : candidates?.length === 0 && !error ? (
        <EmptyState
          title="没有待确认的候选"
          description="训记与佳明记录已全部匹配完成"
        />
      ) : candidates?.length > 0 ? (
        <ul className="space-y-3">
          {candidates.map((c) => (
            <CandidateCard key={c.id} candidate={c} onResolve={handleResolved} onStale={refresh} />
          ))}
        </ul>
      ) : null}
    </div>
  )
}
