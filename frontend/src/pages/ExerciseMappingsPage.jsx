import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError } from '../api/client'
import PageHeader from '../components/PageHeader'
import Badge from '../components/ui/Badge'
import Button from '../components/ui/Button'
import Card from '../components/ui/Card'
import EmptyState from '../components/ui/EmptyState'
import ErrorState from '../components/ui/ErrorState'
import Skeleton from '../components/ui/Skeleton'
import { useToast } from '../components/ui/useToast'

const STATUS_OPTIONS = [
  { value: '', label: '全部' },
  { value: 'draft', label: 'draft' },
  { value: 'active', label: 'active' },
  { value: 'disabled', label: 'disabled' },
  { value: 'not_applicable', label: 'not_applicable' },
]

const CONFIDENCE_OPTIONS = [
  { value: '', label: '全部' },
  { value: 'high', label: 'high' },
  { value: 'medium', label: 'medium' },
  { value: 'low', label: 'low' },
]

const WEIGHT_LABELS = {
  total: '总重',
  per_hand: '单只',
  bodyweight: '自重',
  assisted: '辅助',
}

const WEIGHT_OPTIONS = [
  { value: 'total', label: '总重' },
  { value: 'per_hand', label: '单只' },
  { value: 'bodyweight', label: '自重' },
  { value: 'assisted', label: '辅助' },
]

const STATUS_BADGE = {
  draft: 'amber',
  active: 'green',
  disabled: 'gray',
  not_applicable: 'gray',
  missing: 'red',
}

const CONFIDENCE_BADGE = {
  high: 'green',
  medium: 'indigo',
  low: 'amber',
  none: 'gray',
}

function weightLabel(strategy) {
  return WEIGHT_LABELS[strategy] || strategy || '—'
}

function errorMessage(err) {
  if (err instanceof ApiError) {
    if (err.detail && typeof err.detail === 'object' && err.detail.message) {
      return err.detail.message
    }
    if (typeof err.detail === 'string' && err.detail) return err.detail
    return err.message
  }
  return err?.message || '请求失败'
}

function buildListQuery({ status, confidence, keyword, page, pageSize }) {
  const params = new URLSearchParams()
  if (status) params.set('status', status)
  if (confidence) params.set('confidence', confidence)
  if (keyword) params.set('keyword', keyword)
  params.set('page', String(page))
  params.set('page_size', String(pageSize))
  return `/api/exercise-mappings?${params.toString()}`
}

export default function ExerciseMappingsPage() {
  const { toast } = useToast()

  const [coverage, setCoverage] = useState(null)
  const [coverageError, setCoverageError] = useState('')
  const [coverageLoading, setCoverageLoading] = useState(true)

  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [pages, setPages] = useState(1)
  const [page, setPage] = useState(1)
  const [listError, setListError] = useState('')
  const [listLoading, setListLoading] = useState(true)

  const [status, setStatus] = useState('')
  const [confidence, setConfidence] = useState('')
  const [keywordInput, setKeywordInput] = useState('')
  const [keyword, setKeyword] = useState('')

  const [staleSyncs, setStaleSyncs] = useState([])
  const [staleOpen, setStaleOpen] = useState(false)

  const [rowBusy, setRowBusy] = useState({})
  const [batchBusy, setBatchBusy] = useState(false)

  const [editingId, setEditingId] = useState(null)
  const [editForm, setEditForm] = useState(null)
  const [editError, setEditError] = useState('')
  const [editSaving, setEditSaving] = useState(false)
  const [categories, setCategories] = useState([])
  const [exerciseQuery, setExerciseQuery] = useState('')
  const [exerciseResults, setExerciseResults] = useState([])
  const [exerciseSearching, setExerciseSearching] = useState(false)

  const pageSize = 50

  const loadCoverage = useCallback(() => {
    setCoverageLoading(true)
    setCoverageError('')
    return api('/api/exercise-mappings/coverage')
      .then((data) => setCoverage(data))
      .catch((err) => setCoverageError(errorMessage(err)))
      .finally(() => setCoverageLoading(false))
  }, [])

  const loadList = useCallback(() => {
    setListLoading(true)
    setListError('')
    return api(buildListQuery({ status, confidence, keyword, page, pageSize }))
      .then((data) => {
        setItems(data.items || [])
        setTotal(data.total ?? 0)
        setPages(data.pages ?? 1)
      })
      .catch((err) => setListError(errorMessage(err)))
      .finally(() => setListLoading(false))
  }, [status, confidence, keyword, page, pageSize])

  const loadStale = useCallback(() => {
    return api('/api/exercise-mappings/stale-syncs?limit=50')
      .then((data) => setStaleSyncs(Array.isArray(data) ? data : []))
      .catch(() => setStaleSyncs([]))
  }, [])

  useEffect(() => {
    loadCoverage()
    loadStale()
  }, [loadCoverage, loadStale])

  useEffect(() => {
    loadList()
  }, [loadList])

  // 关键词 300ms 防抖；仅在实际变更时重置页码（避免挂载防抖把用户刚点的分页打回第 1 页）
  useEffect(() => {
    const timer = setTimeout(() => {
      const next = keywordInput.trim()
      setKeyword((prev) => (prev === next ? prev : next))
    }, 300)
    return () => clearTimeout(timer)
  }, [keywordInput])

  const keywordInitRef = useRef(true)
  useEffect(() => {
    if (keywordInitRef.current) {
      keywordInitRef.current = false
      return
    }
    setPage(1)
  }, [keyword])

  // 打开编辑时拉 category 选项（catalog limit=100 去重）
  useEffect(() => {
    if (editingId == null) return
    let cancelled = false
    api('/api/exercise-mappings/catalog?limit=100')
      .then((rows) => {
        if (cancelled) return
        const set = new Set()
        for (const row of rows || []) {
          if (row.category) set.add(row.category)
        }
        if (editForm?.garmin_category) set.add(editForm.garmin_category)
        setCategories([...set].sort())
      })
      .catch(() => {
        if (!cancelled && editForm?.garmin_category) {
          setCategories([editForm.garmin_category])
        }
      })
    return () => {
      cancelled = true
    }
  }, [editingId, editForm?.garmin_category])

  // 动作搜索防抖
  useEffect(() => {
    if (editingId == null) return
    const q = exerciseQuery.trim()
    if (!q) {
      setExerciseResults([])
      return undefined
    }
    let cancelled = false
    const timer = setTimeout(() => {
      setExerciseSearching(true)
      const params = new URLSearchParams({ q, limit: '30' })
      if (editForm?.garmin_category) params.set('category', editForm.garmin_category)
      api(`/api/exercise-mappings/catalog?${params.toString()}`)
        .then((rows) => {
          if (!cancelled) setExerciseResults(Array.isArray(rows) ? rows : [])
        })
        .catch(() => {
          if (!cancelled) setExerciseResults([])
        })
        .finally(() => {
          if (!cancelled) setExerciseSearching(false)
        })
    }, 250)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [exerciseQuery, editingId, editForm?.garmin_category])

  const setBusy = (id, busy) => {
    setRowBusy((prev) => ({ ...prev, [id]: busy }))
  }

  const handleActivate = async (row) => {
    setBusy(row.id, true)
    try {
      await api(`/api/exercise-mappings/${row.id}/activate`, { method: 'POST', body: JSON.stringify({}) })
      toast('已采纳')
      await Promise.all([loadCoverage(), loadList()])
    } catch (err) {
      toast(errorMessage(err), 'error')
    } finally {
      setBusy(row.id, false)
    }
  }

  const handleDisable = async (row) => {
    setBusy(row.id, true)
    try {
      await api(`/api/exercise-mappings/${row.id}/disable`, { method: 'POST', body: JSON.stringify({}) })
      toast('已停用')
      await Promise.all([loadCoverage(), loadList()])
    } catch (err) {
      toast(errorMessage(err), 'error')
    } finally {
      setBusy(row.id, false)
    }
  }

  const handleBatchActivate = async () => {
    setBatchBusy(true)
    try {
      const result = await api('/api/exercise-mappings/batch-activate', {
        method: 'POST',
        body: JSON.stringify({ confidence: 'high' }),
      })
      toast(`已采纳 ${result.activated ?? 0} 条`)
      await Promise.all([loadCoverage(), loadList()])
    } catch (err) {
      toast(errorMessage(err), 'error')
    } finally {
      setBatchBusy(false)
    }
  }

  const openEdit = async (row) => {
    setEditError('')
    setExerciseQuery('')
    setExerciseResults([])
    setEditingId(row.id)
    setEditForm({
      xunji_name: row.xunji_name || '',
      garmin_category: row.garmin_category || '',
      garmin_exercise_name: row.garmin_exercise_name || '',
      garmin_display_name: row.garmin_display_name || '',
      weight_strategy: row.weight_strategy || 'total',
      reason: '',
    })
    try {
      const detail = await api(`/api/exercise-mappings/${row.id}`)
      setEditForm((prev) => ({
        ...prev,
        xunji_name: detail.xunji_name || prev.xunji_name,
        garmin_category: detail.garmin_category || '',
        garmin_exercise_name: detail.garmin_exercise_name || '',
        garmin_display_name: detail.garmin_display_name || '',
        weight_strategy: detail.weight_strategy || 'total',
      }))
    } catch {
      // 列表行数据已够用，详情失败不阻断编辑
    }
  }

  const closeEdit = () => {
    if (editSaving) return
    setEditingId(null)
    setEditForm(null)
    setEditError('')
    setExerciseQuery('')
    setExerciseResults([])
  }

  const handleSaveEdit = async () => {
    if (!editingId || !editForm) return
    setEditSaving(true)
    setEditError('')
    const body = {
      garmin_category: editForm.garmin_category || null,
      garmin_exercise_name: editForm.garmin_exercise_name ?? '',
      garmin_display_name: editForm.garmin_display_name ?? '',
      weight_strategy: editForm.weight_strategy || undefined,
    }
    if (editForm.reason?.trim()) body.reason = editForm.reason.trim()
    try {
      await api(`/api/exercise-mappings/${editingId}`, {
        method: 'PATCH',
        body: JSON.stringify(body),
      })
      toast('已保存')
      setEditingId(null)
      setEditForm(null)
      await Promise.all([loadCoverage(), loadList()])
    } catch (err) {
      if (err instanceof ApiError && err.status === 422) {
        setEditError(errorMessage(err))
      } else {
        setEditError(errorMessage(err))
        toast(errorMessage(err), 'error')
      }
    } finally {
      setEditSaving(false)
    }
  }

  const pickExercise = (row) => {
    setEditForm((prev) => ({
      ...prev,
      garmin_category: row.category || prev.garmin_category,
      garmin_exercise_name: row.exercise || '',
      garmin_display_name: row.name || '',
    }))
    setExerciseQuery('')
    setExerciseResults([])
  }

  const clearExercise = () => {
    setEditForm((prev) => ({
      ...prev,
      garmin_exercise_name: '',
      garmin_display_name: '',
    }))
  }

  const cov = coverage?.coverage || {}
  const byStatus = coverage?.by_status || {}

  return (
    <div className="space-y-4">
      <PageHeader title="动作映射" subtitle="覆盖率看板与映射复核" back />

      {staleSyncs.length > 0 && (
        <div
          data-testid="stale-alert"
          className="rounded-2xl border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-100"
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p>
              有 {staleSyncs.length} 条已同步训练使用的映射已更新，可能需要重新同步
            </p>
            <Button
              variant="secondary"
              size="compact"
              onClick={() => setStaleOpen((v) => !v)}
            >
              {staleOpen ? '收起' : '展开'}
            </Button>
          </div>
          {staleOpen && (
            <ul data-testid="stale-list" className="mt-3 space-y-1.5 text-xs">
              {staleSyncs.map((s) => (
                <li
                  key={s.sync_id}
                  className="rounded-xl border border-amber-200/80 bg-white/70 px-3 py-2 dark:border-amber-900 dark:bg-gray-900/60"
                >
                  <span className="font-medium">{s.plan_ref || '—'}</span>
                  {' · '}
                  {s.training_date || '—'}
                  {' · '}
                  workout {s.workout_id || '—'}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <Button
          variant="primary"
          size="compact"
          testId="batch-activate"
          disabled={batchBusy}
          onClick={handleBatchActivate}
        >
          {batchBusy ? '处理中…' : '批量采纳 high 置信'}
        </Button>
      </div>

      {/* A. 覆盖率看板 */}
      {coverageError && (
        <ErrorState message={coverageError} onRetry={loadCoverage} testId="coverage-error" />
      )}
      {coverageLoading && !coverage ? (
        <Skeleton className="h-28" />
      ) : coverage ? (
        <section data-testid="coverage-panel" className="space-y-3">
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
            <Card className="p-3">
              <p className="text-[10.5px] text-ink-400 dark:text-gray-400">总动作 / 已映射</p>
              <p className="mt-1 text-base font-black text-ink-900 dark:text-white">
                <span data-testid="coverage-total">{coverage.total}</span>
                {' / '}
                <span data-testid="coverage-with-candidate">{cov.with_candidate}</span>
                <span className="ml-1 text-xs font-medium text-ink-400 dark:text-gray-400">
                  ({cov.with_candidate_pct}%)
                </span>
              </p>
            </Card>
            <Card className="p-3">
              <p className="text-[10.5px] text-ink-400 dark:text-gray-400">可信候选</p>
              <p className="mt-1 text-base font-black text-ink-900 dark:text-white">
                <span data-testid="coverage-high">{cov.high}</span>
                <span className="ml-1 text-xs font-medium text-ink-400 dark:text-gray-400">
                  ({cov.high_pct}%)
                </span>
              </p>
            </Card>
            <Card className="p-3">
              <p className="text-[10.5px] text-ink-400 dark:text-gray-400">力量类覆盖</p>
              <p className="mt-1 text-base font-black text-ink-900 dark:text-white">
                <span data-testid="coverage-strength">
                  {cov.strength_with_candidate}/{cov.strength_total}
                </span>
                <span className="ml-1 text-xs font-medium text-ink-400 dark:text-gray-400">
                  ({cov.strength_with_candidate_pct}%)
                </span>
              </p>
            </Card>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {['draft', 'active', 'not_applicable', 'missing'].map((key) => (
              <Badge key={key} variant={STATUS_BADGE[key] || 'gray'}>
                {key}: {byStatus[key] ?? 0}
              </Badge>
            ))}
          </div>
        </section>
      ) : null}

      {/* B. 筛选 + 列表 */}
      <div className="flex flex-wrap items-end gap-2">
        <label className="text-xs text-ink-500 dark:text-gray-400">
          状态
          <select
            data-testid="filter-status"
            value={status}
            onChange={(e) => {
              setStatus(e.target.value)
              setPage(1)
            }}
            className="mt-1 block h-10 min-w-36 rounded-xl border border-line bg-white px-3 text-sm text-ink-900 focus:outline-none focus:ring-2 focus:ring-brand-200 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-100"
          >
            {STATUS_OPTIONS.map((o) => (
              <option key={o.value || 'all'} value={o.value}>{o.label}</option>
            ))}
          </select>
        </label>
        <label className="text-xs text-ink-500 dark:text-gray-400">
          置信度
          <select
            data-testid="filter-confidence"
            value={confidence}
            onChange={(e) => {
              setConfidence(e.target.value)
              setPage(1)
            }}
            className="mt-1 block h-10 min-w-36 rounded-xl border border-line bg-white px-3 text-sm text-ink-900 focus:outline-none focus:ring-2 focus:ring-brand-200 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-100"
          >
            {CONFIDENCE_OPTIONS.map((o) => (
              <option key={o.value || 'all'} value={o.value}>{o.label}</option>
            ))}
          </select>
        </label>
        <label className="min-w-[12rem] flex-1 text-xs text-ink-500 dark:text-gray-400">
          关键词
          <input
            data-testid="filter-keyword"
            type="search"
            value={keywordInput}
            onChange={(e) => setKeywordInput(e.target.value)}
            placeholder="训记名 / Garmin 英文名"
            className="mt-1 block h-10 w-full rounded-xl border border-line bg-white px-3 text-sm text-ink-900 focus:outline-none focus:ring-2 focus:ring-brand-200 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-100"
          />
        </label>
      </div>

      {listError && (
        <ErrorState message={listError} onRetry={loadList} testId="list-error" />
      )}

      <div data-testid="mapping-list">
        {listLoading ? (
          <div className="space-y-2">
            <Skeleton className="h-16" />
            <Skeleton className="h-16" />
            <Skeleton className="h-16" />
          </div>
        ) : !listError && items.length === 0 ? (
          <EmptyState title="没有匹配的映射" description="试试调整筛选条件或关键词" />
        ) : items.length > 0 ? (
          <ul className="space-y-2.5">
            {items.map((row) => {
              const busy = Boolean(rowBusy[row.id])
              const showActivate = row.status === 'draft' && Boolean(row.garmin_category)
              const showDisable = row.status === 'active'
              return (
                <li
                  key={row.id}
                  data-testid={`mapping-row-${row.id}`}
                  className="rounded-[18px] border border-line bg-white px-4 py-3.5 shadow-card dark:border-gray-800 dark:bg-gray-900"
                >
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0 flex-1 space-y-1">
                      <p className="font-semibold text-ink-900 dark:text-gray-100">{row.xunji_name}</p>
                      <p className="text-xs text-ink-500 dark:text-gray-400">
                        {(row.garmin_category || '—') + ' / ' + (row.garmin_exercise_name || '—')}
                      </p>
                      {row.garmin_display_name && (
                        <p className="text-xs text-ink-600 dark:text-gray-300">{row.garmin_display_name}</p>
                      )}
                      <div className="flex flex-wrap items-center gap-1.5 pt-1">
                        <Badge variant={STATUS_BADGE[row.status] || 'gray'}>{row.status}</Badge>
                        <Badge variant={CONFIDENCE_BADGE[row.confidence] || 'gray'}>
                          {row.confidence || 'none'}
                        </Badge>
                        <span className="text-[11px] text-ink-400 dark:text-gray-400">
                          {weightLabel(row.weight_strategy)}
                        </span>
                        {row.candidate_count > 0 && (
                          <span className="text-[11px] text-ink-400 dark:text-gray-400">
                            {row.candidate_count} 个候选
                          </span>
                        )}
                      </div>
                    </div>
                    <div className="flex flex-wrap gap-1.5">
                      <Button
                        variant="secondary"
                        size="compact"
                        testId={`mapping-edit-${row.id}`}
                        disabled={busy}
                        onClick={() => openEdit(row)}
                      >
                        编辑
                      </Button>
                      {showActivate && (
                        <Button
                          variant="primary"
                          size="compact"
                          testId={`mapping-activate-${row.id}`}
                          disabled={busy}
                          onClick={() => handleActivate(row)}
                        >
                          采纳
                        </Button>
                      )}
                      {showDisable && (
                        <Button
                          variant="danger"
                          size="compact"
                          testId={`mapping-disable-${row.id}`}
                          disabled={busy}
                          onClick={() => handleDisable(row)}
                        >
                          停用
                        </Button>
                      )}
                    </div>
                  </div>
                </li>
              )
            })}
          </ul>
        ) : null}
      </div>

      {!listLoading && !listError && pages > 0 && (
        <div className="flex items-center justify-between gap-2">
          <Button
            variant="secondary"
            size="compact"
            testId="page-prev"
            disabled={page <= 1 || listLoading}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
          >
            上一页
          </Button>
          <span className="text-sm text-ink-500 dark:text-gray-400" data-testid="page-indicator">
            第 {page} / {pages} 页
            {total > 0 && <span className="ml-1 text-xs">（共 {total}）</span>}
          </span>
          <Button
            variant="secondary"
            size="compact"
            testId="page-next"
            disabled={page >= pages || listLoading}
            onClick={() => setPage((p) => p + 1)}
          >
            下一页
          </Button>
        </div>
      )}

      {/* C. 编辑浮层 */}
      {editingId != null && editForm && (
        <div
          className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 p-3 sm:items-center"
          onClick={closeEdit}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-label="编辑映射"
            data-testid="edit-panel"
            className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-2xl border border-line bg-white p-4 shadow-lift dark:border-gray-700 dark:bg-gray-900"
            onClick={(e) => e.stopPropagation()}
          >
            <h2 className="text-base font-bold text-ink-900 dark:text-white">编辑映射</h2>
            <p className="mt-1 text-sm text-ink-500 dark:text-gray-400">
              训记名：<span className="font-medium text-ink-800 dark:text-gray-200">{editForm.xunji_name}</span>
            </p>

            <label className="mt-4 block text-xs text-ink-500 dark:text-gray-400">
              Garmin category
              <select
                data-testid="edit-category"
                value={editForm.garmin_category}
                onChange={(e) => setEditForm((prev) => ({ ...prev, garmin_category: e.target.value }))}
                className="mt-1 block h-11 w-full rounded-xl border border-line bg-canvas/50 px-3 text-sm text-ink-900 focus:outline-none focus:ring-2 focus:ring-brand-200 dark:border-gray-700 dark:bg-gray-950 dark:text-gray-100"
              >
                <option value="">（未选）</option>
                {categories.map((c) => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
            </label>

            <label className="mt-3 block text-xs text-ink-500 dark:text-gray-400">
              Garmin 动作搜索
              <input
                data-testid="edit-exercise-search"
                type="search"
                value={exerciseQuery}
                onChange={(e) => setExerciseQuery(e.target.value)}
                placeholder="搜索英文名或枚举名"
                className="mt-1 block h-11 w-full rounded-xl border border-line bg-canvas/50 px-3 text-sm text-ink-900 focus:outline-none focus:ring-2 focus:ring-brand-200 dark:border-gray-700 dark:bg-gray-950 dark:text-gray-100"
              />
            </label>
            {(exerciseResults.length > 0 || exerciseSearching) && (
              <ul className="mt-2 max-h-40 overflow-y-auto rounded-xl border border-line dark:border-gray-700">
                {exerciseSearching && (
                  <li className="px-3 py-2 text-xs text-ink-400">搜索中…</li>
                )}
                {exerciseResults.map((row, index) => (
                  <li key={`${row.category}-${row.exercise}-${index}`}>
                    <button
                      type="button"
                      data-testid={`edit-exercise-result-${index}`}
                      className="block w-full px-3 py-2 text-left text-sm text-ink-800 hover:bg-canvas dark:text-gray-200 dark:hover:bg-gray-800"
                      onClick={() => pickExercise(row)}
                    >
                      <span className="font-medium">{row.name || row.exercise}</span>
                      <span className="ml-2 text-xs text-ink-400">{row.category}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
            <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-ink-500 dark:text-gray-400">
              <span>
                当前：{editForm.garmin_exercise_name || '（空 = 仅显示 category）'}
                {editForm.garmin_display_name ? ` · ${editForm.garmin_display_name}` : ''}
              </span>
              {(editForm.garmin_exercise_name || editForm.garmin_display_name) && (
                <Button variant="ghost" size="compact" onClick={clearExercise}>
                  清空动作
                </Button>
              )}
            </div>

            <label className="mt-3 block text-xs text-ink-500 dark:text-gray-400">
              重量语义
              <select
                data-testid="edit-weight-strategy"
                value={editForm.weight_strategy}
                onChange={(e) => setEditForm((prev) => ({ ...prev, weight_strategy: e.target.value }))}
                className="mt-1 block h-11 w-full rounded-xl border border-line bg-canvas/50 px-3 text-sm text-ink-900 focus:outline-none focus:ring-2 focus:ring-brand-200 dark:border-gray-700 dark:bg-gray-950 dark:text-gray-100"
              >
                {WEIGHT_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
            </label>
            {editForm.weight_strategy === 'assisted' && (
              <p className="mt-1 text-[11px] leading-4 text-ink-400 dark:text-gray-500">
                辅助重量：本期不做换算，请按 Garmin 实际录入理解「辅助」语义。
              </p>
            )}

            <label className="mt-3 block text-xs text-ink-500 dark:text-gray-400">
              修改原因（可选）
              <textarea
                data-testid="edit-reason"
                value={editForm.reason}
                onChange={(e) => setEditForm((prev) => ({ ...prev, reason: e.target.value }))}
                rows={2}
                className="mt-1 block w-full rounded-xl border border-line bg-canvas/50 px-3 py-2 text-sm text-ink-900 focus:outline-none focus:ring-2 focus:ring-brand-200 dark:border-gray-700 dark:bg-gray-950 dark:text-gray-100"
              />
            </label>

            {editError && (
              <p data-testid="edit-error" className="mt-3 text-sm text-red-600 dark:text-red-400">
                {editError}
              </p>
            )}

            <div className="mt-4 flex justify-end gap-2">
              <Button
                variant="secondary"
                testId="edit-cancel"
                disabled={editSaving}
                onClick={closeEdit}
              >
                取消
              </Button>
              <Button
                variant="primary"
                testId="edit-save"
                disabled={editSaving}
                onClick={handleSaveEdit}
              >
                {editSaving ? '保存中…' : '保存'}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
