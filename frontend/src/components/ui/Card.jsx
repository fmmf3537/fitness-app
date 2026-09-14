/** 全站唯一卡片规格，淘汰原有 4 种变体 */
const BASE = 'rounded-xl border border-gray-200 bg-white p-4 shadow-sm'

export default function Card({ children, className = '', testId }) {
  const classes = [BASE, className].filter(Boolean).join(' ')
  return (
    <div data-testid={testId} className={classes}>
      {children}
    </div>
  )
}
