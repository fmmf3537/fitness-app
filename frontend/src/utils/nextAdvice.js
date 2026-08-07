// V1-4 下次训练建议（next_advice）内容解析：Markdown 正文 + ```json 结构化建议块

const ADVICE_BLOCK_RE = /```json\s*\n([\s\S]*?)\n```/

/**
 * 拆分 AI 报告 content_md：
 * 返回 { markdown, advice }；无 JSON 块或解析失败时 advice 为 null。
 */
export function parseNextAdvice(contentMd) {
  const text = contentMd || ''
  const match = text.match(ADVICE_BLOCK_RE)
  if (!match) {
    return { markdown: text, advice: null }
  }
  let advice = null
  try {
    const data = JSON.parse(match[1])
    if (data && data.schema === 'next_advice_v1' && Array.isArray(data.suggestions)) {
      advice = data
    }
  } catch {
    advice = null
  }
  const markdown = text.replace(ADVICE_BLOCK_RE, '').trim()
  return { markdown, advice }
}

/** 建议按两类分组：auto_writable（可自动写回）/ manual（需手动调整）。 */
export function groupSuggestions(advice) {
  const grouped = { auto_writable: [], manual: [] }
  for (const s of advice?.suggestions || []) {
    if (grouped[s.category]) grouped[s.category].push(s)
  }
  return grouped
}

/** 参数对象转可读文本，如 {weight:60,sets:4,reps:10} → "60kg · 4组 × 10次"。 */
export function formatParams(params) {
  if (!params || typeof params !== 'object') return '-'
  const parts = []
  if (params.weight != null) parts.push(`${params.weight}${params.unit || 'kg'}`)
  if (params.sets != null && params.reps != null) parts.push(`${params.sets}组 × ${params.reps}次`)
  else if (params.reps != null) parts.push(`${params.reps}次`)
  if (params.rpe != null) parts.push(`RPE ${params.rpe}`)
  if (params.difficulty != null) parts.push(`难度 ${params.difficulty}`)
  return parts.length > 0 ? parts.join(' · ') : '-'
}
