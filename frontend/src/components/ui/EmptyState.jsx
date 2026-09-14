export default function EmptyState({ icon, title, description, action, testId }) {
  return (
    <div
      data-testid={testId}
      className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-6 text-center shadow-sm"
    >
      {icon != null && (
        <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-indigo-50 dark:bg-indigo-950/50 text-indigo-500">
          {icon}
        </div>
      )}
      <p className="mt-3 text-sm font-medium text-gray-900 dark:text-gray-100">{title}</p>
      {description != null && description !== '' && (
        <p className="mt-1 text-xs text-gray-600 dark:text-gray-400">{description}</p>
      )}
      {action != null && (
        <div className="mt-4 flex justify-center">{action}</div>
      )}
    </div>
  )
}
