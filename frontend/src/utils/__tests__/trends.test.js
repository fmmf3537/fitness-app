import { describe, expect, it } from 'vitest'
import {
  buildBodyMetricOption,
  buildBodyPartOption,
  buildSleepVolumeOption,
  buildWeeklyVolumeOption,
} from '../trends'

describe('buildWeeklyVolumeOption', () => {
  it('正常装配柱状图：x=week_start，y=volume_tons', () => {
    const option = buildWeeklyVolumeOption([
      { week_start: '2026-07-13', volume_tons: 12.34, sessions: 3 },
      { week_start: '2026-07-20', volume_tons: 8.1, sessions: 2 },
    ])
    expect(option.xAxis.data).toEqual(['2026-07-13', '2026-07-20'])
    expect(option.series).toHaveLength(1)
    expect(option.series[0].type).toBe('bar')
    expect(option.series[0].data).toEqual([12.34, 8.1])
  })

  it('tooltip formatter 展示 sessions', () => {
    const option = buildWeeklyVolumeOption([
      { week_start: '2026-07-13', volume_tons: 12.34, sessions: 3 },
    ])
    const text = option.tooltip.formatter([{ name: '2026-07-13', value: 12.34, dataIndex: 0 }])
    expect(text).toContain('2026-07-13')
    expect(text).toContain('12.34')
    expect(text).toContain('3')
  })

  it('空数组返回合法 option（series 数据为空）', () => {
    const option = buildWeeklyVolumeOption([])
    expect(option.xAxis.data).toEqual([])
    expect(option.series[0].data).toEqual([])
  })
})

describe('buildBodyPartOption', () => {
  const DATA = [
    { week_start: '2026-07-13', parts: { 胸: 2, 背: 1 } },
    { week_start: '2026-07-20', parts: { 腿: 3 } },
    { week_start: '2026-07-27', parts: {} },
  ]

  it('按部位堆叠柱状图，部位集合取所有周并集且排序稳定', () => {
    const option = buildBodyPartOption(DATA)
    expect(option.xAxis.data).toEqual(['2026-07-13', '2026-07-20', '2026-07-27'])
    const names = option.series.map((s) => s.name)
    expect(names).toEqual(['背', '腿', '胸'].sort())
    for (const s of option.series) {
      expect(s.type).toBe('bar')
      expect(s.stack).toBeTruthy()
    }
  })

  it('各部位数据按周对齐，缺失补 0', () => {
    const option = buildBodyPartOption(DATA)
    const byName = Object.fromEntries(option.series.map((s) => [s.name, s.data]))
    expect(byName['胸']).toEqual([2, 0, 0])
    expect(byName['背']).toEqual([1, 0, 0])
    expect(byName['腿']).toEqual([0, 3, 0])
  })

  it('空数组返回合法 option（series 为空）', () => {
    const option = buildBodyPartOption([])
    expect(option.xAxis.data).toEqual([])
    expect(option.series).toEqual([])
  })
})

describe('buildBodyMetricOption', () => {
  it('weight/bodyfat 两条折线 series，x 为日期并集', () => {
    const option = buildBodyMetricOption({
      weight: [
        { date: '2026-07-15', value: 72.4 },
        { date: '2026-07-22', value: 71.9 },
      ],
      bodyfat: [{ date: '2026-07-15', value: 18.2 }],
    })
    expect(option.xAxis.data).toEqual(['2026-07-15', '2026-07-22'])
    expect(option.series.map((s) => s.name)).toEqual(['体重', '体脂率'])
    expect(option.series[0].type).toBe('line')
    expect(option.series[0].data).toEqual([72.4, 71.9])
    expect(option.series[1].data).toEqual([18.2, null])
  })

  it('某类无数据时该 series 为空数组而非报错', () => {
    const option = buildBodyMetricOption({
      weight: [{ date: '2026-07-15', value: 72.4 }],
    })
    expect(option.series[0].data).toEqual([72.4])
    expect(option.series[1].data).toEqual([])
  })

  it('空对象返回合法 option（series 数据为空）', () => {
    const option = buildBodyMetricOption({})
    expect(option.xAxis.data).toEqual([])
    expect(option.series[0].data).toEqual([])
    expect(option.series[1].data).toEqual([])
  })
})

describe('buildSleepVolumeOption', () => {
  it('散点图：x=sleep_hours，y=volume_tons', () => {
    const option = buildSleepVolumeOption([
      { date: '2026-07-15', sleep_hours: 7.2, volume_tons: 4.1 },
      { date: '2026-07-16', sleep_hours: 6.5, volume_tons: 5.0 },
    ])
    expect(option.series).toHaveLength(1)
    expect(option.series[0].type).toBe('scatter')
    expect(option.series[0].data).toEqual([
      [7.2, 4.1],
      [6.5, 5.0],
    ])
  })

  it('空数组返回合法 option（series 数据为空）', () => {
    const option = buildSleepVolumeOption([])
    expect(option.series[0].data).toEqual([])
  })
})
