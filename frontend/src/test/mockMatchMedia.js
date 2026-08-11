// jsdom 未实现 window.matchMedia，这里提供统一 mock。
// installMatchMedia(false) = 桌面（默认）；installMatchMedia(true) = 移动端。
export function installMatchMedia(initialMatches = false) {
  const listeners = new Set()
  const state = { matches: initialMatches }
  window.matchMedia = (query) => ({
    get matches() {
      return state.matches
    },
    media: query,
    onchange: null,
    addEventListener: (_type, cb) => listeners.add(cb),
    removeEventListener: (_type, cb) => listeners.delete(cb),
    addListener: (cb) => listeners.add(cb),
    removeListener: (cb) => listeners.delete(cb),
    dispatchEvent: () => true,
  })
  return {
    setMatches(next) {
      state.matches = next
      listeners.forEach((cb) => cb({ matches: next }))
    },
  }
}
