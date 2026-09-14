/**
 * 暗色模式：class 策略（html.dark）
 * 跟随系统 prefers-color-scheme，为后续设置页手动开关预留入口
 */

/** @param {boolean} isDark */
export function applyDarkClass(isDark) {
  const root = document.documentElement
  if (isDark) {
    root.classList.add('dark')
  } else {
    root.classList.remove('dark')
  }
}

/**
 * 监听系统偏好并同步 html.dark
 * @returns {() => void} cleanup
 */
export function initDarkModeListener() {
  const mq = window.matchMedia('(prefers-color-scheme: dark)')
  const sync = () => applyDarkClass(mq.matches)
  sync()
  mq.addEventListener('change', sync)
  return () => mq.removeEventListener('change', sync)
}
