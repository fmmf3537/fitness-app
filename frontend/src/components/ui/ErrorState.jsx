/**
 * 错误态必带恢复入口（审计发现原错误只是一行红字，用户无法恢复）。
 */
function AlertIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className="shrink-0"
    >
      <circle cx="12" cy="12" r="10" />
      <line x1="12" y1="8" x2="12" y2="12" />
      <line x1="12" y1="16" x2="12.01" y2="16" />
    </svg>
  )
}

export default function ErrorState({ message, onRetry, testId }) {
  return (
    <div
      role="alert"
      data-testid={testId}
      className="rounded-xl border border-red-200 bg-red-50 p-4"
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-sm text-red-700">
          <AlertIcon />
          <span>{message}</span>
        </div>
        {onRetry != null && (
          <button
            type="button"
            onClick={onRetry}
            className="min-h-[44px] rounded-lg px-3 text-sm font-medium text-red-700 hover:bg-red-100 active:bg-red-200"
          >
            重试
          </button>
        )}
      </div>
    </div>
  )
}
