import { describe, expect, it } from 'vitest'
import {
  METRIC_DEFS,
  METRIC_GROUPS,
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

  it('V3-9：包含体脂秤 10 类新指标且单位正确', () => {
    const map = Object.fromEntries(METRIC_DEFS.map((d) => [d.type, d]))
    const expected = {
      visceral_fat: '级',
      bmr: 'kcal',
      muscle_rate: '%',
      water_rate: '%',
      protein_rate: '%',
      bone_mass: 'kg',
      muscle_ability: '级',
      bmi: 'kg/m²',
      body_age: '岁',
      body_score: '分',
    }
    for (const [type, unit] of Object.entries(expected)) {
      expect(map[type], type).toBeTruthy()
      expect(map[type].unit, type).toBe(unit)
      expect(map[type].syncable, type).toBe(false)
    }
  })

  it('V3-9：METRIC_GROUPS 分组覆盖全部指标（基础/成分/评估/日常记录）', () => {
    const grouped = METRIC_GROUPS.flatMap((g) => g.types)
    expect(new Set(grouped).size).toBe(METRIC_DEFS.length)
    const labels = Object.fromEntries(METRIC_GROUPS.map((g) => [g.label, g.types]))
    expect(labels['基础']).toEqual(['weight', 'bodyfat', 'bmi'])
    expect(labels['成分']).toEqual(['muscle_rate', 'water_rate', 'protein_rate', 'bone_mass'])
    expect(labels['评估']).toEqual(
      expect.arrayContaining(['visceral_fat', 'bmr', 'body_age', 'body_score']),
    )
    expect(labels['日常记录']).toEqual(
      expect.arrayContaining(['height', 'bp_systolic', 'bp_diastolic', 'blood_glucose']),
    )
  })

  it('仅 weight/bodyfat 可同步训记，其余仅本地', () => {
    expect(isSyncable('weight')).toBe(true)
    expect(isSyncable('bodyfat')).toBe(true)
    expect(isSyncable('height')).toBe(false)
    expect(isSyncable('bp_systolic')).toBe(false)
    expect(isSyncable('bp_diastolic')).toBe(false)
    expect(isSyncable('blood_glucose')).toBe(false)
    expect(isSyncable('bmi')).toBe(false)
    expect(isSyncable('visceral_fat')).toBe(false)
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

describe('移动端适配（mobile 参数）', () => {
  const WEIGHTS = [
    { date: '2026-08-01', value: 72.4 },
    { date: '2026-08-03', value: 72.0 },
  ]
  const VOLUME = [{ week_start: '2026-07-27', volume_tons: 8.1, sessions: 2 }]

  it('desktop 缺省：输出与基线一致', () => {
    const trend = buildMetricTrendOption(WEIGHTS, '体重', 'kg')
    expect(trend.grid).toEqual({ left: 50, right: 20, top: 40, bottom: 30 })
    expect(trend.xAxis.axisLabel).toBeUndefined()
    const dual = buildWeightVolumeOption(VOLUME, WEIGHTS)
    expect(dual.grid).toEqual({ left: 50, right: 50, top: 40, bottom: 30 })
    expect(dual.legend).toEqual({ top: 0 })
    expect(dual.xAxis.axisLabel).toBeUndefined()
  })

  it('mobile：单指标趋势 rotate45/日期裁剪/grid 移动端值/y 轴去名', () => {
    const option = buildMetricTrendOption(WEIGHTS, '体重', 'kg', { mobile: true })
    expect(option.grid).toEqual({ left: 40, right: 12, top: 56, bottom: 48 })
    expect(option.xAxis.axisLabel.rotate).toBe(45)
    expect(option.xAxis.axisLabel.fontSize).toBe(10)
    expect(option.xAxis.axisLabel.formatter('2026-08-01')).toBe('08-01')
    expect(option.yAxis.name).toBeUndefined()
  })

  it('mobile：体重×容量双轴图 time 轴用 {MM}-{dd} 模板，右 y 轴保留宽度', () => {
    const option = buildWeightVolumeOption(VOLUME, WEIGHTS, { mobile: true })
    expect(option.xAxis.axisLabel).toEqual({ rotate: 45, fontSize: 10, formatter: '{MM}-{dd}' })
    expect(option.legend.type).toBe('scroll')
    expect(option.grid.left).toBe(40)
    expect(option.grid.top).toBe(56)
    expect(option.grid.bottom).toBe(48)
    expect(option.grid.right).toBeGreaterThanOrEqual(30)
    expect(option.yAxis.every((y) => y.name === undefined)).toBe(true)
  })
})
