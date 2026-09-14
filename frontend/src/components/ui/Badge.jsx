const VARIANT_CLASS = {
  indigo: 'bg-indigo-100 text-indigo-700',
  green: 'bg-green-100 text-green-700',
  amber: 'bg-amber-100 text-amber-800',
  gray: 'bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400',
  red: 'bg-red-100 text-red-700',
}

const BASE = 'inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium'

export default function Badge({ variant = 'gray', children, testId }) {
  const variantClass = VARIANT_CLASS[variant] ?? VARIANT_CLASS.gray
  return (
    <span data-testid={testId} className={`${BASE} ${variantClass}`}>
      {children}
    </span>
  )
}
