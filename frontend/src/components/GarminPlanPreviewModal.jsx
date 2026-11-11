import { useEffect, useId, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { api, ApiError } from '../api/client'
import useModalAccessibility from '../hooks/useModalAccessibility'
import Button from './ui/Button'
import ConfirmDialog from './ui/ConfirmDialog'
import Icon from './ui/Icon'
import Skeleton from './ui/Skeleton'

const POLL_INTERVAL_MS = 1500

const STATUS_META = {
  not_synced: { label: '未同步', icon: 'sync', className: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-300' },
  pending: { label: '待同步', icon: 'clock', className: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-300' },
  syncing: { label: '同步中', icon: 'sync', className: 'bg-blue-50 text-blue-700 dark:bg-blue-950/60 dark:text-blue-300' },
  synced: { label: '已同步', icon: 'check', className: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/60 dark:text-emerald-300' },
  update_available: { label: '有更新', icon: 'alert', className: 'bg-amber-50 text-amber-700 dark:bg-amber-950/60 dark:text-amber-300' },
  reschedule_pending: { label: '顺延待确认', icon: 'calendar', className: 'bg-violet-50 text-violet-700 dark:bg-violet-950/60 dark:text-violet-300' },
  failed: { label: '同步失败', icon: 'alert', className: 'bg-red-50 text-red-700 dark:bg-red-950/60 dark:text-red-300' },
  conflict: { label: '待处理冲突', icon: 'alert', className: 'bg-red-50 text-red-700 dark:bg-red-950/60 dark:text-red-300' },
  source_removed: { label: '源计划已移除', icon: 'alert', className: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-300' },
}

export function GarminSyncBadge({ sync }) {
  const meta = STATUS_META[sync?.status] || STATUS_META.not_synced
  return (
    <span
      data-testid="garmin-sync-badge"
      className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-semibold ${meta.className}`}
    >
      <Icon name={meta.icon} size={13} />
      Garmin · {meta.label}
    </span>
  )
}

function formatRest(seconds) {
  if (seconds == null) return '未设休息'
  if (seconds === 0) return '无休息'
  return `休息 ${seconds} 秒`
}

function errorMessage(error) {
  if (error instanceof ApiError) {
    return error.detail?.message || error.message
  }
  return error?.message || '未知错误'
}

function PreviewContent({ preview, isReschedule = false }) {
  const { stats = {}, movements = [], sync } = preview
  return (
    <div className="space-y-4">
      {isReschedule ? (
        <section
          data-testid="garmin-reschedule-comparison"
          className="rounded-2xl border border-violet-200 bg-violet-50 p-4 text-violet-900 dark:border-violet-900 dark:bg-violet-950/40 dark:text-violet-200"
        >
          <p className="text-xs font-semibold">训记已将这次训练顺延</p>
          <div className="mt-3 grid grid-cols-[1fr_auto_1fr] items-center gap-2 text-center">
            <div className="rounded-xl bg-white/75 px-2 py-3 dark:bg-gray-900/60">
              <p className="text-[11px] text-ink-500 dark:text-gray-400">原 Garmin 日期</p>
              <p className="mt-1 text-sm font-black" data-testid="garmin-reschedule-from">{preview.from_date}</p>
            </div>
            <Icon name="arrow" size={18} className="shrink-0" />
            <div className="rounded-xl bg-white/75 px-2 py-3 dark:bg-gray-900/60">
              <p className="text-[11px] text-ink-500 dark:text-gray-400">调整后日期</p>
              <p className="mt-1 text-sm font-black" data-testid="garmin-reschedule-to">{preview.to_date}</p>
            </div>
          </div>
          <p className="mt-3 text-xs leading-5">
            {sync?.status === 'synced'
              ? '改期已完成，训练内容、日程日期和关联均已回读核验。'
              : '确认后更新原 Workout 并调整原日程，保留两个远端 ID；不会创建或删除训练、日程。'}
          </p>
        </section>
      ) : (
        <div className="rounded-xl bg-blue-50 p-3 text-xs leading-5 text-blue-800 dark:bg-blue-950/50 dark:text-blue-200">
          {sync?.status === 'synced'
            ? '此版本已同步到 Garmin，并完成训练与日程回读验证。'
            : '当前为完整预览，不会自动写入 Garmin；只有点击下方确认按钮才会创建或覆盖此应用管理的训练。'}
        </div>
      )}

      {sync?.status === 'update_available' && (
        <p role="status" className="rounded-xl bg-amber-50 p-3 text-xs leading-5 text-amber-800 dark:bg-amber-950/50 dark:text-amber-200">
          训记计划已变化。确认后将覆盖关联的 Garmin 训练，但保留原 Workout ID 和日程 ID。
        </p>
      )}
      {sync?.last_error && (
        <p role="alert" className="rounded-xl bg-red-50 p-3 text-xs leading-5 text-red-700 dark:bg-red-950/50 dark:text-red-300">
          {sync.last_error}
        </p>
      )}

      <dl className="grid grid-cols-3 gap-2" data-testid="garmin-preview-stats">
        <div className="rounded-xl bg-line/60 p-3 text-center dark:bg-gray-800">
          <dt className="text-[11px] text-ink-500 dark:text-gray-400">动作</dt>
          <dd className="mt-1 text-lg font-black text-ink-900 dark:text-white">{stats.movements ?? 0}</dd>
        </div>
        <div className="rounded-xl bg-line/60 p-3 text-center dark:bg-gray-800">
          <dt className="text-[11px] text-ink-500 dark:text-gray-400">总组数</dt>
          <dd className="mt-1 text-lg font-black text-ink-900 dark:text-white">{stats.sets ?? 0}</dd>
        </div>
        <div className="rounded-xl bg-line/60 p-3 text-center dark:bg-gray-800">
          <dt className="text-[11px] text-ink-500 dark:text-gray-400">热身 / 正式</dt>
          <dd className="mt-1 text-lg font-black text-ink-900 dark:text-white">{stats.warmup_sets ?? 0} / {stats.working_sets ?? 0}</dd>
        </div>
      </dl>

      <div className="space-y-3">
        {movements.map((movement, movementIndex) => (
          <section
            key={`${movement.name}-${movementIndex}`}
            data-testid={`garmin-preview-movement-${movementIndex}`}
            className="rounded-2xl border border-line p-3 dark:border-gray-800"
          >
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div>
                <h3 className="text-sm font-bold text-ink-900 dark:text-gray-100">{movement.name}</h3>
                <p className="mt-0.5 text-xs text-ink-500 dark:text-gray-400">{movement.garmin_display_name}</p>
              </div>
              <span className="text-[10px] text-ink-400 dark:text-gray-500">
                {['p0_verified', 'p2_verified', 'p3_verified'].includes(movement.support_level) ? '已端到端验证' : '目录映射已确认 · 待远端验收'}
              </span>
            </div>
            <ul className="mt-3 space-y-2">
              {(movement.groups || []).map((group, groupIndex) => (
                <li
                  key={`${group.source_sets}-${groupIndex}`}
                  className="rounded-xl bg-line/50 px-3 py-2 text-xs leading-5 text-ink-700 dark:bg-gray-800/70 dark:text-gray-300"
                >
                  <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                    <span className="font-semibold text-ink-900 dark:text-gray-100">
                      源组 {group.source_sets} · {group.count} 组 × {group.reps} 次
                    </span>
                    {group.set_type === 'warmup' && (
                      <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-medium text-amber-800 dark:bg-amber-950 dark:text-amber-300">热身</span>
                    )}
                  </div>
                  <p className="mt-0.5 text-ink-500 dark:text-gray-400">
                    {group.weight_kg == null ? '自重 / 未设重量' : `${group.weight_kg} kg`}
                    <span className="mx-1.5">·</span>
                    {formatRest(group.rest_seconds)}
                  </p>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>

      <div className="text-[11px] leading-5 text-ink-400 dark:text-gray-500">
        <p>休息总计 {stats.rest_seconds ?? 0} 秒 · RepeatGroup {stats.repeat_groups ?? 0} 个</p>
        <p className="mt-1 break-all">来源哈希：{preview.source_hash}</p>
        {(sync?.workout_id || sync?.workout_schedule_id) && (
          <p className="mt-1 break-all">
            已关联 Workout {sync.workout_id || '—'} / 日程 {sync.workout_schedule_id || '—'}
          </p>
        )}
      </div>
    </div>
  )
}

function confirmLabel(status, isReschedule) {
  if (isReschedule) return status === 'failed' ? '恢复顺延' : '确认顺延'
  if (status === 'update_available') return '确认覆盖更新'
  if (status === 'failed') return '恢复同步'
  return '确认同步'
}

export default function GarminPlanPreviewModal({ day, onClose, onSyncChange }) {
  const open = Boolean(day)
  const dayDate = day?.date
  const initialSync = day?.garmin_sync
  const isReschedule = Boolean(
    initialSync?.phase === 'reschedule' && initialSync?.reschedule_to_date,
  )
  const fromDate = isReschedule ? initialSync.reschedule_from_date : dayDate
  const targetDate = isReschedule ? initialSync.reschedule_to_date : dayDate
  const [preview, setPreview] = useState(null)
  const [error, setError] = useState(null)
  const [actionError, setActionError] = useState(null)
  const [loading, setLoading] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [retryToken, setRetryToken] = useState(0)
  const [pollRetryToken, setPollRetryToken] = useState(0)
  const dialogRef = useRef(null)
  const closeRef = useRef(null)
  const titleId = useId()
  useModalAccessibility({ open, containerRef: dialogRef, initialFocusRef: closeRef, onClose })

  useEffect(() => {
    if (!open) setConfirmOpen(false)
  }, [open])

  useEffect(() => {
    if (!dayDate || !fromDate || !targetDate) return undefined
    let active = true
    setLoading(true)
    setPreview(null)
    setError(null)
    setActionError(null)
    setSubmitting(false)
    const path = isReschedule
      ? `/api/plans/${fromDate}/garmin/reschedule?to_date=${encodeURIComponent(targetDate)}`
      : `/api/plans/${dayDate}/garmin/preview`
    api(path)
      .then((data) => {
        if (active) setPreview(data)
      })
      .catch((reason) => {
        if (active) setError(reason)
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [dayDate, fromDate, targetDate, isReschedule, retryToken])

  const sync = preview?.sync
  useEffect(() => {
    if (!open || !targetDate || sync?.status !== 'syncing' || actionError) return undefined
    let active = true
    const timer = setTimeout(async () => {
      try {
        const nextSync = await api(`/api/plans/${targetDate}/garmin/sync`)
        if (!active) return
        setPreview((current) => current ? { ...current, sync: nextSync } : current)
        if (nextSync.status !== 'syncing') onSyncChange?.(targetDate, nextSync)
      } catch (reason) {
        if (active) setActionError(reason)
      }
    }, POLL_INTERVAL_MS)
    return () => {
      active = false
      clearTimeout(timer)
    }
  }, [open, targetDate, sync, actionError, pollRetryToken, onSyncChange])

  if (!open) return null
  const issues = error instanceof ApiError && error.status === 422
    ? error.detail?.issues || []
    : []
  const status = sync?.status
  const canWrite = Boolean(
    preview?.remote_write_eligible
    && !['synced', 'syncing', 'conflict', 'source_removed'].includes(status),
  )

  const confirmDescription = isReschedule
    ? `将从 ${preview?.from_date} 顺延到 ${preview?.to_date}，保留原 Workout ${sync?.workout_id || '—'} 与日程 ${sync?.workout_schedule_id || '—'} 的关联。`
    : status === 'update_available'
      ? `将覆盖此应用管理的 Garmin 训练（保留原 Workout 与日程关联），日期 ${dayDate}。`
      : status === 'failed'
        ? `将从已保存的阶段恢复，系统会先对账，不会重复创建。日期 ${dayDate}。`
        : `将在 Garmin Connect 为 ${dayDate} 创建训练并安排日程。Garmin 不支持批量删除，误创建需在 App 中手动删除。`

  const requestConfirm = () => {
    if (!canWrite || submitting || confirmOpen) return
    setConfirmOpen(true)
  }

  const handleConfirm = async () => {
    if (!canWrite || submitting) return
    setSubmitting(true)
    setActionError(null)
    try {
      const path = isReschedule
        ? `/api/plans/${fromDate}/garmin/reschedule`
        : `/api/plans/${dayDate}/garmin/sync`
      const body = isReschedule
        ? { to_date: targetDate, source_hash: preview.source_hash }
        : { source_hash: preview.source_hash }
      const result = await api(path, {
        method: 'POST',
        body: JSON.stringify(body),
      })
      setPreview((current) => current ? { ...current, sync: result.sync } : current)
      onSyncChange?.(targetDate, result.sync)
    } catch (reason) {
      if (reason instanceof ApiError && ['PLAN_CHANGED', 'SYNC_ALREADY_RUNNING'].includes(reason.detail?.code)) {
        // 旧预览确认已作废；重新加载当前计划或接管现有任务的轮询。
        setRetryToken((value) => value + 1)
      } else {
        setActionError(reason)
      }
    } finally {
      setSubmitting(false)
    }
  }

  const handleDialogConfirm = () => {
    setConfirmOpen(false)
    void handleConfirm()
  }

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-4">
      <div
        data-testid="garmin-preview-backdrop"
        className="absolute inset-0 bg-black/55"
        onClick={onClose}
      />
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        data-testid="garmin-preview-modal"
        className="relative flex max-h-[92dvh] w-full max-w-2xl flex-col rounded-2xl bg-white shadow-2xl dark:bg-gray-900"
      >
        <header className="flex items-start justify-between gap-3 border-b border-line px-4 py-4 dark:border-gray-800 sm:px-5">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h2 id={titleId} className="text-lg font-black text-ink-900 dark:text-white">
                {isReschedule ? 'Garmin 顺延预览' : 'Garmin 同步预览'}
              </h2>
              <GarminSyncBadge sync={sync || day.garmin_sync} />
            </div>
            <p className="mt-1 text-xs text-ink-500 dark:text-gray-400">
              {day.date}{day.title ? ` · ${day.title}` : ''}
            </p>
          </div>
          <Button
            ref={closeRef}
            variant="ghost"
            size="icon"
            ariaLabel="关闭 Garmin 预览"
            testId="garmin-preview-close-icon"
            onClick={onClose}
            className="shrink-0 text-ink-500 dark:text-gray-300"
          >
            <span aria-hidden="true" className="text-2xl leading-none">×</span>
          </Button>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4 sm:px-5">
          {loading && (
            <div data-testid="garmin-preview-loading" className="space-y-3" aria-label="正在生成预览">
              <Skeleton className="h-16" />
              <Skeleton className="h-24" />
              <Skeleton className="h-40" />
            </div>
          )}
          {!loading && error && (
            <div role="alert" className="rounded-2xl border border-red-200 bg-red-50 p-4 dark:border-red-900 dark:bg-red-950/40">
              <h3 className="text-sm font-bold text-red-800 dark:text-red-200">
                {issues.length > 0 ? '暂不支持同步此计划' : '预览生成失败'}
              </h3>
              {issues.length > 0 ? (
                <ul data-testid="garmin-preview-issues" className="mt-3 space-y-2 text-xs leading-5 text-red-700 dark:text-red-300">
                  {issues.map((issue, index) => (
                    <li key={`${issue.movement || 'plan'}-${issue.code}-${index}`} className="rounded-lg bg-white/70 p-2 dark:bg-gray-900/50">
                      <span className="font-semibold">{issue.movement || '计划'}：</span>
                      {issue.message}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="mt-2 text-xs text-red-700 dark:text-red-300">{errorMessage(error)}</p>
              )}
              {issues.length === 0 && (
                <Button
                  variant="secondary"
                  size="compact"
                  className="mt-3"
                  testId="garmin-preview-retry"
                  onClick={() => setRetryToken((value) => value + 1)}
                >
                  重新加载
                </Button>
              )}
            </div>
          )}
          {!loading && !error && preview && (
            <PreviewContent preview={preview} isReschedule={isReschedule} />
          )}
          {!loading && !error && preview && !preview.remote_write_eligible && status !== 'synced' && (
            <p role="status" className="mt-4 rounded-xl bg-gray-100 p-3 text-xs leading-5 text-gray-600 dark:bg-gray-800 dark:text-gray-300">
              Garmin 写入当前未启用；预览和状态查询仍可使用。
            </p>
          )}
          {actionError && (
            <div role="alert" className="mt-4 rounded-xl bg-red-50 p-3 text-xs leading-5 text-red-700 dark:bg-red-950/50 dark:text-red-300">
              <p>{errorMessage(actionError)}</p>
              {status === 'syncing' && (
                <Button
                  variant="secondary"
                  size="compact"
                  className="mt-2"
                  testId="garmin-sync-poll-retry"
                  onClick={() => {
                    setActionError(null)
                    setPollRetryToken((value) => value + 1)
                  }}
                >
                  重新获取状态
                </Button>
              )}
            </div>
          )}
        </div>

        <footer className="border-t border-line px-4 py-3 dark:border-gray-800 sm:px-5">
          {canWrite && (
            <div className="mb-3 rounded-xl bg-amber-50 p-3 text-xs leading-5 text-amber-800 dark:bg-amber-950/50 dark:text-amber-200" data-testid="garmin-write-confirmation">
              {isReschedule
                ? status === 'failed'
                  ? '将从已保存的顺延阶段恢复，先回读原 Workout 和日程；不会重复更新已成功的步骤。'
                  : `确认后保留 Workout ${sync?.workout_id || '—'} 和日程 ${sync?.workout_schedule_id || '—'}，将训练从 ${preview.from_date} 调整到 ${preview.to_date}。`
                : status === 'update_available'
                  ? '确认后将覆盖此应用管理的 Garmin 训练，保留原训练与日程关联。'
                  : status === 'failed'
                    ? '将从已保存的阶段恢复；系统会先对账，不会盲目重复创建训练或日程。'
                    : '确认后将创建一个由本应用管理的 Garmin 训练，并安排到该计划日期。'}
            </div>
          )}
          <div className={canWrite ? 'grid grid-cols-2 gap-2' : ''}>
            <Button variant="secondary" fullWidth onClick={onClose} testId="garmin-preview-close">
              关闭
            </Button>
            {canWrite && (
              <Button
                variant="primary"
                fullWidth
                onClick={requestConfirm}
                disabled={submitting}
                testId={isReschedule ? 'garmin-confirm-reschedule' : 'garmin-confirm-sync'}
              >
                {submitting ? '提交中…' : confirmLabel(status, isReschedule)}
              </Button>
            )}
          </div>
        </footer>
      </div>
      <ConfirmDialog
        open={confirmOpen}
        title={isReschedule ? '确认顺延改期？' : '确认写入 Garmin？'}
        description={confirmDescription}
        confirmText={isReschedule ? '确认改期' : '确认写入'}
        cancelText="取消"
        danger
        onConfirm={handleDialogConfirm}
        onCancel={() => setConfirmOpen(false)}
      />
    </div>,
    document.body,
  )
}
