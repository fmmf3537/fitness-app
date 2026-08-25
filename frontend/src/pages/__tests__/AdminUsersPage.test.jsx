import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { CurrentUserProvider } from '../../contexts/CurrentUserContext'
import AdminUsersPage from '../AdminUsersPage'

function mockResponse(data, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => data }
}

const USERS = [
  {
    id: 1,
    username: 'alice',
    role: 'user',
    is_active: true,
    bindings: { garmin: true, xunji: false, llm: true },
  },
  {
    id: 2,
    username: 'bob',
    role: 'user',
    is_active: false,
    bindings: { garmin: false, xunji: true, llm: false },
  },
]

function renderPage() {
  return render(
    <CurrentUserProvider>
      <AdminUsersPage />
    </CurrentUserProvider>,
  )
}

describe('AdminUsersPage', () => {
  beforeEach(() => {
    localStorage.clear()
    localStorage.setItem('fh_token', 'tok')
    localStorage.setItem('fh_user_id', '99')
    localStorage.setItem('fh_user_role', 'admin')
  })

  it('非 admin 显示 403', () => {
    localStorage.setItem('fh_user_role', 'user')
    renderPage()
    expect(screen.getByTestId('admin-forbidden')).toBeInTheDocument()
  })

  it('加载用户列表', async () => {
    globalThis.fetch = vi.fn((url) => {
      if (url === '/api/admin/users') return Promise.resolve(mockResponse(USERS))
      return Promise.resolve(mockResponse({}, 404))
    })
    renderPage()
    expect(await screen.findByTestId('user-row-1')).toBeInTheDocument()
    expect(screen.getByTestId('user-row-2')).toBeInTheDocument()
  })

  it('创建用户成功', async () => {
    const user = userEvent.setup()
    let users = [...USERS]
    globalThis.fetch = vi.fn((url, opts = {}) => {
      if (url === '/api/admin/users' && opts.method === 'POST') {
        users = [...users, { id: 3, username: 'carol', role: 'user', is_active: true, bindings: {} }]
        return Promise.resolve(mockResponse({ id: 3 }, 201))
      }
      if (url === '/api/admin/users') return Promise.resolve(mockResponse(users))
      return Promise.resolve(mockResponse({}, 404))
    })
    renderPage()
    await screen.findByTestId('users-table')
    await user.type(screen.getByTestId('create-username'), 'carol')
    await user.type(screen.getByTestId('create-password'), 'secret1')
    await user.click(screen.getByTestId('create-submit'))
    await waitFor(() => {
      expect(screen.getByTestId('user-row-3')).toBeInTheDocument()
    })
  })

  it('重置密码调用 PUT', async () => {
    const user = userEvent.setup()
    vi.stubGlobal('prompt', vi.fn(() => 'new-pass-99'))
    globalThis.fetch = vi.fn((url, opts = {}) => {
      if (url === '/api/admin/users') return Promise.resolve(mockResponse(USERS))
      if (url === '/api/admin/users/2/reset-password' && opts.method === 'PUT') {
        return Promise.resolve(mockResponse({ ok: true }))
      }
      return Promise.resolve(mockResponse({}, 404))
    })
    renderPage()
    await screen.findByTestId('user-row-2')
    await user.click(screen.getByTestId('reset-pwd-2'))
    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        '/api/admin/users/2/reset-password',
        expect.objectContaining({ method: 'PUT' }),
      )
    })
    vi.unstubAllGlobals()
  })

  it('停用用户', async () => {
    const user = userEvent.setup()
    globalThis.fetch = vi.fn((url, opts = {}) => {
      if (url === '/api/admin/users') return Promise.resolve(mockResponse(USERS))
      if (url === '/api/admin/users/1/deactivate' && opts.method === 'PUT') {
        return Promise.resolve(mockResponse({ ok: true }))
      }
      return Promise.resolve(mockResponse({}, 404))
    })
    renderPage()
    await screen.findByTestId('user-row-1')
    await user.click(screen.getByTestId('deactivate-1'))
    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        '/api/admin/users/1/deactivate',
        expect.objectContaining({ method: 'PUT' }),
      )
    })
  })
})
