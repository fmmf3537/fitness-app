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

function splitTableRow(line) {
  const source = String(line || '').trim()
  const cells = []
  let cell = ''
  let escaped = false
  for (const char of source) {
    if (escaped) {
      cell += char
      escaped = false
    } else if (char === '\\') {
      escaped = true
    } else if (char === '|') {
      cells.push(cell.trim())
      cell = ''
    } else {
      cell += char
    }
  }
  cells.push(cell.trim())
  if (source.startsWith('|')) cells.shift()
  if (source.endsWith('|')) cells.pop()
  return cells
}

function parseTableSeparator(line, expectedColumns) {
  const cells = splitTableRow(line)
  if (cells.length !== expectedColumns || cells.length === 0) return null
  const aligns = []
  for (const cell of cells) {
    if (!/^:?-{3,}:?$/.test(cell)) return null
    aligns.push(cell.startsWith(':') && cell.endsWith(':') ? 'center' : cell.endsWith(':') ? 'right' : 'left')
  }
  return aligns
}

/** 行内解析：先切 `code`（其内容不再解析），再切 **加粗**。 */
function renderInline(text, keyPrefix) {
  const nodes = []
  text.split(INLINE_CODE_RE).forEach((seg, i) => {
    if (!seg) return
    if (seg.length > 2 && seg.startsWith('`') && seg.endsWith('`')) {
      nodes.push(
        <code
          key={`${keyPrefix}-c${i}`}
          className="rounded bg-gray-100 dark:bg-gray-800 px-1 py-0.5 text-xs text-gray-800 dark:text-gray-200"
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
          <strong key={`${keyPrefix}-b${i}-${j}`} className="font-semibold text-gray-900 dark:text-gray-100">
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

  const lines = (text || '').split('\n')
  for (let lineIndex = 0; lineIndex < lines.length; lineIndex += 1) {
    const line = lines[lineIndex]
    if (line.trimStart().startsWith('```')) {
      flushList()
      if (inFence) {
        blocks.push({ type: 'pre', text: fenceLines.join('\n') })
        fenceLines = []
        inFence = false
      } else {
        inFence = true
      }
      continue
    }
    if (inFence) {
      fenceLines.push(line)
      continue
    }
    const header = splitTableRow(line)
    const aligns = line.includes('|') && lineIndex + 1 < lines.length
      ? parseTableSeparator(lines[lineIndex + 1], header.length)
      : null
    if (aligns) {
      flushList()
      const rows = []
      lineIndex += 2
      while (lineIndex < lines.length && lines[lineIndex].trim() && lines[lineIndex].includes('|')) {
        const row = splitTableRow(lines[lineIndex])
        if (row.length !== header.length) break
        rows.push(row)
        lineIndex += 1
      }
      lineIndex -= 1
      blocks.push({ type: 'table', header, aligns, rows })
      continue
    }
    if (UL_RE.test(line)) {
      if (listType !== 'ul') {
        flushList()
        listType = 'ul'
      }
      listItems.push(line.replace(UL_RE, ''))
      continue
    }
    if (OL_RE.test(line)) {
      if (listType !== 'ol') {
        flushList()
        listType = 'ol'
      }
      listItems.push(line.replace(OL_RE, ''))
      continue
    }
    flushList()
    blocks.push({ type: 'line', text: line })
  }
  if (inFence && fenceLines.length > 0) {
    blocks.push({ type: 'pre', text: fenceLines.join('\n') })
  }
  flushList()

  const liClass = 'break-words text-sm text-gray-800 dark:text-gray-200'

  return (
    <div className="space-y-2">
      {blocks.map((block, i) => {
        if (block.type === 'pre') {
          return (
            <pre
              key={i}
              className="overflow-x-auto rounded-md bg-gray-100 dark:bg-gray-800 p-3 text-xs text-gray-700 dark:text-gray-300"
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
        if (block.type === 'table') {
          return (
            <div key={i} className="max-w-full overflow-x-auto rounded-xl border border-gray-200 dark:border-gray-700">
              <table className="min-w-full border-collapse text-sm text-gray-800 dark:text-gray-200">
                <thead className="bg-gray-50 dark:bg-gray-800/80">
                  <tr>
                    {block.header.map((cell, j) => (
                      <th key={j} scope="col" style={{ textAlign: block.aligns[j] }} className="whitespace-nowrap border-b border-gray-200 px-3 py-2 font-semibold dark:border-gray-700">
                        {renderInline(cell, `th${i}-${j}`)}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                  {block.rows.map((row, rowIndex) => (
                    <tr key={rowIndex}>
                      {row.map((cell, j) => (
                        <td key={j} style={{ textAlign: block.aligns[j] }} className="min-w-28 break-words px-3 py-2 align-top">
                          {renderInline(cell, `td${i}-${rowIndex}-${j}`)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        }
        const line = block.text
        if (line.startsWith('#### ')) {
          return (
            <h5 key={i} className="text-sm font-semibold text-gray-700 dark:text-gray-300">
              {renderInline(line.slice(5), `h5-${i}`)}
            </h5>
          )
        }
        if (line.startsWith('### ')) {
          return (
            <h4 key={i} className="text-sm font-bold text-gray-900 dark:text-gray-100">
              {renderInline(line.slice(4), `h4-${i}`)}
            </h4>
          )
        }
        if (line.startsWith('## ')) {
          return (
            <h3 key={i} className="text-base font-bold text-gray-900 dark:text-gray-100">
              {renderInline(line.slice(3), `h3-${i}`)}
            </h3>
          )
        }
        if (line.startsWith('# ')) {
          return (
            <h2 key={i} className="text-lg font-bold text-gray-900 dark:text-gray-100">
              {renderInline(line.slice(2), `h2-${i}`)}
            </h2>
          )
        }
        if (HR_RE.test(line)) {
          return <hr key={i} className="border-gray-200 dark:border-gray-700" />
        }
        if (line.trim() === '') return null
        return (
          <p key={i} className="break-words text-sm text-gray-800 dark:text-gray-200">
            {renderInline(line, `p-${i}`)}
          </p>
        )
      })}
    </div>
  )
}
