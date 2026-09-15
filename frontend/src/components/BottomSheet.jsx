import { useId, useRef } from 'react'
import useModalAccessibility from '../hooks/useModalAccessibility'

/**
 * 共享底部抽屉（Bottom Sheet）。
 * - fixed 底部弹层：rounded-t-2xl、max-h vh+dvh 兜底链（移动端 vh 含浏览器工具栏）、
 *   容器 min-w-0 防内容撑宽、内容区 overflow-y-auto + overflow-x-hidden；
 * - 半透明背板，点背板关闭；右上角关闭按钮；打开时锁 body 滚动；
 * - title：顶部标题栏插槽；footer：底部操作区插槽（如上一篇/下一篇按钮）；
 * - 不做滑动手势（保持简单）。
 */
export default function BottomSheet({ open = true, onClose, title, footer, children }) {
  const sheetRef = useRef(null)
  const closeRef = useRef(null)
  const titleId = useId()
  useModalAccessibility({ open, containerRef: sheetRef, initialFocusRef: closeRef, onClose })

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-end">
      <div
        data-testid="bottom-sheet-backdrop"
        className="absolute inset-0 bg-black/50"
        onClick={onClose}
      />
      <div
        ref={sheetRef}
        data-testid="bottom-sheet"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className="relative flex max-h-[85vh] max-h-[85dvh] w-full min-w-0 flex-col rounded-t-2xl bg-white dark:bg-gray-900 shadow-xl"
      >
        <div className="flex items-center justify-between gap-2 border-b border-gray-100 dark:border-gray-800 px-4 py-3">
          <div id={titleId} className="min-w-0 flex-1 truncate text-sm font-bold text-gray-900 dark:text-gray-100">{title}</div>
          <button
            ref={closeRef}
            type="button"
            data-testid="bottom-sheet-close"
            aria-label="关闭"
            data-dialog-close
            onClick={onClose}
            className="min-h-[44px] min-w-[44px] shrink-0 rounded-md px-2 py-1 text-lg leading-none text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 hover:text-gray-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2"
          >
            ✕
          </button>
        </div>
        <div data-testid="bottom-sheet-content" className="min-w-0 overflow-x-hidden overflow-y-auto px-4 py-3">
          {children}
        </div>
        {footer && (
          <div data-testid="bottom-sheet-footer" className="shrink-0 border-t border-gray-100 dark:border-gray-800 px-4 pt-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]">
            {footer}
          </div>
        )}
      </div>
    </div>
  )
}
