import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { getToken } from '../api/client'
import { useCurrentUser } from '../contexts/CurrentUserContext'

export default function RequireAuth() {
  const location = useLocation()
  const cu = useCurrentUser()
  if (!getToken() || !cu) {
    return <Navigate to="/login" replace state={{ from: location }} />
  }
  return <Outlet />
}
