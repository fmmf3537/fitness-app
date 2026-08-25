import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import { useCurrentUser } from '../contexts/CurrentUserContext'
import { CurrentUserProvider } from '../contexts/CurrentUserContext'

function Probe() {
  const cu = useCurrentUser()
  return <div data-testid="hook-probe">{cu?.role ?? 'none'}</div>
}

describe('useCurrentUser', () => {
  beforeEach(() => localStorage.clear())

  it('在 Provider 外返回 null', () => {
    render(<Probe />)
    expect(screen.getByTestId('hook-probe')).toHaveTextContent('none')
  })

  it('在 Provider 内读取 role', () => {
    localStorage.setItem('fh_token', 't')
    localStorage.setItem('fh_user_id', '2')
    localStorage.setItem('fh_user_role', 'user')
    render(
      <CurrentUserProvider>
        <Probe />
      </CurrentUserProvider>,
    )
    expect(screen.getByTestId('hook-probe')).toHaveTextContent('user')
  })
})
