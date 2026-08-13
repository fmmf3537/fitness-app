import { useEffect } from 'react'
import { useLocation } from 'react-router-dom'
import { Capacitor } from '@capacitor/core'
import { App } from '@capacitor/app'

// 五个底部 Tab 路由视为“根路由”：在根路由按返回键退到后台（不杀进程），而非继续 history.back()
const ROOT_PATHS = ['/', '/plans', '/ai-reports', '/trends', '/settings']

/**
 * 安卓返回键语义（仅原生平台生效，Web 环境安全空转）：
 * 1. 弹层优先：调用方传入的弹层（如汉堡菜单）打开 → 先关弹层；
 *    DOM 中存在打开的 BottomSheet（role="dialog"）→ 点击其关闭按钮；
 * 2. 非根路由 → history.back()；
 * 3. 根路由 → App.minimizeApp() 退到后台。
 *
 * @param {{ isOverlayOpen?: boolean, closeOverlay?: () => void }} options
 */
export default function useAndroidBackButton({ isOverlayOpen = false, closeOverlay } = {}) {
  const location = useLocation()

  useEffect(() => {
    if (!Capacitor.isNativePlatform()) return undefined

    const onBackButton = () => {
      if (isOverlayOpen && closeOverlay) {
        closeOverlay()
        return
      }
      const dialog = document.querySelector('[role="dialog"]')
      if (dialog) {
        const closeBtn = dialog.querySelector('[data-testid="bottom-sheet-close"]')
        if (closeBtn) {
          closeBtn.click()
          return
        }
      }
      if (!ROOT_PATHS.includes(location.pathname)) {
        window.history.back()
        return
      }
      App.minimizeApp()
    }

    let handle
    let cancelled = false
    App.addListener('backButton', onBackButton).then((h) => {
      if (cancelled) h.remove()
      else handle = h
    })
    return () => {
      cancelled = true
      if (handle) handle.remove()
    }
  }, [isOverlayOpen, closeOverlay, location.pathname])
}
