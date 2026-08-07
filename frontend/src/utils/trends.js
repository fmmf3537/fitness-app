// V2 趋势页 ECharts option 构造纯函数。
// 输入为 GET /api/stats/trends 响应的各个数组字段；所有函数对空输入返回合法 option。

function asArray(value) {
  return Array.isArray(value) ? value : []
}

const BASE_GRID = { left: 50, right: 20, top: 40, bottom: 30 }

/** 每周总容量柱状图：x=week_start，y=volume_tons，tooltip 展示 sessions。 */
export function buildWeeklyVolumeOption(weeklyVolume) {
  const rows = asArray(weeklyVolume)
  return {
    tooltip: {
      trigger: 'axis',
      formatter: (params) => {
        const p = Array.isArray(params) ? params[0] : params
        const row = rows[p?.dataIndex]
        return `${p?.name ?? ''}<br/>容量：${p?.value ?? 0} 吨<br/>训练次数：${row?.sessions ?? 0}`
      },
    },
    grid: BASE_GRID,
    xAxis: { type: 'category', name: '周', data: rows.map((r) => r.week_start) },
    yAxis: { type: 'value', name: '吨' },
    series: [
      {
        name: '总容量',
        type: 'bar',
        data: rows.map((r) => r.volume_tons),
        itemStyle: { color: '#4f46e5' },
      },
    ],
  }
}

/** 各部位训练频次堆叠柱状图：x=week_start，部位集合为所有周并集（排序稳定）。 */
export function buildBodyPartOption(bodyPartFrequency) {
  const rows = asArray(bodyPartFrequency)
  const weeks = rows.map((r) => r.week_start)
  const parts = [...new Set(rows.flatMap((r) => Object.keys(r.parts || {})))].sort()
  return {
    tooltip: { trigger: 'axis' },
    legend: { top: 0 },
    grid: BASE_GRID,
    xAxis: { type: 'category', name: '周', data: weeks },
    yAxis: { type: 'value', name: '次数' },
    series: parts.map((part) => ({
      name: part,
      type: 'bar',
      stack: 'parts',
      data: rows.map((r) => r.parts?.[part] ?? 0),
    })),
  }
}

/** 体重/体脂折线图：x 为两类日期并集（升序），某类无数据时该 series 为空数组。 */
export function buildBodyMetricOption(bodyMetrics) {
  const metrics = bodyMetrics || {}
  const weight = asArray(metrics.weight)
  const bodyfat = asArray(metrics.bodyfat)
  const dates = [...new Set([...weight, ...bodyfat].map((r) => r.date))].sort()
  const toSeries = (rows) => {
    if (rows.length === 0) return []
    const byDate = new Map(rows.map((r) => [r.date, r.value]))
    return dates.map((d) => byDate.get(d) ?? null)
  }
  return {
    tooltip: { trigger: 'axis' },
    legend: { top: 0 },
    grid: BASE_GRID,
    xAxis: { type: 'category', name: '日期', data: dates },
    yAxis: { type: 'value' },
    series: [
      { name: '体重', type: 'line', smooth: true, connectNulls: true, data: toSeries(weight) },
      { name: '体脂率', type: 'line', smooth: true, connectNulls: true, data: toSeries(bodyfat) },
    ],
  }
}

/** 睡眠-容量散点图：x=sleep_hours，y=volume_tons。 */
export function buildSleepVolumeOption(sleepVolume) {
  const rows = asArray(sleepVolume)
  return {
    tooltip: {
      trigger: 'item',
      formatter: (p) => `睡眠：${p?.value?.[0] ?? '-'} 小时<br/>容量：${p?.value?.[1] ?? '-'} 吨`,
    },
    grid: BASE_GRID,
    xAxis: { type: 'value', name: '睡眠（小时）' },
    yAxis: { type: 'value', name: '容量（吨）' },
    series: [
      {
        name: '睡眠-容量',
        type: 'scatter',
        symbolSize: 12,
        data: rows.map((r) => [r.sleep_hours, r.volume_tons]),
        itemStyle: { color: '#0ea5e9' },
      },
    ],
  }
}
