import Button from './ui/Button'

const VERDICT_META = {
  current_ok: {
    label: '当前映射合理',
    className: 'bg-emerald-100 text-emerald-700',
    showSuggestion: false,
  },
  better_candidate: {
    label: '有更优候选',
    className: 'bg-sky-100 text-sky-800',
    showSuggestion: true,
  },
  suspected_error: {
    label: '疑似错误',
    className: 'bg-rose-100 text-rose-700',
    showSuggestion: true,
  },
  likely_unmapped: {
    label: '可能无对应',
    className: 'bg-amber-100 text-amber-800',
    showSuggestion: false,
  },
  needs_human: {
    label: '需要你判断',
    className: 'bg-gray-100 text-gray-700',
    showSuggestion: false,
  },
}

function suggestionPath(review) {
  const category = review?.suggested_category || ''
  const exercise = review?.suggested_exercise_name || ''
  if (!category && !exercise) return ''
  return `${category}/${exercise}`
}

export default function AiReviewPanel({ review, onApply, busy = false }) {
  if (!review) return null

  const verdict = review.verdict
  const meta = VERDICT_META[verdict] || {
    label: verdict || '未知',
    className: 'bg-gray-100 text-gray-700',
    showSuggestion: false,
  }
  const path = suggestionPath(review)
  const canApply = Boolean(review.suggested_exercise_name) && typeof onApply === 'function'
  const showSuggestionBlock = meta.showSuggestion && path

  return (
    <div
      data-testid="ai-review-panel"
      data-verdict={verdict}
      className="w-full rounded-xl border border-line bg-canvas/40 px-3 py-2.5 dark:border-gray-700 dark:bg-gray-950/40"
    >
      <div className="flex flex-wrap items-center gap-2">
        <span
          className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium ${meta.className}`}
        >
          {meta.label}
        </span>
        {showSuggestionBlock && (
          <span className="font-mono text-xs text-ink-700 dark:text-gray-300">
            {verdict === 'better_candidate' ? `当前 → ${path}` : `→ ${path}`}
          </span>
        )}
        {canApply && (
          <Button
            variant="secondary"
            size="compact"
            testId="ai-review-apply"
            disabled={busy}
            onClick={() =>
              onApply({
                category: review.suggested_category || '',
                exercise_name: review.suggested_exercise_name || '',
              })
            }
          >
            应用建议
          </Button>
        )}
      </div>
      {review.reason ? (
        <p className="mt-2 text-sm leading-5 text-ink-600 dark:text-gray-300">{review.reason}</p>
      ) : null}
    </div>
  )
}
