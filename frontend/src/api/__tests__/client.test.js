import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'
import {
  api,
  login,
  getToken,
  setToken,
  clearToken,
  ApiError,
} from '../client'

function mockFetch(status, body = {}) {
  return vi.fn().mockResolvedValue({
    status,
    ok: status >= 200 && status < 300,
    json: () => Promise.resolve(body),
  })
}

/** 可写 location stub：便于断言 redirectToLogin 的 href 赋值与 pathname 分支 */
function stubLocation({ pathname = '/settings', search = '' } = {}) {
  const loc = { pathname, search, href: '' }
  Object.defineProperty(window, 'location', {
    configurable: true,
    writable: true,
    value: loc,
  })
  return loc
}

describe('token 存取', () => {
  beforeEach(() => localStorage.clear())

  it('set/get/clear token', () => {
    expect(getToken()).toBeNull()
    setToken('abc')
    expect(getToken()).toBe('abc')
    clearToken()
    expect(getToken()).toBeNull()
  })
})

describe('api()', () => {
  let loc

  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
    loc = stubLocation({ pathname: '/settings', search: '' })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    sessionStorage.clear()
  })

  it('成功时返回 json，带 token 时附加 Authorization 头', async () => {
    setToken('t123')
    const fetchMock = mockFetch(200, { ok: 1 })
    vi.stubGlobal('fetch', fetchMock)
    const data = await api('/api/x', { headers: { 'X-A': 'b' } })
    expect(data).toEqual({ ok: 1 })
    const [, opts] = fetchMock.mock.calls[0]
    expect(opts.headers.Authorization).toBe('Bearer t123')
    expect(opts.headers['X-A']).toBe('b')
  })

  it('无 token 不带 Authorization；带 body 时补 Content-Type', async () => {
    const fetchMock = mockFetch(200, {})
    vi.stubGlobal('fetch', fetchMock)
    await api('/api/x', { method: 'POST', body: '{}' })
    const [, opts] = fetchMock.mock.calls[0]
    expect(opts.headers.Authorization).toBeUndefined()
    expect(opts.headers['Content-Type']).toBe('application/json')
  })

  it('401 清除 token 并抛 ApiError(401)', async () => {
    setToken('t123')
    vi.stubGlobal('fetch', mockFetch(401))
    await expect(api('/api/x')).rejects.toMatchObject({ status: 401 })
    expect(getToken()).toBeNull()
    expect(sessionStorage.getItem('fh_auth_from')).toBe('/settings')
    expect(loc.href).toBe('/login')
  })

  it('401 时 pathname 已是 /login 不写 sessionStorage', async () => {
    loc = stubLocation({ pathname: '/login', search: '' })
    setToken('t123')
    vi.stubGlobal('fetch', mockFetch(401))
    await expect(api('/api/x')).rejects.toMatchObject({ status: 401 })
    expect(getToken()).toBeNull()
    expect(sessionStorage.getItem('fh_auth_from')).toBeNull()
    expect(loc.href).toBe('')
  })

  it('401 时记住 pathname+search', async () => {
    loc = stubLocation({ pathname: '/workouts', search: '?date=2026-08-03' })
    setToken('t123')
    vi.stubGlobal('fetch', mockFetch(401))
    await expect(api('/api/x')).rejects.toMatchObject({ status: 401 })
    expect(sessionStorage.getItem('fh_auth_from')).toBe('/workouts?date=2026-08-03')
    expect(loc.href).toBe('/login')
  })

  it('404 抛 not found', async () => {
    vi.stubGlobal('fetch', mockFetch(404))
    await expect(api('/api/x')).rejects.toMatchObject({
      status: 404,
      message: 'not found',
    })
  })

  it('409 抛 conflict', async () => {
    vi.stubGlobal('fetch', mockFetch(409))
    await expect(api('/api/x')).rejects.toMatchObject({
      status: 409,
      message: 'conflict',
    })
  })

  it('其他非 ok 状态抛 request failed', async () => {
    vi.stubGlobal('fetch', mockFetch(500))
    await expect(api('/api/x')).rejects.toMatchObject({
      status: 500,
      message: 'request failed: 500',
    })
  })

  it('ApiError 是 Error 子类', () => {
    const err = new ApiError(400, 'bad')
    expect(err).toBeInstanceOf(Error)
    expect(err.status).toBe(400)
  })
})

describe('login()', () => {
  beforeEach(() => {
    sessionStorage.clear()
    stubLocation({ pathname: '/login', search: '' })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    sessionStorage.clear()
  })

  it('成功返回 json', async () => {
    const fetchMock = mockFetch(200, { token: 'tok' })
    vi.stubGlobal('fetch', fetchMock)
    const data = await login('pw')
    expect(data).toEqual({ token: 'tok' })
    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/auth/login')
    expect(JSON.parse(opts.body)).toEqual({ password: 'pw' })
  })

  it('401 抛口令错误', async () => {
    vi.stubGlobal('fetch', mockFetch(401))
    await expect(login('bad')).rejects.toMatchObject({
      status: 401,
      message: '口令错误',
    })
    // login 自身 401 不走统一拦截，不写回跳路径
    expect(sessionStorage.getItem('fh_auth_from')).toBeNull()
  })

  it('其他非 ok 状态抛 request failed', async () => {
    vi.stubGlobal('fetch', mockFetch(503))
    await expect(login('pw')).rejects.toMatchObject({
      status: 503,
      message: 'request failed: 503',
    })
  })
})
