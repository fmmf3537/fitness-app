/**
 * 共享按钮原语。
 * min-h-[44px] 是移动端触控热区红线（审计发现全站按钮 28–36px）。
 */
const VARIANT_CLASS = {
  primary: 'bg-gradient-brand text-white shadow-glow hover:brightness-105 active:brightness-95',
  secondary: 'border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800 active:bg-gray-100',
  danger: 'border border-red-300 bg-white dark:bg-gray-900 text-red-600 hover:bg-red-50 dark:hover:bg-red-950/50 active:bg-red-100',
  dangerSolid: 'bg-red-600 text-white hover:bg-red-700 active:bg-red-800',
  ghost: 'px-3 text-indigo-600 hover:bg-indigo-50 dark:hover:bg-indigo-950/50 active:bg-indigo-100',
}

const BASE =
  'inline-flex items-center justify-center gap-1.5 rounded-lg text-sm font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50'

const SIZE_CLASS = {
  compact: 'min-h-9 px-3 text-xs',
  default: 'min-h-[44px] px-4',
  large: 'min-h-12 px-5 text-base',
  icon: 'h-11 w-11 p-0',
}

export default function Button({
  variant = 'primary',
  size = 'default',
  fullWidth = false,
  type = 'button',
  disabled = false,
  onClick,
  children,
  testId,
  className = '',
  ariaLabel,
  dataDialogClose = false,
  ref,
}) {
  const variantClass = VARIANT_CLASS[variant] ?? VARIANT_CLASS.primary
  const classes = [
    BASE,
    SIZE_CLASS[size] ?? SIZE_CLASS.default,
    variantClass,
    fullWidth ? 'w-full' : '',
    className,
  ]
    .filter(Boolean)
    .join(' ')

  return (
    <button
      ref={ref}
      type={type}
      disabled={disabled}
      onClick={onClick}
      data-testid={testId}
      aria-label={ariaLabel}
      data-dialog-close={dataDialogClose ? '' : undefined}
      className={classes}
    >
      {children}
    </button>
  )
}
