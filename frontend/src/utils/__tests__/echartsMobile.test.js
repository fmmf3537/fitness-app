import { describe, expect, it } from 'vitest'
import { CHART_PALETTE, mergeMobileOption } from '../echartsMobile'

const BASE_OPTION = {
  title: { text: '近 4 周训练容量趋势图', left: 'left', textStyle: { fontSize: 18, color: '#111' } },
  legend: { top: 8, data: ['容量'] },
  grid: { left: 60, top: 30 },
  xAxis: {
    type: 'category',
    name: '周',
    data: ['07-13', '07-20'],
    axisLabel: { interval: 0 },
  },
  yAxis: { type: 'value', name: '容量（吨）' },
  series: [
    {
      name: '容量',
      type: 'bar',
      label: { show: true, position: 'top', fontSize: 12 },
      data: [12, 8],
    },
  ],
}

describe('mergeMobileOption', () => {
  it('title：居中置顶、字号缩小，原文与其他样式保留', () => {
    const next = mergeMobileOption(BASE_OPTION)
    expect(next.title.left).toBe('center')
    expect(next.title.top).toBe(0)
    expect(next.title.text).toBe('近 4 周训练容量趋势图')
    expect(next.title.textStyle.fontSize).toBe(13)
    expect(next.title.textStyle.color).toBe('#111')
  })

  it('grid：紧凑边距 + containLabel', () => {
    const next = mergeMobileOption(BASE_OPTION)
    expect(next.grid).toEqual({ top: 56, left: 8, right: 8, bottom: 44, containLabel: true })
  })

  it('legend：底部滚动、小字号；原 top 被移除避免上下冲突', () => {
    const next = mergeMobileOption(BASE_OPTION)
    expect(next.legend.bottom).toBe(0)
    expect(next.legend.type).toBe('scroll')
    expect(next.legend.textStyle.fontSize).toBe(10)
    expect(next.legend.data).toEqual(['容量'])
    expect(next.legend.top).toBeUndefined()
  })

  it('yAxis：name 保留，nameTextStyle 缩小', () => {
    const next = mergeMobileOption(BASE_OPTION)
    expect(next.yAxis.name).toBe('容量（吨）')
    expect(next.yAxis.nameTextStyle.fontSize).toBe(10)
  })

  it('xAxis：类目轴 axisLabel 缩小并旋转 30°，原有配置保留', () => {
    const next = mergeMobileOption(BASE_OPTION)
    expect(next.xAxis.axisLabel.fontSize).toBe(10)
    expect(next.xAxis.axisLabel.rotate).toBe(30)
    expect(next.xAxis.axisLabel.interval).toBe(0)
    expect(next.xAxis.data).toEqual(['07-13', '07-20'])
  })

  it('xAxis：数值轴不旋转，仅缩小字号', () => {
    const next = mergeMobileOption({
      xAxis: { type: 'value', name: '睡眠' },
      series: [{ type: 'scatter', data: [] }],
    })
    expect(next.xAxis.axisLabel.fontSize).toBe(10)
    expect(next.xAxis.axisLabel.rotate).toBeUndefined()
  })

  it('series：每个系列的 label 字号缩小为 10，原有 label 配置保留', () => {
    const next = mergeMobileOption(BASE_OPTION)
    expect(next.series[0].label.fontSize).toBe(10)
    expect(next.series[0].label.show).toBe(true)
    expect(next.series[0].label.position).toBe('top')
    expect(next.series[0].data).toEqual([12, 8])
  })

  it('series 无 label 时新建 label 对象', () => {
    const next = mergeMobileOption({ series: [{ type: 'line', data: [1, 2] }] })
    expect(next.series[0].label).toEqual({ fontSize: 10 })
  })

  it('无 legend/title/grid 时安全新建', () => {
    const next = mergeMobileOption({ series: [{ type: 'pie', data: [] }] })
    expect(next.legend).toMatchObject({ bottom: 0, type: 'scroll', textStyle: { fontSize: 10 } })
    expect(next.title).toMatchObject({ left: 'center', top: 0, textStyle: { fontSize: 13 } })
    expect(next.grid).toEqual({ top: 56, left: 8, right: 8, bottom: 44, containLabel: true })
  })

  it('无 xAxis/yAxis/series 时不凭空创建坐标轴与系列', () => {
    const next = mergeMobileOption({ series: undefined })
    expect(next.xAxis).toBeUndefined()
    expect(next.yAxis).toBeUndefined()
    expect(next.series).toBeUndefined()
  })

  it('支持 xAxis/yAxis 数组形式', () => {
    const next = mergeMobileOption({
      xAxis: [{ type: 'category', data: ['a'] }, { type: 'category', data: ['b'] }],
      yAxis: [{ type: 'value', name: '吨' }, { type: 'value', name: '次' }],
    })
    expect(next.xAxis[0].axisLabel).toMatchObject({ fontSize: 10, rotate: 30 })
    expect(next.xAxis[1].axisLabel).toMatchObject({ fontSize: 10, rotate: 30 })
    expect(next.yAxis[0]).toMatchObject({ name: '吨', nameTextStyle: { fontSize: 10 } })
    expect(next.yAxis[1]).toMatchObject({ name: '次', nameTextStyle: { fontSize: 10 } })
  })

  it('输入 option 不被修改（不可变性）', () => {
    const input = JSON.parse(JSON.stringify(BASE_OPTION))
    const snapshot = JSON.parse(JSON.stringify(BASE_OPTION))
    mergeMobileOption(input)
    expect(input).toEqual(snapshot)
  })

  it('overrides.grid 深合并覆盖 MOBILE_GRID 对应键', () => {
    const next = mergeMobileOption(BASE_OPTION, { grid: { right: 40 } })
    expect(next.grid).toEqual({
      top: 56,
      left: 8,
      right: 40,
      bottom: 44,
      containLabel: true,
    })
  })

  it('overrides.xAxisLabel 整体替换 axisLabel', () => {
    const label = { rotate: 30, fontSize: 10, formatter: '{MM}-{dd}' }
    const next = mergeMobileOption(BASE_OPTION, { xAxisLabel: label })
    expect(next.xAxis.axisLabel).toEqual(label)
  })
})

describe('CHART_PALETTE', () => {
  it('五色定序：indigo/sky/amber/rose/emerald', () => {
    expect(CHART_PALETTE).toEqual([
      '#4f46e5',
      '#0ea5e9',
      '#f59e0b',
      '#e11d48',
      '#10b981',
    ])
  })
})
