import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, ApiError } from '../api/client'
import AiReviewPanel from '../components/AiReviewPanel'
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

const RELATION_OPTIONS = [
  { value: '', label: '全部' },
  { value: 'EXACT', label: '精确' },
  { value: 'SIMILAR', label: '近似' },
  { value: 'CATEGORY', label: '大类' },
  { value: 'UNMAPPED', label: '无对应' },
  { value: '__unset__', label: '未回填' },
]

const RELATION_BADGE = {
  EXACT: { label: '精确', className: 'bg-emerald-100 text-emerald-700' },
  SIMILAR: { label: '近似（有损）', className: 'bg-amber-100 text-amber-800' },
  CATEGORY: { label: '大类（有损）', className: 'bg-orange-100 text-orange-800' },
  UNMAPPED: { label: '无对应', className: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400' },
}

const SKIPPED_REASON_LABELS = {
  relation_not_exact: '关系非精确',
  relation_missing: '未回填关系',
  target_unverified: '目标未验证',
  equipment_mismatch: '器械不符',
  catalog_missing: '目录无此组合',
}

function RelationBadge({ relation }) {
  if (relation == null || relation === '') {
    return (
      <span
        data-testid="relation-badge"
        title="relation 尚未回填，可调用 backfill-relations"
        className="inline-flex items-center rounded-full bg-gray-50 px-2.5 py-1 text-xs font-medium text-gray-400 dark:bg-gray-900 dark:text-gray-500"
      >
        未回填
      </span>
    )
  }
  const meta = RELATION_BADGE[relation] || {
    label: relation,
    className: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400',
  }
  return (
    <span
      data-testid="relation-badge"
      className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium ${meta.className}`}
    >
      {meta.label}
    </span>
  )
}

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
  const [relation, setRelation] = useState('')
  const [keywordInput, setKeywordInput] = useState('')
  const [keyword, setKeyword] = useState('')

  const [staleSyncs, setStaleSyncs] = useState([])
  const [staleOpen, setStaleOpen] = useState(false)

  const [rowBusy, setRowBusy] = useState({})
  const [reviewBusy, setReviewBusy] = useState({})
  const [reviewsByRow, setReviewsByRow] = useState({})
  const [batchBusy, setBatchBusy] = useState(false)
  const [batchResult, setBatchResult] = useState(null)

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
      setBatchResult(result)
      toast(`已采纳 ${result.activated ?? 0} 条`)
      await Promise.all([loadCoverage(), loadList()])
    } catch (err) {
      toast(errorMessage(err), 'error')
    } finally {
      setBatchBusy(false)
    }
  }

  // 后端 list_mappings 不支持 relation 查询参数 → 仅过滤当前页
  const filteredItems = useMemo(() => {
    if (!relation) return items
    if (relation === '__unset__') {
      return items.filter((row) => row.relation == null || row.relation === '')
    }
    return items.filter((row) => row.relation === relation)
  }, [items, relation])

  const openEdit = async (row, preset) => {
    setEditError('')
    setExerciseQuery('')
    setExerciseResults([])
    setEditingId(row.id)
    setEditForm({
      xunji_name: row.xunji_name || '',
      garmin_category: preset?.category || row.garmin_category || '',
      garmin_exercise_name: preset?.exercise_name || row.garmin_exercise_name || '',
      garmin_display_name: row.garmin_display_name || '',
      weight_strategy: row.weight_strategy || 'total',
      reason: '',
    })
    try {
      const detail = await api(`/api/exercise-mappings/${row.id}`)
      setEditForm((prev) => ({
        ...prev,
        xunji_name: detail.xunji_name || prev.xunji_name,
        garmin_category: preset?.category || detail.garmin_category || '',
        garmin_exercise_name: preset?.exercise_name || detail.garmin_exercise_name || '',
        garmin_display_name: detail.garmin_display_name || '',
        weight_strategy: detail.weight_strategy || 'total',
      }))
    } catch {
      // 列表行数据已够用，详情失败不阻断编辑
    }
  }

  const handleAiReview = async (row) => {
    const id = row.id
    setReviewBusy((prev) => ({ ...prev, [id]: true }))
    try {
      // 必须带上该行的 status：后端默认只审 active 行，draft 行不传会被静默过滤成 0 条
      const query = new URLSearchParams({ xunji_name: row.xunji_name })
      if (row.status) query.set('status', row.status)
      const started = await api(
        `/api/exercise-mappings/review?${query.toString()}`,
        { method: 'POST' },
      )
      // requested === 0 说明后端没选中任何目标（根本没调 LLM），要说清是"没找到"而不是"没返回"
      if (!started?.requested) {
        toast(`未找到可审核的映射：${row.xunji_name}（状态 ${row.status || '未知'}）`, 'error')
        return
      }
      const batchId = started?.batch_id
      if (!batchId) {
        toast('审核未产生结果', 'error')
        return
      }
      const payload = await api(`/api/exercise-mappings/reviews?batch_id=${batchId}`)
      const item = (payload?.items || []).find((it) => it.xunji_name === row.xunji_name)
      if (!item) {
        toast('审核已执行，但未解析出该动作的结论；可稍后重试', 'error')
        return
      }
      setReviewsByRow((prev) => ({ ...prev, [id]: item }))
      if (item.verdict === 'current_ok') {
        toast('AI 认为当前映射合理')
      }
    } catch (err) {
      toast(errorMessage(err), 'error')
    } finally {
      setReviewBusy((prev) => ({ ...prev, [id]: false }))
    }
  }

  const handleApplyReview = (row, suggestion) => {
    openEdit(row, suggestion)
    toast('已填入 AI 建议，请确认后保存')
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

      {batchResult && (
        <div
          data-testid="batch-activate-result"
          className="rounded-2xl border border-line bg-white px-4 py-3 text-sm text-ink-700 shadow-card dark:border-gray-800 dark:bg-gray-900 dark:text-gray-200"
        >
          <p>
            已采纳 <span className="font-semibold">{batchResult.activated ?? 0}</span> 条
            {batchResult.skipped != null && (
              <>
                ，跳过 <span className="font-semibold">{batchResult.skipped}</span> 条
              </>
            )}
          </p>
          {batchResult.skipped_reasons && Object.keys(batchResult.skipped_reasons).length > 0 && (
            <ul data-testid="batch-skipped-reasons" className="mt-2 flex flex-wrap gap-1.5 text-xs">
              {Object.entries(batchResult.skipped_reasons).map(([code, count]) => (
                <li
                  key={code}
                  className="rounded-full bg-amber-50 px-2.5 py-1 text-amber-900 dark:bg-amber-950/40 dark:text-amber-100"
                >
                  {SKIPPED_REASON_LABELS[code] || code}: {count}
                </li>
              ))}
            </ul>
          )}
          {batchResult.relation_breakdown && Object.keys(batchResult.relation_breakdown).length > 0 && (
            <p data-testid="batch-relation-breakdown" className="mt-2 text-xs text-ink-500 dark:text-gray-400">
              关系分布：
              {Object.entries(batchResult.relation_breakdown)
                .map(([key, count]) => `${RELATION_BADGE[key]?.label || key} ${count}`)
                .join(' · ')}
            </p>
          )}
        </div>
      )}

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
        <label className="text-xs text-ink-500 dark:text-gray-400">
          关系
          <select
            data-testid="filter-relation"
            value={relation}
            onChange={(e) => setRelation(e.target.value)}
            className="mt-1 block h-10 min-w-36 rounded-xl border border-line bg-white px-3 text-sm text-ink-900 focus:outline-none focus:ring-2 focus:ring-brand-200 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-100"
          >
            {RELATION_OPTIONS.map((o) => (
              <option key={o.value || 'all'} value={o.value}>{o.label}</option>
            ))}
          </select>
        </label>
        <span
          data-testid="relation-filter-scope-hint"
          className="pb-2.5 text-[11px] text-ink-400 dark:text-gray-500"
        >
          仅筛选当前页
        </span>
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
        ) : !listError && filteredItems.length === 0 ? (
          <EmptyState title="没有匹配的映射" description="试试调整筛选条件或关键词" />
        ) : filteredItems.length > 0 ? (
          <ul className="space-y-2.5">
            {filteredItems.map((row) => {
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
                        <RelationBadge relation={row.relation} />
                        {row.decision_source === 'human_policy' && (
                          <span
                            data-testid="decision-source-badge"
                            title="继承旧规则的批量使用政策，非逐条人工语义确认（ADR §10.1）"
                            className="inline-flex items-center rounded-full bg-indigo-50 px-2.5 py-1 text-xs font-medium text-indigo-700 dark:bg-indigo-950/40 dark:text-indigo-200"
                          >
                            沿用旧政策
                          </span>
                        )}
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
                        testId={`mapping-ai-review-${row.id}`}
                        disabled={busy || reviewBusy[row.id]}
                        onClick={() => handleAiReview(row)}
                      >
                        {reviewBusy[row.id] ? '审核中…' : 'AI 审核'}
                      </Button>
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
                  {reviewsByRow[row.id] && (
                    <div className="mt-3 w-full">
                      <AiReviewPanel
                        review={reviewsByRow[row.id]}
                        busy={busy}
                        onApply={(sug) => handleApplyReview(row, sug)}
                      />
                    </div>
                  )}
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
