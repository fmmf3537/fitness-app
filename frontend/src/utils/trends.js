// V2 趋势页 ECharts option 构造纯函数。
// 输入为 GET /api/stats/trends 响应的各个数组字段；所有函数对空输入返回合法 option。

import { CHART_PALETTE, mergeMobileOption } from './echartsMobile'

// UIX-11 图表皮肤：坐标/图例墨色 + 浅描边网格
const AXIS_LABEL = { color: '#9aa0b5' }
const AXIS_LINE = { lineStyle: { color: '#eceef5' } }
const SPLIT_LINE = { lineStyle: { color: '#eceef5', type: 'dashed' } }
const LEGEND_TEXT = { color: '#7b8099', fontSize: 11 }

/** 品牌紫柱状渐变（上浅下深） */
export function brandBarGradient() {
  return {
    type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
    colorStops: [
      { offset: 0, color: '#818cf8' },
      { offset: 1, color: '#a855f7' },
    ],
  }
}

function asArray(value) {
  return Array.isArray(value) ? value : []
}

const BASE_GRID = { left: 50, right: 20, top: 40, bottom: 30 }

/** YYYY-MM-DD（或以其为前缀）裁剪为 MM-DD，其他值原样返回（不误伤 value 轴数值）。 */
export function shortDateLabel(value) {
  return String(value).replace(/^\d{4}-(\d{2}-\d{2}).*$/, '$1')
}

/**
 * 移动端适配薄 wrapper：委托全站唯一 helper mergeMobileOption。
 * time 轴用 '{MM}-{dd}' 模板，category 等用 shortDateLabel；可通过 overrides.grid 覆盖局部值。
 */
export function applyMobile(option, overrides = {}) {
  const isTime = option?.xAxis?.type === 'time'
  return mergeMobileOption(option, {
    grid: overrides.grid,
    xAxisLabel: {
      rotate: 30,
      fontSize: 10,
      formatter: isTime ? '{MM}-{dd}' : shortDateLabel,
    },
  })
}

/** 每周总容量柱状图：x=week_start，y=volume_tons，tooltip 展示 sessions。 */
export function buildWeeklyVolumeOption(weeklyVolume, { mobile = false } = {}) {
  const rows = asArray(weeklyVolume)
  const option = {
    aria: { enabled: true },
    tooltip: {
      trigger: 'axis',
      formatter: (params) => {
        const p = Array.isArray(params) ? params[0] : params
        const row = rows[p?.dataIndex]
        return `${p?.name ?? ''}<br/>容量：${p?.value ?? 0} 吨<br/>训练次数：${row?.sessions ?? 0}`
      },
    },
    grid: BASE_GRID,
    xAxis: { type: 'category', name: '周', data: rows.map((r) => r.week_start), axisLabel: AXIS_LABEL, axisLine: AXIS_LINE },
    yAxis: { type: 'value', name: '吨', axisLabel: AXIS_LABEL, splitLine: SPLIT_LINE },
    series: [
      {
        name: '总容量',
        type: 'bar',
        barWidth: '55%',
        data: rows.map((r) => r.volume_tons),
        itemStyle: { color: brandBarGradient(), borderRadius: [6, 6, 2, 2] },
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
    aria: { enabled: true },
    color: CHART_PALETTE,
    tooltip: { trigger: 'axis' },
    legend: { top: 0, textStyle: LEGEND_TEXT },
    grid: BASE_GRID,
    xAxis: { type: 'category', name: '周', data: weeks, axisLabel: AXIS_LABEL, axisLine: AXIS_LINE },
    yAxis: { type: 'value', name: '次数', axisLabel: AXIS_LABEL, splitLine: SPLIT_LINE },
    series: parts.map((part) => ({
      name: part,
      type: 'bar',
      stack: 'parts',
      barWidth: '55%',
      data: rows.map((r) => r.parts?.[part] ?? 0),
      itemStyle: { borderRadius: 3 },
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
    aria: { enabled: true },
    tooltip: { trigger: 'axis' },
    legend: { top: 0, textStyle: LEGEND_TEXT },
    grid: BASE_GRID,
    xAxis: { type: 'category', name: '日期', data: dates, axisLabel: AXIS_LABEL, axisLine: AXIS_LINE },
    yAxis: { type: 'value', axisLabel: AXIS_LABEL, splitLine: SPLIT_LINE },
    series: [
      {
        name: '体重',
        type: 'line',
        smooth: true,
        connectNulls: true,
        symbolSize: 7,
        lineStyle: { width: 3 },
        data: toSeries(weight),
        itemStyle: { color: CHART_PALETTE[0] },
      },
      {
        name: '体脂率',
        type: 'line',
        smooth: true,
        connectNulls: true,
        symbolSize: 7,
        lineStyle: { width: 3 },
        data: toSeries(bodyfat),
        itemStyle: { color: CHART_PALETTE[1] },
      },
    ],
  }
  return mobile ? applyMobile(option) : option
}

/** 睡眠-容量散点图：x=sleep_hours，y=volume_tons。 */
export function buildSleepVolumeOption(sleepVolume, { mobile = false } = {}) {
  const rows = asArray(sleepVolume)
  const option = {
    aria: { enabled: true },
    tooltip: {
      trigger: 'item',
      formatter: (p) => `睡眠：${p?.value?.[0] ?? '-'} 小时<br/>容量：${p?.value?.[1] ?? '-'} 吨`,
    },
    grid: BASE_GRID,
    xAxis: { type: 'value', name: '睡眠（小时）', axisLabel: AXIS_LABEL, splitLine: SPLIT_LINE },
    yAxis: { type: 'value', name: '容量（吨）', axisLabel: AXIS_LABEL, splitLine: SPLIT_LINE },
    series: [
      {
        name: '睡眠-容量',
        type: 'scatter',
        symbolSize: 16,
        data: rows.map((r) => [r.sleep_hours, r.volume_tons]),
        itemStyle: { color: 'rgba(139,92,246,.75)' },
      },
    ],
  }
  return mobile ? applyMobile(option) : option
}
