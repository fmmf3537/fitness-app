/** 全站唯一卡片规格，淘汰原有 4 种变体 */
const BASE = [
  'rounded-2xl border border-gray-200 dark:border-gray-700',
  'bg-white dark:bg-gray-900 p-4 shadow-sm transition-shadow duration-200',
].join(' ')

export default function Card({ children, className = '', testId }) {
  const classes = [BASE, className].filter(Boolean).join(' ')
  return (
    <div data-testid={testId} className={classes}>
      {children}
    </div>
  )
}
