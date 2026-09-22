import Icon from './Icon'

/**
 * 彩色图标 chip（UIX-11）：统计卡 / 列表行左侧的语义色图标底。
 * variant: violet | blue | green | amber | red
 */
const VARIANT_CLASS = {
  violet: 'bg-brand-100 text-brand-600 dark:bg-brand-900/40 dark:text-brand-300',
  blue: 'bg-indigo-100 text-indigo-600 dark:bg-indigo-900/40 dark:text-indigo-300',
  green: 'bg-emerald-100 text-emerald-600 dark:bg-emerald-900/40 dark:text-emerald-300',
  amber: 'bg-amber-100 text-amber-600 dark:bg-amber-900/40 dark:text-amber-300',
  red: 'bg-red-100 text-red-600 dark:bg-red-900/40 dark:text-red-300',
}

export default function IconChip({ icon, variant = 'violet', size = 16, className = '' }) {
  return (
    <span
      aria-hidden="true"
      className={`inline-flex h-[30px] w-[30px] shrink-0 items-center justify-center rounded-[10px] ${VARIANT_CLASS[variant] ?? VARIANT_CLASS.violet} ${className}`}
    >
      <Icon name={icon} size={size} />
    </span>
  )
}
