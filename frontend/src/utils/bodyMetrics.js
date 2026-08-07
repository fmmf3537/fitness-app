// V1-7 身体数据页：指标定义与 ECharts option 构造纯函数（PRD US-12）。

/** 六类指标定义；syncable=false 的指标训记 API 不支持，仅本地保存。 */
export const METRIC_DEFS = [
  { type: 'height', label: '身高', unit: 'cm', syncable: false },
  { type: 'weight', label: '体重', unit: 'kg', syncable: true },
  { type: 'bodyfat', label: '体脂率', unit: '%', syncable: true },
  { type: 'bp_systolic', label: '收缩压', unit: 'mmHg', syncable: false },
  { type: 'bp_diastolic', label: '舒张压', unit: 'mmHg', syncable: false },
  { type: 'blood_glucose', label: '血糖', unit: 'mmol/L', syncable: false },
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
export function buildMetricTrendOption(records, label, unit) {
  const rows = Array.isArray(records) ? records : []
  return {
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
}

/** 体重曲线与周训练容量同屏对照（双 y 轴，时间轴对齐）。 */
export function buildWeightVolumeOption(weeklyVolume, weights) {
  const volume = Array.isArray(weeklyVolume) ? weeklyVolume : []
  const weightRows = Array.isArray(weights) ? weights : []
  return {
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
}
