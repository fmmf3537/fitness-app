import { afterEach, describe, expect, it, vi } from 'vitest'
import { uuidv4 } from '../uuid'

const V4_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/

describe('uuidv4', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('优先走 crypto.randomUUID（安全上下文）', () => {
    const spy = vi.fn(() => '11111111-1111-4111-8111-111111111111')
    vi.stubGlobal('crypto', { randomUUID: spy })
    expect(uuidv4()).toBe('11111111-1111-4111-8111-111111111111')
    expect(spy).toHaveBeenCalledTimes(1)
  })

  it('无 randomUUID 时用 crypto.getRandomValues 构造（版本位/变体位正确）', () => {
    // 真机 HTTP WebView 场景：getRandomValues 可用、randomUUID 不存在
    vi.stubGlobal('crypto', {
      getRandomValues: (arr) => {
        arr.fill(0)
        return arr
      },
    })
    const id = uuidv4()
    expect(id).toMatch(V4_RE)
  })

  it('getRandomValues 结果各不相同（非固定值）', () => {
    vi.stubGlobal('crypto', {
      getRandomValues: (arr) => {
        for (let i = 0; i < arr.length; i++) arr[i] = Math.floor(Math.random() * 256)
        return arr
      },
    })
    expect(uuidv4()).not.toBe(uuidv4())
  })

  it('crypto 完全不可用时退 Math.random 兜底，仍为 v4 格式', () => {
    vi.stubGlobal('crypto', undefined)
    expect(uuidv4()).toMatch(V4_RE)
  })

  it('默认环境输出符合 v4 格式', () => {
    expect(uuidv4()).toMatch(V4_RE)
  })
})
