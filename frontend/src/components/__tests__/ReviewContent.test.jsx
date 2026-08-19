import { render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as echarts from 'echarts'
import ReviewContent from '../ReviewContent'
import { installMatchMedia } from '../../test/mockMatchMedia'

vi.mock('echarts', () => ({
  init: vi.fn(() => ({ setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn() })),
}))

const OPTION = {
  title: { text: '近 4 周训练容量趋势图', left: 'left' },
  legend: { top: 8, data: ['容量'] },
  grid: { left: 60, top: 30 },
  xAxis: { type: 'category', name: '周', data: ['07-13', '07-20'] },
  yAxis: { type: 'value', name: '容量（吨）' },
  series: [
    { name: '容量', type: 'bar', label: { show: true, position: 'top' }, data: [12, 8] },
  ],
}

const REPORT_TEXT = `## 周复盘\n\n\`\`\`echarts\n${JSON.stringify(OPTION, null, 2)}\n\`\`\`\n\n## 下周建议\n卧推加到 62.5kg`

function lastSetOption() {
  const results = echarts.init.mock.results
  return results.at(-1).value.setOption.mock.calls.at(-1)?.[0]
}

describe('ReviewContent / EChartBlock', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  afterEach(() => {
    installMatchMedia(false)
  })

  it('桌面端：setOption 收到 LLM option 原样（不合并）', () => {
    installMatchMedia(false)
    render(<ReviewContent text={REPORT_TEXT} />)
    expect(screen.getByTestId('echarts-block')).toBeInTheDocument()
    expect(lastSetOption()).toEqual(OPTION)
  })

  it('移动端：setOption 收到合并后的移动端配置', () => {
    installMatchMedia(true)
    render(<ReviewContent text={REPORT_TEXT} />)

    const merged = lastSetOption()
    expect(merged.title).toMatchObject({ left: 'center', top: 0, textStyle: { fontSize: 13 } })
    expect(merged.title.text).toBe('近 4 周训练容量趋势图')
    expect(merged.grid).toEqual({ top: 56, left: 8, right: 8, bottom: 44, containLabel: true })
    expect(merged.yAxis.name).toBe('容量（吨）')
    expect(merged.yAxis.nameTextStyle.fontSize).toBe(10)
    expect(merged.xAxis.axisLabel).toMatchObject({ fontSize: 10, rotate: 30 })
    expect(merged.legend).toMatchObject({ bottom: 0, type: 'scroll', textStyle: { fontSize: 10 } })
    expect(merged.series[0].label).toMatchObject({ show: true, position: 'top', fontSize: 9 })
    // 数据原样保留
    expect(merged.series[0].data).toEqual([12, 8])
    expect(merged.xAxis.data).toEqual(['07-13', '07-20'])
  })

  it('移动端合并不污染文本块渲染', () => {
    installMatchMedia(true)
    render(<ReviewContent text={REPORT_TEXT} />)
    expect(screen.getByRole('heading', { name: '周复盘' })).toBeInTheDocument()
    expect(screen.getByText(/卧推加到 62.5kg/)).toBeInTheDocument()
  })

  it('非法 JSON 仍按原文 pre 展示（回归保护）', () => {
    installMatchMedia(true)
    render(<ReviewContent text={'```echarts\n{oops}\n```'} />)
    expect(screen.queryByTestId('echarts-block')).not.toBeInTheDocument()
    expect(screen.getByText('{oops}')).toBeInTheDocument()
  })
})
