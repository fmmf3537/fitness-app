import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import SimpleMarkdown from '../SimpleMarkdown'

describe('SimpleMarkdown', () => {
  it('普通段落渲染为 <p> 且带 break-words（长词可断行）', () => {
    const { container } = render(<SimpleMarkdown text={'第一行\n第二行'} />)
    const ps = container.querySelectorAll('p')
    expect(ps).toHaveLength(2)
    ps.forEach((p) => expect(p.className).toContain('break-words'))
  })

  it('标题行渲染规则保持不变', () => {
    render(<SimpleMarkdown text={'# 一级\n## 二级\n正文'} />)
    expect(screen.getByText('一级').tagName).toMatch(/^H/)
    expect(screen.getByText('二级').tagName).toMatch(/^H/)
    expect(screen.getByText('正文').tagName).toBe('P')
  })

  it('``` 围栏块渲染为可横向滚动的 <pre>，围栏行本身不渲染', () => {
    const md = ['前文', '```json', '{"a":1}', '```', '后文'].join('\n')
    const { container } = render(<SimpleMarkdown text={md} />)
    const pre = container.querySelector('pre')
    expect(pre).not.toBeNull()
    expect(pre.className).toContain('overflow-x-auto')
    expect(pre.className).toContain('text-xs')
    expect(pre.textContent).toContain('{"a":1}')
    expect(container.textContent).not.toContain('```')
    expect(screen.getByText('前文')).toBeInTheDocument()
    expect(screen.getByText('后文')).toBeInTheDocument()
  })

  it('含超长无空格 JSON 行的 markdown：长行渲染在可滚动 pre 内而非 <p>', () => {
    const longLine = `{"movements":[{"name":"深蹲","sets":[${'"x",'.repeat(80)}"y"]}]}`
    const md = ['```json', longLine, '```'].join('\n')
    const { container } = render(<SimpleMarkdown text={md} />)
    const pre = container.querySelector('pre')
    expect(pre).not.toBeNull()
    expect(pre.textContent).toContain(longLine)
    // 任何 <p> 都不得包含该超长行（否则 flex min-width:auto 会撑破抽屉）
    const ps = [...container.querySelectorAll('p')]
    expect(ps.some((p) => p.textContent.includes(longLine))).toBe(false)
  })

  it('未闭合的围栏块兜底按 pre 渲染，不丢失内容', () => {
    const md = ['```json', '{"a":1}'].join('\n')
    const { container } = render(<SimpleMarkdown text={md} />)
    const pre = container.querySelector('pre')
    expect(pre).not.toBeNull()
    expect(pre.textContent).toContain('{"a":1}')
  })
})
