import { useEffect } from 'react'
import { Capacitor } from '@capacitor/core'
import { StatusBar, Style } from '@capacitor/status-bar'

/**
 * 原生端状态栏设置（Web 环境安全空转）：
 * - Style.Dark：深色文字/图标，配浅色 UI；
 * - overlaysWebView(true)：沉浸式边到边，状态栏区域由页面内容延伸
 *   （配合 header 的 pt-[env(safe-area-inset-top)] 防内容被遮挡）。
 */
export default function useNativeStatusBar() {
  useEffect(() => {
    if (!Capacitor.isNativePlatform()) return
    StatusBar.setStyle({ style: Style.Dark }).catch(() => {})
    StatusBar.setOverlaysWebView({ overlay: true }).catch(() => {})
  }, [])
}
