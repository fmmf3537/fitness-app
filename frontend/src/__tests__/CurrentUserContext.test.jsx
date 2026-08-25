import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import { CurrentUserProvider, useCurrentUser } from '../contexts/CurrentUserContext'

function Probe() {
  const cu = useCurrentUser()
  return <div data-testid="probe">{cu ? JSON.stringify(cu) : 'null'}</div>
}

describe('CurrentUserProvider', () => {
  beforeEach(() => localStorage.clear())

  it('localStorage 无 user 信息时返回 null', () => {
    render(
      <CurrentUserProvider>
        <Probe />
      </CurrentUserProvider>,
    )
    expect(screen.getByTestId('probe')).toHaveTextContent('null')
  })

  it('localStorage 有 user_id+role 时返回带 isAdmin', () => {
    localStorage.setItem('fh_token', 't')
    localStorage.setItem('fh_user_id', '5')
    localStorage.setItem('fh_user_role', 'admin')
    render(
      <CurrentUserProvider>
        <Probe />
      </CurrentUserProvider>,
    )
    const t = screen.getByTestId('probe').textContent
    expect(t).toContain('"user_id":5')
    expect(t).toContain('"isAdmin":true')
  })

  it('role=user 时 isAdmin=false', () => {
    localStorage.setItem('fh_token', 't')
    localStorage.setItem('fh_user_id', '1')
    localStorage.setItem('fh_user_role', 'user')
    render(
      <CurrentUserProvider>
        <Probe />
      </CurrentUserProvider>,
    )
    expect(screen.getByTestId('probe')).toHaveTextContent('"isAdmin":false')
  })
})
