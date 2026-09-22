/** 全站唯一卡片规格（UIX-11：20px 圆角 + 软阴影层级） */
const BASE = [
  'rounded-[20px] border border-line dark:border-gray-700',
  'bg-white dark:bg-gray-900 p-4 shadow-card transition-shadow duration-200 hover:shadow-lift',
].join(' ')

export default function Card({ children, className = '', testId }) {
  const classes = [BASE, className].filter(Boolean).join(' ')
  return (
    <div data-testid={testId} className={classes}>
      {children}
    </div>
  )
}
