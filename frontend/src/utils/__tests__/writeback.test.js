import { describe, expect, it } from 'vitest'
import { buildChanges } from '../writeback'

const MOVEMENTS = [
  {
    name: '宽距高位下拉',
    sets: [
      { weight: '50', unit: 'kg', reps: '10', done: true },
      { weight: '50', unit: 'kg', reps: '8', done: true },
    ],
  },
  { name: '杠铃划船', sets: [{ weight: '60', unit: 'kg', reps: '10', done: true }] },
]

describe('buildChanges（V1-5-FIX 补丁式：只输出目标动作与显式变更的组/字段）', () => {
  it('只输出目标动作补丁，未匹配动作不出现（服务端深合并保留）', () => {
    const changes = buildChanges(
      { movement: '宽距高位下拉', suggested: { rpe: 8 } },
      MOVEMENTS,
    )
    expect(changes.movements).toHaveLength(1)
    expect(changes.movements[0].name).toBe('宽距高位下拉')
  })

  it('把 suggested.rpe 应用到同名动作的每一组（字符串化），未给字段不出现在补丁里', () => {
    const changes = buildChanges(
      { movement: '宽距高位下拉', suggested: { rpe: 8 } },
      MOVEMENTS,
    )
    const sets = changes.movements[0].sets
    expect(sets).toEqual([
      { index: 1, rpe: '8' },
      { index: 2, rpe: '8' },
    ])
  })

  it('suggested.weight/reps 只写入补丁字段', () => {
    const changes = buildChanges(
      { movement: '杠铃划船', suggested: { weight: 62.5, reps: 8 } },
      MOVEMENTS,
    )
    expect(changes.movements[0].sets).toEqual([{ index: 1, weight: '62.5', reps: '8' }])
  })

  it('suggested.difficulty 写在动作补丁上，无组变更时不输出 sets', () => {
    const changes = buildChanges(
      { movement: '杠铃划船', suggested: { difficulty: 'hard' } },
      MOVEMENTS,
    )
    expect(changes.movements[0].difficulty).toBe('hard')
    expect(changes.movements[0].sets).toBeUndefined()
  })

  it('suggested.sets 增加组数：新组以最后一组为底并叠加建议值', () => {
    const grow = buildChanges(
      { movement: '杠铃划船', suggested: { sets: 3, rpe: 8 } },
      MOVEMENTS,
    )
    expect(grow.movements[0].sets).toEqual([
      { index: 1, rpe: '8' },
      { ...MOVEMENTS[1].sets[0], index: 2, rpe: '8' },
      { ...MOVEMENTS[1].sets[0], index: 3, rpe: '8' },
    ])
  })

  it('suggested.sets 减少组数：多余组用 _delete 显式删除', () => {
    const shrink = buildChanges(
      { movement: '宽距高位下拉', suggested: { sets: 1 } },
      MOVEMENTS,
    )
    expect(shrink.movements[0].sets).toEqual([{ index: 2, _delete: true }])
  })

  it('不修改传入的原始 movements（纯函数）', () => {
    buildChanges({ movement: '杠铃划船', suggested: { rpe: 9 } }, MOVEMENTS)
    expect(MOVEMENTS[1].sets[0].rpe).toBeUndefined()
    expect(MOVEMENTS[1].sets[0].index).toBeUndefined()
  })

  it('找不到同名动作时返回 null', () => {
    const changes = buildChanges({ movement: '不存在动作', suggested: { rpe: 8 } }, MOVEMENTS)
    expect(changes).toBeNull()
  })
})
