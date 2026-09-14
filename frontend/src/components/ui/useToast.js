import { createContext, useContext } from 'react'

/**
 * Toast 上下文与 hook（独立文件：Toast.jsx 只导出组件，保证 fast refresh 生效）。
 * UIX-01 决策点 3：Toast 用 Provider+hook 而非全局事件。
 */
export const ToastContext = createContext(null)

export function useToast() {
  const ctx = useContext(ToastContext)
  if (!ctx) {
    throw new Error('useToast must be used within ToastProvider')
  }
  return ctx
}
