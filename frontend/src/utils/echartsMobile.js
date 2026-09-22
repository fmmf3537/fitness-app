// 全站唯一移动端图表适配入口：对解析后的 option 做深合并覆盖（不动原文）。
// 趋势页 applyMobile 退化为本 helper 的特化 wrapper（time/category formatter）。

const MOBILE_GRID = { top: 56, left: 8, right: 8, bottom: 44, containLabel: true }

/** 图表统一色板（UIX-11 品牌紫体系，定序循环）：主系列 / 次系列 / 对比 / 正向 / 辅助 */
export const CHART_PALETTE = ['#8b5cf6', '#6366f1', '#f59e0b', '#10b981', '#0ea5e9']

function asObject(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {}
}

function mergeTitle(title) {
  const t = asObject(title)
  return {
    ...t,
    left: 'center',
    top: 0,
    textStyle: { ...asObject(t.textStyle), fontSize: 13 },
  }
}

function mergeLegend(legend) {
  const l = asObject(legend)
  const next = {
    ...l,
    type: 'scroll',
    bottom: 0,
    textStyle: { ...asObject(l.textStyle), fontSize: 10 },
  }
  // top 与 bottom 同时存在时 ECharts 以 top 为准，移除原 top 才能让图例落到底部
  delete next.top
  return next
}

function mergeXAxis(xAxis, xAxisLabelOverride) {
  const mergeOne = (axis) => {
    const a = asObject(axis)
    if (xAxisLabelOverride !== undefined) {
      return { ...a, axisLabel: xAxisLabelOverride }
    }
    const isCategory = !a.type || a.type === 'category'
    return {
      ...a,
      axisLabel: {
        ...asObject(a.axisLabel),
        fontSize: 10,
        ...(isCategory ? { rotate: 30 } : {}),
      },
    }
  }
  return Array.isArray(xAxis) ? xAxis.map(mergeOne) : mergeOne(xAxis)
}

function mergeYAxis(yAxis) {
  const mergeOne = (axis) => {
    const a = asObject(axis)
    // name 保留（仅缩小 nameTextStyle），避免丢失单位信息
    return { ...a, nameTextStyle: { ...asObject(a.nameTextStyle), fontSize: 10 } }
  }
  return Array.isArray(yAxis) ? yAxis.map(mergeOne) : mergeOne(yAxis)
}

function mergeSeries(series) {
  if (!Array.isArray(series)) return series
  return series.map((s) => {
    const item = asObject(s)
    return { ...item, label: { ...asObject(item.label), fontSize: 10 } }
  })
}

/**
 * 移动端合并：title 居中缩小、grid 紧凑 + containLabel、类目轴标签缩小旋转 30°、
 * y 轴名保留并缩小、图例底部滚动、系列标签字号 10。
 * overrides.grid 存在时深合并覆盖 MOBILE_GRID 对应键；
 * overrides.xAxisLabel 存在时整体替换 xAxis.axisLabel（兼容 time 轴 formatter 特化）。
 * 输入 option 不被修改；缺省键安全新建。
 */
export function mergeMobileOption(option, overrides = {}) {
  const src = asObject(option)
  const ov = asObject(overrides)
  const next = {
    ...src,
    title: mergeTitle(src.title),
    grid: { ...asObject(src.grid), ...MOBILE_GRID, ...asObject(ov.grid) },
    legend: mergeLegend(src.legend),
  }
  if (src.xAxis !== undefined) next.xAxis = mergeXAxis(src.xAxis, ov.xAxisLabel)
  if (src.yAxis !== undefined) next.yAxis = mergeYAxis(src.yAxis)
  if (src.series !== undefined) next.series = mergeSeries(src.series)
  return next
}
