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

  // ================= V3-4 任务1：全语法渲染 =================

  it('### / #### 渲染为 h3/h4 样式标题', () => {
    render(<SimpleMarkdown text={'### 三级标题\n#### 四级标题'} />)
    const h3el = screen.getByText('三级标题')
    expect(['H3', 'H4']).toContain(h3el.tagName)
    expect(h3el.className).toContain('font-bold')
    const h4el = screen.getByText('四级标题')
    expect(h4el.tagName).toBe('H4')
    expect(h4el.className).toContain('font-bold')
  })

  it('行内 **加粗** 解析：一行多段加粗均生效', () => {
    const { container } = render(<SimpleMarkdown text={'这是**重点**与**次重点**内容'} />)
    const strongs = container.querySelectorAll('strong')
    expect(strongs).toHaveLength(2)
    expect(strongs[0].textContent).toBe('重点')
    expect(strongs[1].textContent).toBe('次重点')
    expect(container.textContent).not.toContain('**')
  })

  it('标题与列表项内的 **加粗** 同样被行内解析', () => {
    const { container } = render(<SimpleMarkdown text={'## **加粗标题**\n- **加粗项** 说明'} />)
    const strongs = container.querySelectorAll('strong')
    expect(strongs).toHaveLength(2)
    expect(strongs[0].textContent).toBe('加粗标题')
    expect(strongs[1].textContent).toBe('加粗项')
  })

  it('--- 渲染为分隔线 <hr>，原始符号不显示', () => {
    const { container } = render(<SimpleMarkdown text={'上文\n---\n下文'} />)
    expect(container.querySelector('hr')).not.toBeNull()
    expect(container.textContent).not.toContain('---')
    expect(screen.getByText('上文')).toBeInTheDocument()
    expect(screen.getByText('下文')).toBeInTheDocument()
  })

  it('- 无序列表渲染为 ul/li，连续项合并为一个列表', () => {
    const { container } = render(<SimpleMarkdown text={'- 苹果\n- 香蕉\n正文'} />)
    const ul = container.querySelector('ul')
    expect(ul).not.toBeNull()
    expect(ul.className).toContain('list-disc')
    const lis = ul.querySelectorAll('li')
    expect(lis).toHaveLength(2)
    expect(lis[0].textContent).toBe('苹果')
    expect(screen.getByText('正文').tagName).toBe('P')
  })

  it('数字列表渲染为 ol/li', () => {
    const { container } = render(<SimpleMarkdown text={'1. 第一步\n2. 第二步'} />)
    const ol = container.querySelector('ol')
    expect(ol).not.toBeNull()
    expect(ol.className).toContain('list-decimal')
    const lis = ol.querySelectorAll('li')
    expect(lis).toHaveLength(2)
    expect(lis[1].textContent).toBe('第二步')
  })

  it('段内行内代码 `code` 渲染为 <code>', () => {
    const { container } = render(<SimpleMarkdown text={'使用 `dry_run: true` 预览'} />)
    const code = container.querySelector('code')
    expect(code).not.toBeNull()
    expect(code.textContent).toBe('dry_run: true')
    expect(container.querySelector('p').textContent).toContain('使用')
  })

  it('嵌套边界：code 内的 ** 不再解析为加粗', () => {
    const { container } = render(<SimpleMarkdown text={'示例 `**不加粗**` 但**真加粗**生效'} />)
    const code = container.querySelector('code')
    expect(code.textContent).toBe('**不加粗**')
    const strongs = container.querySelectorAll('strong')
    expect(strongs).toHaveLength(1)
    expect(strongs[0].textContent).toBe('真加粗')
  })

  it('嵌套边界：单个 * 与未闭合 ** 按纯文本处理', () => {
    const { container } = render(<SimpleMarkdown text={'心率 2 * 3 区间，以及**未闭合'} />)
    expect(container.querySelectorAll('strong')).toHaveLength(0)
    expect(container.textContent).toContain('2 * 3')
  })

  it('链接按纯文本处理，不渲染为 <a>', () => {
    const { container } = render(<SimpleMarkdown text={'详见 [文档](https://example.com)'} />)
    expect(container.querySelector('a')).toBeNull()
  })

  it('混排集成：标题+加粗段落+列表+分隔线+围栏块', () => {
    const md = [
      '# 总览',
      '本次**完成度高**，心率 `150bpm`',
      '### 细节',
      '- 深蹲 60kg',
      '- 卧推 40kg',
      '---',
      '```json',
      '{"score":85}',
      '```',
      '收尾',
    ].join('\n')
    const { container } = render(<SimpleMarkdown text={md} />)
    expect(screen.getByText('总览').tagName).toMatch(/^H/)
    expect(container.querySelector('strong').textContent).toBe('完成度高')
    expect(container.querySelector('code').textContent).toBe('150bpm')
    expect(container.querySelectorAll('li')).toHaveLength(2)
    expect(container.querySelector('hr')).not.toBeNull()
    expect(container.querySelector('pre').textContent).toContain('{"score":85}')
    expect(container.textContent).not.toContain('```')
  })
})
