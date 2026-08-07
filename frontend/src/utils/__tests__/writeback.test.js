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

describe('buildChanges', () => {
  it('把 suggested.rpe 应用到同名动作的每一组（字符串化）', () => {
    const suggestion = {
      movement: '宽距高位下拉',
      suggested: { rpe: 8 },
    }
    const changes = buildChanges(suggestion, MOVEMENTS)
    const sets = changes.movements[0].sets
    expect(sets[0].rpe).toBe('8')
    expect(sets[1].rpe).toBe('8')
    // 其它字段与原值保留
    expect(sets[0].weight).toBe('50')
    expect(sets[0].done).toBe(true)
    // 未匹配的动作不受影响
    expect(changes.movements[1]).toEqual(MOVEMENTS[1])
  })

  it('suggested.weight/reps 覆盖每组重量与次数', () => {
    const suggestion = {
      movement: '杠铃划船',
      suggested: { weight: 62.5, reps: 8 },
    }
    const changes = buildChanges(suggestion, MOVEMENTS)
    expect(changes.movements[1].sets[0].weight).toBe('62.5')
    expect(changes.movements[1].sets[0].reps).toBe('8')
  })

  it('suggested.difficulty 写在动作对象上', () => {
    const suggestion = { movement: '杠铃划船', suggested: { difficulty: 'hard' } }
    const changes = buildChanges(suggestion, MOVEMENTS)
    expect(changes.movements[1].difficulty).toBe('hard')
  })

  it('suggested.sets 调整组数：补齐复制最后一组，超出则截断', () => {
    const grow = buildChanges(
      { movement: '杠铃划船', suggested: { sets: 3 } },
      MOVEMENTS,
    )
    expect(grow.movements[1].sets).toHaveLength(3)
    expect(grow.movements[1].sets[2]).toEqual(MOVEMENTS[1].sets[0])

    const shrink = buildChanges(
      { movement: '宽距高位下拉', suggested: { sets: 1 } },
      MOVEMENTS,
    )
    expect(shrink.movements[0].sets).toHaveLength(1)
  })

  it('不修改传入的原始 movements（纯函数）', () => {
    buildChanges({ movement: '杠铃划船', suggested: { rpe: 9 } }, MOVEMENTS)
    expect(MOVEMENTS[1].sets[0].rpe).toBeUndefined()
  })

  it('找不到同名动作时返回 null', () => {
    const changes = buildChanges({ movement: '不存在动作', suggested: { rpe: 8 } }, MOVEMENTS)
    expect(changes).toBeNull()
  })
})
