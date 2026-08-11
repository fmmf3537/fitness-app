import { useEffect, useRef } from 'react'
import * as echarts from 'echarts'
import SimpleMarkdown from './SimpleMarkdown'

// 拆分 content_md 中的 ```echarts 围栏块，其余按轻量 Markdown 渲染
const ECHARTS_RE = /```echarts\s*\n([\s\S]*?)```/g

function splitReviewBlocks(text) {
  const parts = []
  let last = 0
  let m
  const source = text || ''
  ECHARTS_RE.lastIndex = 0
  while ((m = ECHARTS_RE.exec(source)) !== null) {
    if (m.index > last) parts.push({ type: 'md', text: source.slice(last, m.index) })
    parts.push({ type: 'echarts', text: m[1] })
    last = m.index + m[0].length
  }
  if (last < source.length) parts.push({ type: 'md', text: source.slice(last) })
  return parts
}

function EChartBlock({ optionText }) {
  const ref = useRef(null)

  useEffect(() => {
    let option = null
    try {
      option = JSON.parse(optionText)
    } catch {
      return undefined
    }
    const chart = echarts.init(ref.current)
    chart.setOption(option)
    return () => chart.dispose()
  }, [optionText])

  let valid = true
  try {
    JSON.parse(optionText)
  } catch {
    valid = false
  }
  if (!valid) {
    return (
      <pre className="overflow-x-auto rounded-md bg-gray-100 p-3 text-xs text-gray-600">
        {optionText}
      </pre>
    )
  }
  return <div ref={ref} data-testid="echarts-block" className="h-64 w-full" />
}

export default function ReviewContent({ text }) {
  const blocks = splitReviewBlocks(text)
  return (
    <div className="space-y-4">
      {blocks.map((b, i) =>
        b.type === 'echarts' ? (
          <EChartBlock key={i} optionText={b.text} />
        ) : (
          <SimpleMarkdown key={i} text={b.text} />
        ),
      )}
    </div>
  )
}
