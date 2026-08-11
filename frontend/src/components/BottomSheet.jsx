import { useEffect } from 'react'

/**
 * 共享底部抽屉（Bottom Sheet）。
 * - fixed 底部弹层：rounded-t-2xl、max-h-[85vh]、内容区 overflow-y-auto；
 * - 半透明背板，点背板关闭；右上角关闭按钮；打开时锁 body 滚动；
 * - title：顶部标题栏插槽；footer：底部操作区插槽（如上一篇/下一篇按钮）；
 * - 不做滑动手势（保持简单）。
 */
export default function BottomSheet({ open = true, onClose, title, footer, children }) {
  // 打开期间锁定 body 滚动，关闭/卸载时恢复
  useEffect(() => {
    if (!open) return undefined
    const original = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = original
    }
  }, [open])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-end">
      <div
        data-testid="bottom-sheet-backdrop"
        className="absolute inset-0 bg-black/50"
        onClick={onClose}
      />
      <div
        data-testid="bottom-sheet"
        role="dialog"
        aria-modal="true"
        className="relative flex max-h-[85vh] w-full flex-col rounded-t-2xl bg-white shadow-xl"
      >
        <div className="flex items-center justify-between gap-2 border-b border-gray-100 px-4 py-3">
          <div className="min-w-0 flex-1 truncate text-sm font-bold text-gray-900">{title}</div>
          <button
            type="button"
            data-testid="bottom-sheet-close"
            aria-label="关闭"
            onClick={onClose}
            className="shrink-0 rounded-md px-2 py-1 text-lg leading-none text-gray-500 hover:bg-gray-100 hover:text-gray-800"
          >
            ✕
          </button>
        </div>
        <div className="overflow-y-auto px-4 py-3">{children}</div>
        {footer && <div className="border-t border-gray-100 px-4 py-3">{footer}</div>}
      </div>
    </div>
  )
}
