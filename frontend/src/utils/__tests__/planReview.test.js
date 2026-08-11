import { describe, expect, it } from 'vitest'
import { fieldLabel, parsePlanReview } from '../planReview'

const VALID = `## 计划点评
本次胸部计划整体合理。

\`\`\`json
{"schema":"plan_review_v1","plan_date":"2026-08-12","modifications":[
{"movement":"杠铃卧推","field":"weight","from":"32.5kg","to":"35kg","reason":"渐进超负荷"},
{"movement":"双杠臂屈伸","field":"sets","from":"3组","to":"4组","reason":"容量不足"}
]}
\`\`\`
`

describe('parsePlanReview', () => {
  it('解析 Markdown 正文与 plan_review_v1 结构化块', () => {
    const { markdown, review } = parsePlanReview(VALID)
    expect(markdown).toContain('计划点评')
    expect(markdown).not.toContain('```json')
    expect(review.plan_date).toBe('2026-08-12')
    expect(review.modifications).toHaveLength(2)
    expect(review.modifications[0].movement).toBe('杠铃卧推')
  })

  it('无 JSON 块时 review 为 null，原文作为 markdown', () => {
    const { markdown, review } = parsePlanReview('## 只有正文')
    expect(review).toBeNull()
    expect(markdown).toContain('只有正文')
  })

  it('JSON 块损坏时 review 为 null', () => {
    const { review } = parsePlanReview('```json\n{oops}\n```')
    expect(review).toBeNull()
  })

  it('schema 不匹配时 review 为 null', () => {
    const text = '```json\n{"schema":"next_advice_v1","suggestions":[]}\n```'
    expect(parsePlanReview(text).review).toBeNull()
  })

  it('空输入安全', () => {
    expect(parsePlanReview(null)).toEqual({ markdown: '', review: null })
  })
})

describe('fieldLabel', () => {
  it('映射已知字段', () => {
    expect(fieldLabel('weight')).toBe('重量')
    expect(fieldLabel('add')).toBe('新增动作')
    expect(fieldLabel('remove')).toBe('删除动作')
  })

  it('未知字段原样返回', () => {
    expect(fieldLabel('other')).toBe('other')
  })
})
