/**
 * 轻量 Markdown 渲染（AI 报告类区块共用，零依赖手写解析）：
 * - 标题：# / ## / ### / ####（行内符号照常解析）；
 * - 行内：**加粗**（一行多段）、`行内代码`（code 内不再解析其他符号）、链接按纯文本；
 * - 块级：--- 分隔线、- 无序列表、1. 有序列表（连续项合并）、``` 围栏代码块
 *   渲染为可横向滚动的 <pre>，避免超长无空格字符串撑破父级 flex 布局；
 * - 未闭合围栏兜底按 pre 渲染，未闭合 ** 按纯文本，不丢内容。
 */

const UL_RE = /^\s*[-*]\s+/
const OL_RE = /^\s*\d+[.、)]\s+/
const HR_RE = /^\s*-{3,}\s*$/
const INLINE_CODE_RE = /(`[^`\n]+`)/g
const BOLD_RE = /(\*\*[^\n]+?\*\*)/g

/** 行内解析：先切 `code`（其内容不再解析），再切 **加粗**。 */
function renderInline(text, keyPrefix) {
  const nodes = []
  text.split(INLINE_CODE_RE).forEach((seg, i) => {
    if (!seg) return
    if (seg.length > 2 && seg.startsWith('`') && seg.endsWith('`')) {
      nodes.push(
        <code
          key={`${keyPrefix}-c${i}`}
          className="rounded bg-gray-100 px-1 py-0.5 text-xs text-gray-800"
        >
          {seg.slice(1, -1)}
        </code>,
      )
      return
    }
    seg.split(BOLD_RE).forEach((piece, j) => {
      if (!piece) return
      if (piece.length > 4 && piece.startsWith('**') && piece.endsWith('**')) {
        nodes.push(
          <strong key={`${keyPrefix}-b${i}-${j}`} className="font-semibold text-gray-900">
            {piece.slice(2, -2)}
          </strong>,
        )
      } else {
        nodes.push(piece)
      }
    })
  })
  return nodes
}

export default function SimpleMarkdown({ text }) {
  const blocks = []
  let inFence = false
  let fenceLines = []
  let listType = null // 'ul' | 'ol'
  let listItems = []

  const flushList = () => {
    if (listItems.length > 0) {
      blocks.push({ type: listType, items: listItems })
      listItems = []
      listType = null
    }
  }

  ;(text || '').split('\n').forEach((line) => {
    if (line.trimStart().startsWith('```')) {
      flushList()
      if (inFence) {
        blocks.push({ type: 'pre', text: fenceLines.join('\n') })
        fenceLines = []
        inFence = false
      } else {
        inFence = true
      }
      return
    }
    if (inFence) {
      fenceLines.push(line)
      return
    }
    if (UL_RE.test(line)) {
      if (listType !== 'ul') {
        flushList()
        listType = 'ul'
      }
      listItems.push(line.replace(UL_RE, ''))
      return
    }
    if (OL_RE.test(line)) {
      if (listType !== 'ol') {
        flushList()
        listType = 'ol'
      }
      listItems.push(line.replace(OL_RE, ''))
      return
    }
    flushList()
    blocks.push({ type: 'line', text: line })
  })
  if (inFence && fenceLines.length > 0) {
    blocks.push({ type: 'pre', text: fenceLines.join('\n') })
  }
  flushList()

  const liClass = 'break-words text-sm text-gray-800'

  return (
    <div className="space-y-2">
      {blocks.map((block, i) => {
        if (block.type === 'pre') {
          return (
            <pre
              key={i}
              className="overflow-x-auto rounded-md bg-gray-100 p-3 text-xs text-gray-700"
            >
              {block.text}
            </pre>
          )
        }
        if (block.type === 'ul') {
          return (
            <ul key={i} className="list-disc space-y-1 pl-5">
              {block.items.map((item, j) => (
                <li key={j} className={liClass}>
                  {renderInline(item, `ul${i}-${j}`)}
                </li>
              ))}
            </ul>
          )
        }
        if (block.type === 'ol') {
          return (
            <ol key={i} className="list-decimal space-y-1 pl-5">
              {block.items.map((item, j) => (
                <li key={j} className={liClass}>
                  {renderInline(item, `ol${i}-${j}`)}
                </li>
              ))}
            </ol>
          )
        }
        const line = block.text
        if (line.startsWith('#### ')) {
          return (
            <h4 key={i} className="text-sm font-bold text-gray-900">
              {renderInline(line.slice(5), `h4-${i}`)}
            </h4>
          )
        }
        if (line.startsWith('### ')) {
          return (
            <h3 key={i} className="text-sm font-bold text-gray-900">
              {renderInline(line.slice(4), `h3s-${i}`)}
            </h3>
          )
        }
        if (line.startsWith('## ')) {
          return (
            <h3 key={i} className="text-base font-bold text-gray-900">
              {renderInline(line.slice(3), `h2-${i}`)}
            </h3>
          )
        }
        if (line.startsWith('# ')) {
          return (
            <h3 key={i} className="text-lg font-bold text-gray-900">
              {renderInline(line.slice(2), `h1-${i}`)}
            </h3>
          )
        }
        if (HR_RE.test(line)) {
          return <hr key={i} className="border-gray-200" />
        }
        if (line.trim() === '') return null
        return (
          <p key={i} className="break-words text-sm text-gray-800">
            {renderInline(line, `p-${i}`)}
          </p>
        )
      })}
    </div>
  )
}
