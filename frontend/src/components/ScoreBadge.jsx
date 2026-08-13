/**
 * AI 评分徽章（V3-4）：≥90 绿 / 75-89 indigo / 60-74 黄 / <60 红。
 * score 为 null/undefined 时不渲染。
 */
export default function ScoreBadge({ score, testId }) {
  if (score == null) return null
  const colorCls =
    score >= 90
      ? 'bg-green-100 text-green-700'
      : score >= 75
        ? 'bg-indigo-100 text-indigo-700'
        : score >= 60
          ? 'bg-yellow-100 text-yellow-700'
          : 'bg-red-100 text-red-700'
  return (
    <span
      data-testid={testId}
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold ${colorCls}`}
    >
      {score} 分
    </span>
  )
}
