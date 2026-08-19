// V3-10：AI 报告内嵌 ECharts 的移动端适配。
// LLM 生成的 option 按桌面宽度假设，窄屏下标题/Y 轴名/柱顶标签/图例相互重叠；
// 此处仅在渲染层对解析后的 option 做深合并覆盖（不动 LLM 原文），与 V3-3 applyMobile 同思路。

const MOBILE_GRID = { top: 56, left: 8, right: 8, bottom: 44, containLabel: true }

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

function mergeXAxis(xAxis) {
  const mergeOne = (axis) => {
    const a = asObject(axis)
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
    return { ...item, label: { ...asObject(item.label), fontSize: 9 } }
  })
}

/**
 * 移动端合并：title 居中缩小、grid 紧凑、类目轴标签缩小旋转、y 轴名缩小、
 * 图例底部滚动、系列标签缩小。输入 option 不被修改；缺省键安全新建。
 */
export function mergeMobileOption(option) {
  const src = asObject(option)
  const next = {
    ...src,
    title: mergeTitle(src.title),
    grid: { ...asObject(src.grid), ...MOBILE_GRID },
    legend: mergeLegend(src.legend),
  }
  if (src.xAxis !== undefined) next.xAxis = mergeXAxis(src.xAxis)
  if (src.yAxis !== undefined) next.yAxis = mergeYAxis(src.yAxis)
  if (src.series !== undefined) next.series = mergeSeries(src.series)
  return next
}
