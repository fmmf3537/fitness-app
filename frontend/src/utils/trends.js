// V2 趋势页 ECharts option 构造纯函数。
// 输入为 GET /api/stats/trends 响应的各个数组字段；所有函数对空输入返回合法 option。

function asArray(value) {
  return Array.isArray(value) ? value : []
}

const BASE_GRID = { left: 50, right: 20, top: 40, bottom: 30 }
// 移动端 grid：top 加大容纳换行/滚动图例，bottom 加大容纳旋转后的 X 轴标签
const MOBILE_GRID = { left: 40, right: 12, top: 56, bottom: 48 }

/** YYYY-MM-DD（或以其为前缀）裁剪为 MM-DD，其他值原样返回（不误伤 value 轴数值）。 */
export function shortDateLabel(value) {
  return String(value).replace(/^\d{4}-(\d{2}-\d{2}).*$/, '$1')
}

/**
 * 移动端适配共享 helper：旋转缩小 X 轴标签、可滚动小图例、紧凑 grid、去掉 y 轴名称防叠字。
 * time 轴改用 '{MM}-{dd}' 模板（函数 formatter 会拿到毫秒时间戳，无法裁剪字符串）。
 * 可通过 overrides.grid 覆盖 grid 局部值（如双 y 轴图需保留右侧宽度）。
 */
export function applyMobile(option, overrides = {}) {
  const next = { ...option }
  next.grid = { ...MOBILE_GRID, ...overrides.grid }
  next.xAxis = {
    ...next.xAxis,
    axisLabel:
      next.xAxis?.type === 'time'
        ? { rotate: 45, fontSize: 10, formatter: '{MM}-{dd}' }
        : { rotate: 45, fontSize: 10, formatter: shortDateLabel },
  }
  const dropName = (axis) => {
    const copy = { ...axis }
    delete copy.name
    return copy
  }
  if (next.yAxis) {
    next.yAxis = Array.isArray(next.yAxis) ? next.yAxis.map(dropName) : dropName(next.yAxis)
  }
  if (next.legend) {
    next.legend = {
      ...next.legend,
      type: 'scroll',
      textStyle: { fontSize: 10 },
      itemWidth: 14,
      itemGap: 8,
    }
  }
  return next
}

/** 每周总容量柱状图：x=week_start，y=volume_tons，tooltip 展示 sessions。 */
export function buildWeeklyVolumeOption(weeklyVolume, { mobile = false } = {}) {
  const rows = asArray(weeklyVolume)
  const option = {
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
  return mobile ? applyMobile(option) : option
}

/** 各部位训练频次堆叠柱状图：x=week_start，部位集合为所有周并集（排序稳定）。 */
export function buildBodyPartOption(bodyPartFrequency, { mobile = false } = {}) {
  const rows = asArray(bodyPartFrequency)
  const weeks = rows.map((r) => r.week_start)
  const parts = [...new Set(rows.flatMap((r) => Object.keys(r.parts || {})))].sort()
  const option = {
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
  return mobile ? applyMobile(option) : option
}

/** 体重/体脂折线图：x 为两类日期并集（升序），某类无数据时该 series 为空数组。 */
export function buildBodyMetricOption(bodyMetrics, { mobile = false } = {}) {
  const metrics = bodyMetrics || {}
  const weight = asArray(metrics.weight)
  const bodyfat = asArray(metrics.bodyfat)
  const dates = [...new Set([...weight, ...bodyfat].map((r) => r.date))].sort()
  const toSeries = (rows) => {
    if (rows.length === 0) return []
    const byDate = new Map(rows.map((r) => [r.date, r.value]))
    return dates.map((d) => byDate.get(d) ?? null)
  }
  const option = {
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
  return mobile ? applyMobile(option) : option
}

/** 睡眠-容量散点图：x=sleep_hours，y=volume_tons。 */
export function buildSleepVolumeOption(sleepVolume, { mobile = false } = {}) {
  const rows = asArray(sleepVolume)
  const option = {
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
  return mobile ? applyMobile(option) : option
}
