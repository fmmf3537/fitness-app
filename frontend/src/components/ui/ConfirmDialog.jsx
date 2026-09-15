import { useId, useRef } from 'react'
import Button from './Button'
import useModalAccessibility from '../../hooks/useModalAccessibility'

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
  const dialogRef = useRef(null)
  const titleId = useId()
  const descriptionId = useId()
  useModalAccessibility({ open, containerRef: dialogRef, initialFocusRef: cancelRef, onClose: onCancel })

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div
        data-testid="confirm-dialog-backdrop"
        className="absolute inset-0 bg-black/50"
        onClick={onCancel}
      />
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description != null && description !== '' ? descriptionId : undefined}
        tabIndex={-1}
        data-testid="confirm-dialog"
        className="relative w-full max-w-sm rounded-xl bg-white dark:bg-gray-900 p-5 shadow-xl mb-[env(safe-area-inset-bottom)]"
      >
        <h2 id={titleId} className="text-base font-semibold text-gray-900 dark:text-gray-100">
          {title}
        </h2>
        {description != null && description !== '' && (
          <p id={descriptionId} className="mt-1 text-sm text-gray-600 dark:text-gray-400">{description}</p>
        )}
        <div className="mt-4 flex gap-3">
          <Button
            ref={cancelRef}
            variant="secondary"
            className="flex-1"
            onClick={onCancel}
            testId="confirm-dialog-cancel"
            dataDialogClose
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
