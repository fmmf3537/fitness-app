// V1-7 身体数据页：指标定义与 ECharts option 构造纯函数（PRD US-12）。

import { applyMobile } from './trends'

/** 指标定义；syncable=false 的指标训记 API 不支持，仅本地保存。
 *  V3-9：新增体脂秤 10 类指标，并按 基础/成分/评估/日常记录 分组。 */
export const METRIC_DEFS = [
  { type: 'weight', label: '体重', unit: 'kg', syncable: true, group: 'basic' },
  { type: 'bodyfat', label: '体脂率', unit: '%', syncable: true, group: 'basic' },
  { type: 'bmi', label: 'BMI', unit: 'kg/m²', syncable: false, group: 'basic' },
  { type: 'muscle_rate', label: '肌肉率', unit: '%', syncable: false, group: 'composition' },
  { type: 'water_rate', label: '水分', unit: '%', syncable: false, group: 'composition' },
  { type: 'protein_rate', label: '蛋白质', unit: '%', syncable: false, group: 'composition' },
  { type: 'bone_mass', label: '骨量', unit: 'kg', syncable: false, group: 'composition' },
  { type: 'visceral_fat', label: '内脏脂肪指数', unit: '级', syncable: false, group: 'evaluation' },
  { type: 'bmr', label: '基础代谢率', unit: 'kcal', syncable: false, group: 'evaluation' },
  { type: 'body_age', label: '身体年龄', unit: '岁', syncable: false, group: 'evaluation' },
  { type: 'body_score', label: '身体评分', unit: '分', syncable: false, group: 'evaluation' },
  { type: 'muscle_ability', label: '储肌能力等级', unit: '级', syncable: false, group: 'evaluation' },
  { type: 'height', label: '身高', unit: 'cm', syncable: false, group: 'daily' },
  { type: 'bp_systolic', label: '收缩压', unit: 'mmHg', syncable: false, group: 'daily' },
  { type: 'bp_diastolic', label: '舒张压', unit: 'mmHg', syncable: false, group: 'daily' },
  { type: 'blood_glucose', label: '血糖', unit: 'mmol/L', syncable: false, group: 'daily' },
]

/** 趋势切换器分组（顺序即展示顺序）。 */
export const METRIC_GROUPS = [
  { key: 'basic', label: '基础', types: ['weight', 'bodyfat', 'bmi'] },
  { key: 'composition', label: '成分', types: ['muscle_rate', 'water_rate', 'protein_rate', 'bone_mass'] },
  { key: 'evaluation', label: '评估', types: ['visceral_fat', 'bmr', 'body_age', 'body_score', 'muscle_ability'] },
  { key: 'daily', label: '日常记录', types: ['height', 'bp_systolic', 'bp_diastolic', 'blood_glucose'] },
]

export function metricLabel(type) {
  return METRIC_DEFS.find((d) => d.type === type)?.label || type
}

/** 仅 weight/bodyfat 可同步到训记（PRD §6.1b）。 */
export function isSyncable(type) {
  return METRIC_DEFS.find((d) => d.type === type)?.syncable === true
}

/** 按类型分组，组内按日期升序。 */
export function groupByType(records) {
  const grouped = {}
  for (const r of Array.isArray(records) ? records : []) {
    if (!grouped[r.type]) grouped[r.type] = []
    grouped[r.type].push(r)
  }
  for (const rows of Object.values(grouped)) {
    rows.sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0))
  }
  return grouped
}

const BASE_GRID = { left: 50, right: 20, top: 40, bottom: 30 }

/** 单指标趋势折线：x=日期，y=数值。 */
export function buildMetricTrendOption(records, label, unit, { mobile = false } = {}) {
  const rows = Array.isArray(records) ? records : []
  const option = {
    tooltip: { trigger: 'axis' },
    grid: BASE_GRID,
    xAxis: { type: 'category', name: '日期', data: rows.map((r) => r.date) },
    yAxis: { type: 'value', name: unit },
    series: [
      {
        name: label,
        type: 'line',
        smooth: true,
        connectNulls: true,
        data: rows.map((r) => r.value),
      },
    ],
  }
  return mobile ? applyMobile(option) : option
}

/** 体重曲线与周训练容量同屏对照（双 y 轴，时间轴对齐）。 */
export function buildWeightVolumeOption(weeklyVolume, weights, { mobile = false } = {}) {
  const volume = Array.isArray(weeklyVolume) ? weeklyVolume : []
  const weightRows = Array.isArray(weights) ? weights : []
  const option = {
    tooltip: { trigger: 'axis' },
    legend: { top: 0 },
    grid: { left: 50, right: 50, top: 40, bottom: 30 },
    xAxis: { type: 'time', name: '日期' },
    yAxis: [
      { type: 'value', name: 'kg' },
      { type: 'value', name: '吨' },
    ],
    series: [
      {
        name: '体重',
        type: 'line',
        smooth: true,
        yAxisIndex: 0,
        data: weightRows.map((r) => [r.date, r.value]),
        itemStyle: { color: '#4f46e5' },
      },
      {
        name: '周容量',
        type: 'bar',
        yAxisIndex: 1,
        data: volume.map((r) => [r.week_start, r.volume_tons]),
        itemStyle: { color: '#93c5fd' },
      },
    ],
  }
  // 双 y 轴：移动端 grid 右侧保留 40px 给第二根 y 轴刻度
  return mobile ? applyMobile(option, { grid: { right: 40 } }) : option
}
