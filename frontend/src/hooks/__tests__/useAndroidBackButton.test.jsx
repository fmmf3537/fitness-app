import { render } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { Capacitor } from '@capacitor/core'
import { App } from '@capacitor/app'
import useAndroidBackButton from '../useAndroidBackButton'

vi.mock('@capacitor/core', () => ({
  Capacitor: { isNativePlatform: vi.fn(() => true) },
}))
vi.mock('@capacitor/app', () => ({
  App: {
    addListener: vi.fn(),
    minimizeApp: vi.fn(),
  },
}))

function Probe(props) {
  useAndroidBackButton(props)
  return null
}

function renderProbe(initialPath = '/', props = {}) {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Probe {...props} />
    </MemoryRouter>,
  )
}

describe('useAndroidBackButton 返回键语义', () => {
  let backHandler
  let backSpy

  beforeEach(() => {
    vi.clearAllMocks()
    Capacitor.isNativePlatform.mockReturnValue(true)
    App.addListener.mockImplementation((_event, cb) => {
      backHandler = cb
      return Promise.resolve({ remove: vi.fn() })
    })
    backSpy = vi.spyOn(window.history, 'back').mockImplementation(() => {})
  })

  afterEach(() => {
    backSpy.mockRestore()
  })

  it('Web 环境安全空转：不注册任何监听', () => {
    Capacitor.isNativePlatform.mockReturnValue(false)
    renderProbe('/')
    expect(App.addListener).not.toHaveBeenCalled()
  })

  it('原生环境注册 backButton 监听，卸载时移除', async () => {
    const remove = vi.fn()
    App.addListener.mockImplementation(() => Promise.resolve({ remove }))
    const { unmount } = renderProbe('/')
    expect(App.addListener).toHaveBeenCalledWith('backButton', expect.any(Function))
    unmount()
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(remove).toHaveBeenCalled()
  })

  it('分支一：传入的弹层打开时优先关闭弹层，不返回不最小化', () => {
    const closeOverlay = vi.fn()
    renderProbe('/workouts/1', { isOverlayOpen: true, closeOverlay })
    backHandler()
    expect(closeOverlay).toHaveBeenCalledTimes(1)
    expect(backSpy).not.toHaveBeenCalled()
    expect(App.minimizeApp).not.toHaveBeenCalled()
  })

  it('分支一扩展：DOM 中存在 dialog 弹层（BottomSheet）时点击其关闭按钮', () => {
    const onClose = vi.fn()
    render(
      <MemoryRouter initialEntries={['/reviews']}>
        <Probe />
        <div role="dialog">
          <button data-testid="bottom-sheet-close" onClick={onClose}>
            ✕
          </button>
        </div>
      </MemoryRouter>,
    )
    backHandler()
    expect(onClose).toHaveBeenCalledTimes(1)
    expect(backSpy).not.toHaveBeenCalled()
    expect(App.minimizeApp).not.toHaveBeenCalled()
  })

  it('分支二：非根路由执行 history.back()', () => {
    renderProbe('/workouts/123')
    backHandler()
    expect(backSpy).toHaveBeenCalledTimes(1)
    expect(App.minimizeApp).not.toHaveBeenCalled()
  })

  it('分支三：五个 Tab 根路由均最小化 App（退后台不杀进程）', () => {
    for (const path of ['/', '/plans', '/ai-reports', '/trends', '/settings']) {
      vi.clearAllMocks()
      render(
        <MemoryRouter initialEntries={[path]}>
          <Probe />
        </MemoryRouter>,
      )
      backHandler()
      expect(App.minimizeApp).toHaveBeenCalledTimes(1)
      expect(backSpy).not.toHaveBeenCalled()
    }
  })
})
