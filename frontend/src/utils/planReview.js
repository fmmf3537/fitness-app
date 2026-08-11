// V2-8 计划级 AI 点评（plan_review）内容解析：Markdown 正文 + ```json 结构化修改建议块

const REVIEW_BLOCK_RE = /```json\s*\n([\s\S]*?)\n```/

/**
 * 拆分 plan_review 报告 content_md。
 * 返回 { markdown, review }；无 JSON 块或解析失败时 review 为 null。
 */
export function parsePlanReview(contentMd) {
  const text = contentMd || ''
  const match = text.match(REVIEW_BLOCK_RE)
  if (!match) {
    return { markdown: text, review: null }
  }
  let review = null
  try {
    const data = JSON.parse(match[1])
    if (data && data.schema === 'plan_review_v1' && Array.isArray(data.modifications)) {
      review = data
    }
  } catch {
    review = null
  }
  const markdown = text.replace(REVIEW_BLOCK_RE, '').trim()
  return { markdown, review }
}

/** 修改建议 field 值的中文标签 */
export const FIELD_LABELS = {
  weight: '重量',
  reps: '次数',
  sets: '组数',
  add: '新增动作',
  remove: '删除动作',
}

export function fieldLabel(field) {
  return FIELD_LABELS[field] || field || '—'
}
