/**
 * 分段/胶囊切换组（用于 TrendsPage 周期切换、AIReportsPage/ReviewsPage 类型切换的后续迁移）。
 */
export default function PillGroup({ options = [], value, onChange, testId }) {
  return (
    <div data-testid={testId} className="flex flex-wrap gap-1" role="tablist">
      {options.map((option) => {
        const active = option.value === value
        const classes = [
          'rounded-md px-3 text-sm font-medium min-h-[44px]',
          active
            ? 'bg-indigo-600 text-white'
            : 'text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700 active:bg-gray-300',
        ].join(' ')
        return (
          <button
            key={String(option.value)}
            type="button"
            role="tab"
            aria-selected={active}
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
