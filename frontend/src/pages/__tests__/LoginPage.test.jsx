import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, login, setToken } from '../../api/client'
import LoginPage from '../LoginPage'

vi.mock('../../api/client', async (importOriginal) => {
  const actual = await importOriginal()
  return {
    ...actual,
    login: vi.fn(),
    setToken: vi.fn(),
  }
})

function renderLogin(initialEntry = '/login') {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/" element={<div data-testid="page-home">home</div>} />
        <Route path="/trends" element={<div data-testid="page-trends">trends</div>} />
        <Route path="/body-metrics" element={<div data-testid="page-body">body</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('LoginPage', () => {
  beforeEach(() => {
    vi.mocked(login).mockReset()
    vi.mocked(setToken).mockReset()
    sessionStorage.clear()
  })

  it('渲染口令 label、输入框与登录按钮', () => {
    renderLogin()
    expect(screen.getByLabelText('口令')).toBeInTheDocument()
    expect(screen.getByPlaceholderText('请输入访问口令')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '登录' })).toBeInTheDocument()
  })

  it('无 state 无 sessionStorage 时登录成功跳 /', async () => {
    const user = userEvent.setup()
    vi.mocked(login).mockResolvedValue({ token: 't' })
    renderLogin()

    await user.type(screen.getByLabelText('口令'), 'secret')
    await user.click(screen.getByRole('button', { name: '登录' }))

    await waitFor(() => {
      expect(screen.getByTestId('page-home')).toBeInTheDocument()
    })
    expect(setToken).toHaveBeenCalledWith('t')
  })

  it('location.state.from 存在时登录成功跳目标页', async () => {
    const user = userEvent.setup()
    vi.mocked(login).mockResolvedValue({ token: 't' })
    renderLogin({
      pathname: '/login',
      state: { from: { pathname: '/trends', search: '' } },
    })

    await user.type(screen.getByLabelText('口令'), 'secret')
    await user.click(screen.getByRole('button', { name: '登录' }))

    await waitFor(() => {
      expect(screen.getByTestId('page-trends')).toBeInTheDocument()
    })
  })

  it('sessionStorage fh_auth_from 存在且无 state 时跳回并清除键', async () => {
    const user = userEvent.setup()
    sessionStorage.setItem('fh_auth_from', '/body-metrics')
    vi.mocked(login).mockResolvedValue({ token: 't' })
    renderLogin()

    await user.type(screen.getByLabelText('口令'), 'secret')
    await user.click(screen.getByRole('button', { name: '登录' }))

    await waitFor(() => {
      expect(screen.getByTestId('page-body')).toBeInTheDocument()
    })
    expect(sessionStorage.getItem('fh_auth_from')).toBeNull()
  })

  it('401 显示口令错误且不跳转', async () => {
    const user = userEvent.setup()
    vi.mocked(login).mockRejectedValue(new ApiError(401, '口令错误'))
    renderLogin()

    await user.type(screen.getByLabelText('口令'), 'bad')
    await user.click(screen.getByRole('button', { name: '登录' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('口令错误')
    expect(screen.getByRole('button', { name: '登录' })).toBeInTheDocument()
    expect(screen.queryByTestId('page-home')).not.toBeInTheDocument()
    expect(setToken).not.toHaveBeenCalled()
  })

  it('按钮与输入框含 min-h-[44px]，根容器含 min-h-dvh', () => {
    renderLogin()
    const root = screen.getByLabelText('口令').closest('.min-h-dvh')
    expect(root).not.toBeNull()
    expect(screen.getByLabelText('口令')).toHaveClass('min-h-[44px]')
    expect(screen.getByRole('button', { name: '登录' })).toHaveClass('min-h-[44px]')
  })

  it('品牌区含 Logo svg 与标题「健身看板」', () => {
    const { container } = renderLogin()
    expect(screen.getByRole('heading', { level: 1, name: '健身看板' })).toBeInTheDocument()
    expect(container.querySelector('svg')).not.toBeNull()
    expect(screen.getByRole('heading', { level: 2, name: '登录' })).toBeInTheDocument()
  })
})
