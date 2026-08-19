const TOKEN_KEY = 'fh_token'

export function getToken() {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token) {
  localStorage.setItem(TOKEN_KEY, token)
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY)
}

export class ApiError extends Error {
  constructor(status, message, detail = null) {
    super(message)
    this.status = status
    // 服务端返回的友好错误文案（FastAPI 的 {detail: ...}），无则 null
    this.detail = detail
  }
}

/** 从错误响应体中提取 FastAPI detail 文案（非 JSON / 无 detail 时返回 null）。 */
async function extractDetail(res) {
  try {
    const data = await res.json()
    return typeof data?.detail === 'string' && data.detail ? data.detail : null
  } catch {
    return null
  }
}

export async function api(path, options = {}) {
  const token = getToken()
  const headers = { ...(options.headers || {}) }
  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }
  if (options.body) {
    headers['Content-Type'] = 'application/json'
  }
  const res = await fetch(path, { ...options, headers })
  if (res.status === 401) {
    clearToken()
    throw new ApiError(401, 'unauthorized')
  }
  if (res.status === 404) {
    throw new ApiError(404, 'not found')
  }
  if (res.status === 409) {
    throw new ApiError(409, 'conflict')
  }
  if (!res.ok) {
    throw new ApiError(res.status, `request failed: ${res.status}`)
  }
  return res.json()
}

export async function apiForm(path, formData) {
  // multipart 上传：不手动设置 Content-Type，交由浏览器生成 boundary
  const token = getToken()
  const headers = token ? { Authorization: `Bearer ${token}` } : {}
  const res = await fetch(path, { method: 'POST', body: formData, headers })
  if (res.status === 401) {
    clearToken()
    throw new ApiError(401, 'unauthorized')
  }
  if (!res.ok) {
    // V3-10c：把服务端 detail 带上，页面可展示友好文案而非裸状态码
    throw new ApiError(res.status, `request failed: ${res.status}`, await extractDetail(res))
  }
  return res.json()
}

export async function download(path, filename) {
  const token = getToken()
  const headers = token ? { Authorization: `Bearer ${token}` } : {}
  const res = await fetch(path, { headers })
  if (res.status === 401) {
    clearToken()
    throw new ApiError(401, 'unauthorized')
  }
  if (!res.ok) {
    throw new ApiError(res.status, `request failed: ${res.status}`)
  }
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

export async function login(password) {
  const res = await fetch('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ password }),
  })
  if (res.status === 401) {
    throw new ApiError(401, '口令错误')
  }
  if (!res.ok) {
    throw new ApiError(res.status, `request failed: ${res.status}`)
  }
  return res.json()
}
