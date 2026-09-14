import { useEffect, useRef } from 'react'
import Button from './Button'

/**
 * 居中确认弹窗，替换全站 6 处 window.confirm。
 * 参照 BottomSheet：锁 body 滚动、背板关闭；布局为居中模态。
 */
export default function ConfirmDialog({
  open,
  title,
  description,
  confirmText = '确认',
  cancelText = '取消',
  danger = false,
  onConfirm,
  onCancel,
}) {
  const cancelRef = useRef(null)

  // 打开期间锁定 body 滚动，关闭/卸载时恢复
  useEffect(() => {
    if (!open) return undefined
    const original = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = original
    }
  }, [open])

  // Esc 关闭
  useEffect(() => {
    if (!open) return undefined
    const onKey = (e) => {
      if (e.key === 'Escape') onCancel?.()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onCancel])

  // 打开时焦点落到取消按钮
  useEffect(() => {
    if (!open) return
    cancelRef.current?.focus()
  }, [open])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div
        data-testid="confirm-dialog-backdrop"
        className="absolute inset-0 bg-black/50"
        onClick={onCancel}
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="confirm-dialog-title"
        data-testid="confirm-dialog"
        className="relative w-full max-w-sm rounded-xl bg-white p-5 shadow-xl mb-[env(safe-area-inset-bottom)]"
      >
        <h2 id="confirm-dialog-title" className="text-base font-semibold text-gray-900">
          {title}
        </h2>
        {description != null && description !== '' && (
          <p className="mt-1 text-sm text-gray-600">{description}</p>
        )}
        <div className="mt-4 flex gap-3">
          <Button
            ref={cancelRef}
            variant="secondary"
            className="flex-1"
            onClick={onCancel}
            testId="confirm-dialog-cancel"
          >
            {cancelText}
          </Button>
          <Button
            variant={danger ? 'dangerSolid' : 'primary'}
            className="flex-1"
            onClick={onConfirm}
            testId="confirm-dialog-confirm"
          >
            {confirmText}
          </Button>
        </div>
      </div>
    </div>
  )
}
