import { useEffect, useState } from 'react'

const MOBILE_QUERY = '(max-width: 767px)'

/** 是否移动端断点（<md，即 <768px），断点变化时自动更新。 */
export default function useIsMobile() {
  const [isMobile, setIsMobile] = useState(() => window.matchMedia(MOBILE_QUERY).matches)

  useEffect(() => {
    const mql = window.matchMedia(MOBILE_QUERY)
    const onChange = (e) => setIsMobile(e.matches)
    mql.addEventListener('change', onChange)
    return () => mql.removeEventListener('change', onChange)
  }, [])

  return isMobile
}
