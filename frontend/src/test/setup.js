import '@testing-library/jest-dom'

// jsdom 环境下补齐 localStorage（部分版本默认不提供）
if (
  typeof globalThis.localStorage === 'undefined' ||
  typeof globalThis.localStorage.setItem !== 'function'
) {
  const store = new Map()
  globalThis.localStorage = {
    getItem: (key) => (store.has(String(key)) ? store.get(String(key)) : null),
    setItem: (key, value) => store.set(String(key), String(value)),
    removeItem: (key) => store.delete(String(key)),
    clear: () => store.clear(),
    get length() {
      return store.size
    },
    key: (i) => [...store.keys()][i] ?? null,
  }
}
