/** 轻量 Markdown 渲染：支持 # / ## 标题与正文段落（供 AI 报告类区块共用）。 */
export default function SimpleMarkdown({ text }) {
  return (
    <div className="space-y-2">
      {(text || '').split('\n').map((line, i) => {
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
          <p key={i} className="text-sm text-gray-800">
            {line}
          </p>
        )
      })}
    </div>
  )
}
