// V1-5 写回变更构造：把 AI 建议（next_advice_v1 suggestion）应用到 workout 动作列表，
// 生成提交给 /api/writeback/preview 的 changes。
//
// V1-5-FIX：改为补丁式输出——只包含目标动作与显式变更的组/字段；
// 服务端 build_merged_train 做动作/组/字段三级深度合并，未指定部分全部保留原值。
//
// 应用规则：
// - 按 name 匹配动作，找不到返回 null；
// - suggested.difficulty 写在动作补丁上（easy/normal/hard）；
// - suggested.weight / reps / rpe 只写入补丁（数值字符串化，对齐训记格式），
//   未给的字段不出现在补丁中；
// - suggested.sets 调整组数：超出原组数的新组以最后一组为底叠加建议值；
//   少于原组数的多余组用 { index, _delete: true } 显式删除；
// - 纯函数，不修改入参。

/**
 * @returns {{movements: Array} | null} 找不到同名动作时返回 null。
 */
export function buildChanges(suggestion, movements) {
  if (!suggestion || !Array.isArray(movements)) return null
  const target = (suggestion.movement || '').trim()
  const original = movements.find((m) => (m?.name || '').trim() === target)
  if (!original) return null

  const suggested = suggestion.suggested || {}
  const patch = { name: original.name }
  if (suggested.difficulty != null) patch.difficulty = suggested.difficulty

  const origSets = Array.isArray(original.sets) ? original.sets : []
  const fieldKeys = ['weight', 'reps', 'rpe'].filter((k) => suggested[k] != null)
  const n =
    suggested.sets != null ? Math.max(0, Number(suggested.sets) || 0) : origSets.length

  const setPatches = []
  for (let i = 0; i < n; i++) {
    if (i < origSets.length) {
      if (fieldKeys.length === 0) continue // 无字段变更的组不进补丁
      const sp = { index: i + 1 }
      for (const k of fieldKeys) sp[k] = String(suggested[k])
      setPatches.push(sp)
    } else {
      // 新增组：以最后一组为底（保留 unit/done 等），再叠加建议值
      const sp = { ...(origSets[origSets.length - 1] || {}), index: i + 1 }
      for (const k of fieldKeys) sp[k] = String(suggested[k])
      setPatches.push(sp)
    }
  }
  for (let i = n; i < origSets.length; i++) {
    setPatches.push({ index: i + 1, _delete: true }) // 显式删除多余组
  }
  if (setPatches.length > 0) patch.sets = setPatches

  return { movements: [patch] }
}
