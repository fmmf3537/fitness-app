import { createContext, useContext, useMemo } from 'react'
import { getCurrentUser } from '../api/client'

const Ctx = createContext(null)

export function CurrentUserProvider({ children }) {
  const value = useMemo(() => {
    const cu = getCurrentUser()
    if (!cu) return null
    return {
      ...cu,
      isAdmin: cu.role === 'admin',
    }
  }, [])

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useCurrentUser() {
  return useContext(Ctx)
}
