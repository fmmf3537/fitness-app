import { act, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import useIsMobile from '../useIsMobile'
import { installMatchMedia } from '../../test/mockMatchMedia'

describe('useIsMobile', () => {
  afterEach(() => {
    installMatchMedia(false)
  })

  it('桌面断点（≥768px）返回 false', () => {
    installMatchMedia(false)
    const { result } = renderHook(() => useIsMobile())
    expect(result.current).toBe(false)
  })

  it('移动断点（<768px）返回 true', () => {
    installMatchMedia(true)
    const { result } = renderHook(() => useIsMobile())
    expect(result.current).toBe(true)
  })

  it('断点变化时监听并更新返回值', () => {
    const ctl = installMatchMedia(false)
    const { result } = renderHook(() => useIsMobile())
    expect(result.current).toBe(false)

    act(() => ctl.setMatches(true))
    expect(result.current).toBe(true)

    act(() => ctl.setMatches(false))
    expect(result.current).toBe(false)
  })
})
