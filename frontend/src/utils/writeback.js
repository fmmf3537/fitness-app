// V1-5 写回变更构造：把 AI 建议（next_advice_v1 suggestion）应用到 workout 动作列表，
// 生成提交给 /api/writeback/preview 的 changes（服务端再合并保留元数据）。
//
// 应用规则（假设，V1-5 落地）：
// - suggested.weight / reps / rpe 覆盖同名动作的每一组（数值字符串化，对齐训记格式）；
// - suggested.difficulty 写在动作对象上（easy/normal/hard）；
// - suggested.sets 调整组数：不足复制最后一组补齐，超出截断；
// - 其余字段（unit/done/time 等）与原动作一律保留；不修改入参（纯函数）。

/**
 * @returns {{movements: Array} | null} 找不到同名动作时返回 null。
 */
export function buildChanges(suggestion, movements) {
  if (!suggestion || !Array.isArray(movements)) return null
  const target = (suggestion.movement || '').trim()
  const index = movements.findIndex((m) => (m?.name || '').trim() === target)
  if (index < 0) return null

  const suggested = suggestion.suggested || {}
  const cloned = movements.map((m) => ({
    ...m,
    sets: (m.sets || []).map((s) => ({ ...s })),
  }))
  const mv = cloned[index]

  if (suggested.difficulty != null) mv.difficulty = suggested.difficulty

  if (suggested.sets != null) {
    const n = Math.max(0, Number(suggested.sets) || 0)
    let sets = mv.sets
    while (sets.length < n && sets.length > 0) sets.push({ ...sets[sets.length - 1] })
    while (sets.length < n) sets.push({})
    mv.sets = sets.slice(0, n)
  }

  for (const s of mv.sets) {
    if (suggested.weight != null) s.weight = String(suggested.weight)
    if (suggested.reps != null) s.reps = String(suggested.reps)
    if (suggested.rpe != null) s.rpe = String(suggested.rpe)
  }

  return { movements: cloned }
}
