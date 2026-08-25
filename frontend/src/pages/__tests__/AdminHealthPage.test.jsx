import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { CurrentUserProvider } from '../../contexts/CurrentUserContext'
import AdminHealthPage from '../AdminHealthPage'

function mockResponse(data, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => data }
}

const HEALTH = {
  users: [
    {
      user_id: 1,
      username: 'alice',
      is_active: true,
      garmin_token_state: 'ok',
      last_sync_at: '2026-08-25T22:47:00',
      monthly_llm_cost: 0.42,
      pending_match_count: 0,
    },
    {
      user_id: 2,
      username: 'bob',
      is_active: true,
      garmin_token_state: 'expired',
      last_sync_at: null,
      monthly_llm_cost: 0,
      pending_match_count: 2,
    },
    {
      user_id: 3,
      username: 'carol',
      is_active: false,
      garmin_token_state: 'missing',
      last_sync_at: null,
      monthly_llm_cost: 0,
      pending_match_count: 0,
    },
    {
      user_id: 4,
      username: 'dave',
      is_active: true,
      garmin_token_state: 'n/a',
      last_sync_at: null,
      monthly_llm_cost: 0,
      pending_match_count: 0,
    },
  ],
  system: {
    db_size_bytes: 52428800,
    last_backup_at: '2026-08-25T03:17:00',
    scheduler_running: true,
  },
}

describe('AdminHealthPage', () => {
  beforeEach(() => {
    localStorage.clear()
    localStorage.setItem('fh_token', 'tok')
    localStorage.setItem('fh_user_id', '99')
    localStorage.setItem('fh_user_role', 'admin')
    globalThis.fetch = vi.fn((url) => {
      if (url === '/api/admin/health') return Promise.resolve(mockResponse(HEALTH))
      return Promise.resolve(mockResponse({}, 404))
    })
  })

  it('非 admin 显示 403', () => {
    localStorage.setItem('fh_user_role', 'user')
    render(
      <CurrentUserProvider>
        <AdminHealthPage />
      </CurrentUserProvider>,
    )
    expect(screen.getByTestId('admin-forbidden')).toBeInTheDocument()
  })

  it('渲染系统卡片与用户卡片', async () => {
    render(
      <CurrentUserProvider>
        <AdminHealthPage />
      </CurrentUserProvider>,
    )
    expect(await screen.findByTestId('db-size')).toHaveTextContent('50.0 MB')
    expect(screen.getByTestId('user-health-1')).toBeInTheDocument()
    expect(screen.getByTestId('user-health-2').textContent).toContain('expired')
    expect(screen.getByTestId('user-health-3').textContent).toContain('missing')
    expect(screen.getByTestId('user-health-4').textContent).toContain('n/a')
  })
})
