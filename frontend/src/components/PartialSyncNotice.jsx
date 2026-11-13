export default function PartialSyncNotice({ syncResult, className = '' }) {
  if (!syncResult || !syncResult.skipped) return null

  const written = syncResult.written ?? 0
  const skipped = syncResult.skipped ?? 0
  const excluded = syncResult.excluded ?? 0
  const movements = Array.isArray(syncResult.skipped_movements)
    ? syncResult.skipped_movements
    : []
  const visible = movements.slice(0, 8)
  const remaining = movements.length - visible.length

  return (
    <div
      data-testid="partial-sync-notice"
      className={`rounded-2xl border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-100 ${className}`.trim()}
    >
      <p className="font-medium">
        部分同步：已写入 {written} 个动作，跳过 {skipped} 个
      </p>
      {visible.length > 0 && (
        <ul className="mt-2 space-y-1 text-xs">
          {visible.map((m, index) => (
            <li key={`${m?.name ?? 'm'}-${index}`}>
              <span className="font-medium">{m?.name || '—'}</span>
              {m?.reason ? ` · ${m.reason}` : ''}
            </li>
          ))}
        </ul>
      )}
      {remaining > 0 && (
        <p className="mt-1 text-xs">还有 {remaining} 个</p>
      )}
      <p className="mt-2 text-[11px] leading-4 text-amber-800/80 dark:text-amber-200/80">
        被跳过的动作不会出现在 Garmin 训练里；修复映射后重新同步会补回
      </p>
      {excluded > 0 && (
        <p className="mt-2 text-xs text-gray-600 dark:text-gray-400">
          另有 {excluded} 个动作按产品定义不写入（拉伸/有氧）
        </p>
      )}
    </div>
  )
}
