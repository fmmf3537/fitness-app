import ReviewContent from './ReviewContent'

/** 按 Markdown h2（## ）切分；切分发生在 ReviewContent 的 echarts 切块之前 */
function splitMarkdownSections(text) {
  const source = text || ''
  const starts = []
  const re = /^##\s+/gm
  let m
  while ((m = re.exec(source)) !== null) {
    starts.push(m.index)
  }
  if (starts.length === 0) return source ? [source] : []
  const sections = []
  for (let i = 0; i < starts.length; i++) {
    const from = i === 0 ? 0 : starts[i]
    const to = i + 1 < starts.length ? starts[i + 1] : source.length
    sections.push(source.slice(from, to))
  }
  return sections
}

/**
 * 复盘正文按 h2 分卡。≥2 个 h2 时每段一卡；不足则回退单卡，不丢内容。
 */
export default function ReviewSections({ text, testId }) {
  const sections = splitMarkdownSections(text)
  const multi = sections.length >= 2
  return (
    <div
      data-testid={testId || 'review-sections'}
      className={multi ? 'space-y-3' : undefined}
    >
      {multi ? (
        sections.map((section, i) => (
          <section
            key={i}
            data-testid="review-section-card"
            className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-5 shadow-sm"
          >
            <ReviewContent text={section} />
          </section>
        ))
      ) : (
        <section
          data-testid="review-section-card"
          className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-5 shadow-sm"
        >
          <ReviewContent text={text} />
        </section>
      )}
    </div>
  )
}
