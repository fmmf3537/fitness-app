import { useRef, useState } from 'react'

export default function usePullToRefresh(onRefresh) {
  const startY = useRef(null)
  const [pulling, setPulling] = useState(false)
  return {
    pulling,
    bind: {
      onTouchStart(event) {
        if (window.scrollY === 0) startY.current = event.touches[0]?.clientY ?? null
      },
      onTouchEnd(event) {
        const endY = event.changedTouches[0]?.clientY
        const distance = startY.current == null || endY == null ? 0 : endY - startY.current
        startY.current = null
        if (distance < 70 || pulling) return
        setPulling(true)
        Promise.resolve(onRefresh()).finally(() => setPulling(false))
      },
    },
  }
}
