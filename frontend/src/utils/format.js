/** 成本展示：量级感知即可，分位以下无信息价值 */
export function fmtCost(v) {
  if (v == null) return ''
  if (v < 0.01) return '<¥0.01'
  return `¥${v.toFixed(2)}`
}
