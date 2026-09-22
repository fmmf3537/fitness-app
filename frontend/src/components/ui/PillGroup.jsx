/**
 * 分段/胶囊切换组（用于 TrendsPage 周期切换、AIReportsPage/ReviewsPage 类型切换的后续迁移）。
 */
export default function PillGroup({ options = [], value, onChange, testId, ariaLabel = '筛选选项' }) {
  return (
    <div data-testid={testId} className="flex flex-wrap gap-1" role="group" aria-label={ariaLabel}>
      {options.map((option) => {
        const active = option.value === value
        const classes = [
          'rounded-full px-4 text-sm font-medium min-h-9 transition',
          active
            ? 'bg-gradient-brand text-white shadow-glow'
            : 'text-ink-500 hover:bg-line dark:text-gray-300 dark:hover:bg-gray-700 active:bg-gray-200',
        ].join(' ')
        return (
          <button
            key={String(option.value)}
            type="button"
            aria-pressed={active}
            className={classes}
            onClick={() => onChange?.(option.value)}
          >
            {option.label}
          </button>
        )
      })}
    </div>
  )
}
