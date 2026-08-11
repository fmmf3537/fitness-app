/**
 * 轻量 Markdown 渲染（AI 报告类区块共用）：
 * - 支持 # / ## 标题与正文段落（段落 break-words，长词可断行）；
 * - 支持 ``` 围栏代码块：渲染为可横向滚动的 <pre>，
 *   避免单行超长无空格字符串（如 LLM 输出的 JSON）撑破父级 flex 布局；
 * - 未闭合围栏兜底按 pre 渲染，不丢内容。
 */
export default function SimpleMarkdown({ text }) {
  const blocks = []
  let inFence = false
  let fenceLines = []

  ;(text || '').split('\n').forEach((line) => {
    if (line.trimStart().startsWith('```')) {
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
    blocks.push({ type: 'line', text: line })
  })
  if (inFence && fenceLines.length > 0) {
    blocks.push({ type: 'pre', text: fenceLines.join('\n') })
  }

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
        const line = block.text
        if (line.startsWith('## ')) {
          return (
            <h3 key={i} className="text-base font-bold text-gray-900">
              {line.slice(3)}
            </h3>
          )
        }
        if (line.startsWith('# ')) {
          return (
            <h3 key={i} className="text-lg font-bold text-gray-900">
              {line.slice(2)}
            </h3>
          )
        }
        if (line.trim() === '') return null
        return (
          <p key={i} className="break-words text-sm text-gray-800">
            {line}
          </p>
        )
      })}
    </div>
  )
}
