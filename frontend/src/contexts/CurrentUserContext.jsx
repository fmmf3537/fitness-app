import { createContext, useContext, useSyncExternalStore } from 'react'
import { getCurrentUser, subscribeAuth } from '../api/client'

const Ctx = createContext(null)

/**
 * 当前用户 Provider（M5 hotfix 2026-08-26）。
 *
 * 修复内容：原实现用 useMemo([]) 只在挂载时读一次 localStorage，
 * 登录后 token 写入但 Provider 不刷新 → RequireAuth 永远拿到 null → 死循环。
 *
 * 实现要点：useSyncExternalStore 要求 snapshot 函数返回**稳定引用**
 * （React 用 Object.is 判等），所以这里用 module-level cache：
 * - getCachedSnapshot：localStorage 真实内容不变时返回同一个对象引用
 * - 内容变化时（subscribeAuth 通知）才更新 cache
 * 这样既不引起无限渲染，又能在登录/登出后正确刷新。
 */

let cachedSnapshot = getCurrentUser()
let cachedSerialized = JSON.stringify(cachedSnapshot)

function getCachedSnapshot() {
  // 实时读 localStorage（让外部直接 setItem 时也能感知，但不触发通知）
  const current = getCurrentUser()
  const serialized = JSON.stringify(current)
  if (serialized !== cachedSerialized) {
    cachedSnapshot = current
    cachedSerialized = serialized
  }
  return cachedSnapshot
}

export function CurrentUserProvider({ children }) {
  const cu = useSyncExternalStore(subscribeAuth, getCachedSnapshot, getCachedSnapshot)

  const value = cu ? { ...cu, isAdmin: cu.role === 'admin' } : null

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useCurrentUser() {
  return useContext(Ctx)
}
