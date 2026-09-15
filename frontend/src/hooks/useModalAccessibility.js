import { useEffect, useRef } from 'react'

const FOCUSABLE = [
  'button:not([disabled])',
  'a[href]',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',')

let scrollLocks = 0
let originalOverflow = ''
const modalStack = []

function lockScroll() {
  if (scrollLocks === 0) {
    originalOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
  }
  scrollLocks += 1
}

function unlockScroll() {
  scrollLocks = Math.max(0, scrollLocks - 1)
  if (scrollLocks === 0) document.body.style.overflow = originalOverflow
}

function isTopmostDialog(dialog) {
  return modalStack.filter((item) => item?.isConnected).at(-1) === dialog
}

function focusFallback() {
  const target = document.querySelector('main h1, main h2, main button, main a[href]')
  if (!target) return
  if (!target.matches(FOCUSABLE)) target.setAttribute('tabindex', '-1')
  target.focus()
}

/** Focus trap, Escape handling, scroll lock and focus restoration for modal surfaces. */
export default function useModalAccessibility({ open, containerRef, initialFocusRef, onClose }) {
  const triggerRef = useRef(null)
  const closeRef = useRef(onClose)
  closeRef.current = onClose

  useEffect(() => {
    if (!open) return undefined
    triggerRef.current = document.activeElement
    lockScroll()
    const dialog = containerRef.current
    modalStack.push(dialog)
    const initial = initialFocusRef?.current || dialog?.querySelector(FOCUSABLE) || dialog
    initial?.focus()

    const onDialogKeyDown = (event) => {
      const current = containerRef.current
      if (!current) return
      if (event.key === 'Escape') {
        if (!isTopmostDialog(current)) return
        event.preventDefault()
        event.stopPropagation()
        closeRef.current?.()
        return
      }
      if (event.key !== 'Tab') return
      const focusable = [...current.querySelectorAll(FOCUSABLE)]
      if (focusable.length === 0) {
        event.preventDefault()
        current.focus()
        return
      }
      const first = focusable[0]
      const last = focusable.at(-1)
      const active = event.target
      if (event.shiftKey && (active === first || !current.contains(active))) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && (active === last || !current.contains(active))) {
        event.preventDefault()
        first.focus()
      }
    }
    const onDocumentKeyDown = (event) => {
      if (event.key !== 'Escape' || !isTopmostDialog(dialog)) return
      event.preventDefault()
      event.stopPropagation()
      closeRef.current?.()
    }
    dialog?.addEventListener('keydown', onDialogKeyDown)
    document.addEventListener('keydown', onDocumentKeyDown)
    return () => {
      dialog?.removeEventListener('keydown', onDialogKeyDown)
      document.removeEventListener('keydown', onDocumentKeyDown)
      const position = modalStack.lastIndexOf(dialog)
      if (position >= 0) modalStack.splice(position, 1)
      unlockScroll()
      const trigger = triggerRef.current
      if (trigger?.isConnected && typeof trigger.focus === 'function') trigger.focus()
      else focusFallback()
    }
  }, [open, containerRef, initialFocusRef])
}
