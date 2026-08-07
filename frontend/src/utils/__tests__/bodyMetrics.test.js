import { describe, expect, it } from 'vitest'
import {
  METRIC_DEFS,
  buildMetricTrendOption,
  buildWeightVolumeOption,
  groupByType,
  isSyncable,
} from '../bodyMetrics'

describe('METRIC_DEFS', () => {
  it('包含六类指标且单位正确', () => {
    const map = Object.fromEntries(METRIC_DEFS.map((d) => [d.type, d]))
    expect(map.height.unit).toBe('cm')
    expect(map.weight.unit).toBe('kg')
    expect(map.bodyfat.unit).toBe('%')
    expect(map.bp_systolic.unit).toBe('mmHg')
    expect(map.bp_diastolic.unit).toBe('mmHg')
    expect(map.blood_glucose.unit).toBe('mmol/L')
  })

  it('仅 weight/bodyfat 可同步训记，其余仅本地', () => {
    expect(isSyncable('weight')).toBe(true)
    expect(isSyncable('bodyfat')).toBe(true)
    expect(isSyncable('height')).toBe(false)
    expect(isSyncable('bp_systolic')).toBe(false)
    expect(isSyncable('bp_diastolic')).toBe(false)
    expect(isSyncable('blood_glucose')).toBe(false)
  })
})

describe('groupByType', () => {
  it('按类型分组且组内日期升序', () => {
    const records = [
      { date: '2026-08-01', type: 'weight', value: 72 },
      { date: '2026-07-01', type: 'weight', value: 73 },
      { date: '2026-07-15', type: 'height', value: 175 },
    ]
    const grouped = groupByType(records)
    expect(grouped.weight.map((r) => r.value)).toEqual([73, 72])
    expect(grouped.height).toHaveLength(1)
  })

  it('空输入返回空对象', () => {
    expect(groupByType(null)).toEqual({})
  })
})

describe('buildMetricTrendOption', () => {
  it('单指标折线：x 为日期，y 为数值', () => {
    const option = buildMetricTrendOption(
      [
        { date: '2026-08-01', value: 72.4 },
        { date: '2026-08-03', value: 72.0 },
      ],
      '体重',
      'kg',
    )
    expect(option.xAxis.data).toEqual(['2026-08-01', '2026-08-03'])
    expect(option.series).toHaveLength(1)
    expect(option.series[0].name).toBe('体重')
    expect(option.series[0].data).toEqual([72.4, 72.0])
    expect(option.yAxis.name).toBe('kg')
  })

  it('空数据返回合法空 option', () => {
    const option = buildMetricTrendOption([], '体重', 'kg')
    expect(option.xAxis.data).toEqual([])
    expect(option.series[0].data).toEqual([])
  })
})

describe('buildWeightVolumeOption', () => {
  it('体重曲线与周容量同屏双轴', () => {
    const option = buildWeightVolumeOption(
      [{ week_start: '2026-07-27', volume_tons: 12.3 }],
      [
        { date: '2026-07-28', value: 72.4 },
        { date: '2026-08-01', value: 72.0 },
      ],
    )
    expect(option.yAxis).toHaveLength(2)
    const bar = option.series.find((s) => s.type === 'bar')
    const line = option.series.find((s) => s.type === 'line')
    expect(bar.name).toBe('周容量')
    expect(bar.data).toEqual([['2026-07-27', 12.3]])
    expect(line.name).toBe('体重')
    expect(line.data).toEqual([
      ['2026-07-28', 72.4],
      ['2026-08-01', 72.0],
    ])
  })

  it('空输入不崩溃', () => {
    const option = buildWeightVolumeOption([], [])
    expect(option.series.find((s) => s.type === 'bar').data).toEqual([])
    expect(option.series.find((s) => s.type === 'line').data).toEqual([])
  })
})
