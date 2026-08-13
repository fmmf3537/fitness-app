import { render } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { Capacitor } from '@capacitor/core'
import { StatusBar, Style } from '@capacitor/status-bar'
import useNativeStatusBar from '../useNativeStatusBar'

vi.mock('@capacitor/core', () => ({
  Capacitor: { isNativePlatform: vi.fn(() => true) },
}))
vi.mock('@capacitor/status-bar', () => ({
  StatusBar: {
    setStyle: vi.fn(() => Promise.resolve()),
    setOverlaysWebView: vi.fn(() => Promise.resolve()),
  },
  Style: { Dark: 'DARK', Light: 'LIGHT' },
}))

function Probe() {
  useNativeStatusBar()
  return null
}

describe('useNativeStatusBar 状态栏', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    Capacitor.isNativePlatform.mockReturnValue(true)
  })

  it('原生环境：深色文字 + 沉浸式边到边（overlay webview）', () => {
    render(<Probe />)
    expect(StatusBar.setStyle).toHaveBeenCalledWith({ style: Style.Dark })
    expect(StatusBar.setOverlaysWebView).toHaveBeenCalledWith({ overlay: true })
  })

  it('Web 环境安全空转', () => {
    Capacitor.isNativePlatform.mockReturnValue(false)
    render(<Probe />)
    expect(StatusBar.setStyle).not.toHaveBeenCalled()
    expect(StatusBar.setOverlaysWebView).not.toHaveBeenCalled()
  })
})
