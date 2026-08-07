import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import BodyMetricsPage from '../BodyMetricsPage'

vi.mock('echarts', () => ({
  init: vi.fn(() => ({
    setOption: vi.fn(),
    resize: vi.fn(),
    dispose: vi.fn(),
  })),
}))

function mockResponse(data, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => data }
}

const EMPTY_TRENDS = {
  weeks: 12,
  weekly_volume: [],
  body_part_frequency: [],
  body_metrics: { weight: [], bodyfat: [] },
  sleep_volume: [],
}

const WEIGHT_ROW = {
  id: 1,
  date: '2026-08-03',
  type: 'weight',
  value: 72.4,
  unit: 'kg',
  synced_to_xunji: false,
  note: null,
}
const HEIGHT_ROW = {
  id: 2,
  date: '2026-08-01',
  type: 'height',
  value: 175,
  unit: 'cm',
  synced_to_xunji: false,
  note: null,
}

/** 按 URL/方法路由的 fetch mock；postBodies 收集所有 POST 请求体。 */
function mockFetch({ metrics = [], trends = EMPTY_TRENDS } = {}) {
  const postBodies = []
  globalThis.fetch = vi.fn((url, options = {}) => {
    if (options.method === 'POST' && options.body) {
      postBodies.push({ url, body: JSON.parse(options.body) })
    }
    if (url === '/api/body-metrics' && options.method === 'POST') {
      return Promise.resolve(mockResponse({ ...WEIGHT_ROW }))
    }
    if (url.endsWith('/sync-xunji')) {
      const confirmed = options.body ? JSON.parse(options.body).confirmed : false
      return Promise.resolve(
        mockResponse(
          confirmed
            ? { status: 'synced', summary: '已更新 1 条', metric: { ...WEIGHT_ROW, synced_to_xunji: true } }
            : { status: 'preview', summary: '将更新 2026-08-03 体重 72.4kg', metric: WEIGHT_ROW },
        ),
      )
    }
    if (url.startsWith('/api/body-metrics')) {
      return Promise.resolve(mockResponse({ metrics }))
    }
    if (url.startsWith('/api/stats/trends')) {
      return Promise.resolve(mockResponse(trends))
    }
    return Promise.resolve(mockResponse({ detail: 'not found' }, 404))
  })
  return postBodies
}

describe('BodyMetricsPage', () => {
  beforeEach(() => {
    localStorage.setItem('fh_token', 'test-token')
  })

  it('加载记录与趋势并渲染录入表单、图表、记录列表', async () => {
    mockFetch({ metrics: [WEIGHT_ROW, HEIGHT_ROW] })
    render(<BodyMetricsPage />)

    expect(await screen.findByTestId('metric-form')).toBeInTheDocument()
    expect(screen.getByTestId('trend-chart-weight')).toBeInTheDocument()
    expect(screen.getByTestId('trend-chart-height')).toBeInTheDocument()
    expect(screen.getByTestId('metric-row-1')).toBeInTheDocument()
    expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/stats/trends?weeks=12',
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: 'Bearer test-token' }),
      }),
    )
  })

  it('无身高记录时显示首次使用引导，有身高记录时不显示', async () => {
    mockFetch({ metrics: [WEIGHT_ROW] })
    const { unmount } = render(<BodyMetricsPage />)
    expect(await screen.findByTestId('height-guide')).toBeInTheDocument()
    unmount()

    mockFetch({ metrics: [HEIGHT_ROW] })
    render(<BodyMetricsPage />)
    await screen.findByTestId('metric-row-2')
    expect(screen.queryByTestId('height-guide')).not.toBeInTheDocument()
  })

  it('提交体重：POST 正确请求体', async () => {
    const postBodies = mockFetch({ metrics: [] })
    const user = userEvent.setup()
    render(<BodyMetricsPage />)
    await screen.findByTestId('metric-form')

    await user.selectOptions(screen.getByTestId('metric-type'), 'weight')
    await user.clear(screen.getByTestId('metric-value'))
    await user.type(screen.getByTestId('metric-value'), '72.4')
    await user.click(screen.getByTestId('submit-metric'))

    await vi.waitFor(() => {
      expect(postBodies).toContainEqual({
        url: '/api/body-metrics',
        body: expect.objectContaining({ type: 'weight', value: 72.4 }),
      })
    })
  })

  it('提交血压：拆分为收缩压/舒张压两条记录', async () => {
    const postBodies = mockFetch({ metrics: [] })
    const user = userEvent.setup()
    render(<BodyMetricsPage />)
    await screen.findByTestId('metric-form')

    await user.selectOptions(screen.getByTestId('metric-type'), 'blood_pressure')
    await user.type(screen.getByTestId('metric-bp-systolic'), '120')
    await user.type(screen.getByTestId('metric-bp-diastolic'), '80')
    await user.click(screen.getByTestId('submit-metric'))

    await vi.waitFor(() => {
      const types = postBodies.map((p) => p.body.type)
      expect(types).toContain('bp_systolic')
      expect(types).toContain('bp_diastolic')
    })
    const systolic = postBodies.find((p) => p.body.type === 'bp_systolic')
    const diastolic = postBodies.find((p) => p.body.type === 'bp_diastolic')
    expect(systolic.body.value).toBe(120)
    expect(diastolic.body.value).toBe(80)
  })

  it('仅本地指标标注「仅本地」且无同步按钮', async () => {
    mockFetch({ metrics: [HEIGHT_ROW] })
    render(<BodyMetricsPage />)
    await screen.findByTestId('metric-row-2')
    expect(screen.getByTestId('local-only-2')).toHaveTextContent('仅本地')
    expect(screen.queryByTestId('sync-btn-2')).not.toBeInTheDocument()
  })

  it('同步三段式：预览摘要弹窗 → 确认后才发送 confirmed:true → 已同步', async () => {
    const postBodies = mockFetch({ metrics: [WEIGHT_ROW] })
    const user = userEvent.setup()
    render(<BodyMetricsPage />)
    await screen.findByTestId('metric-row-1')

    // 第一步：点击「同步到训记」→ 预览请求（dry_run）
    await user.click(screen.getByTestId('sync-btn-1'))
    expect(await screen.findByTestId('sync-modal')).toBeInTheDocument()
    expect(screen.getByTestId('sync-summary')).toHaveTextContent('将更新 2026-08-03 体重 72.4kg')

    const previewCalls = postBodies.filter((p) => p.url.endsWith('/sync-xunji'))
    expect(previewCalls).toHaveLength(1)
    expect(previewCalls[0].body.confirmed).not.toBe(true)

    // 第二步：确认 → confirmed:true
    await user.click(screen.getByTestId('sync-confirm'))
    await vi.waitFor(() => {
      const syncCalls = postBodies.filter((p) => p.url.endsWith('/sync-xunji'))
      expect(syncCalls).toHaveLength(2)
      expect(syncCalls[1].body.confirmed).toBe(true)
    })
    expect(await screen.findByTestId('synced-1')).toHaveTextContent('已同步')
  })

  it('取消同步不发送 confirmed 请求', async () => {
    const postBodies = mockFetch({ metrics: [WEIGHT_ROW] })
    const user = userEvent.setup()
    render(<BodyMetricsPage />)
    await screen.findByTestId('metric-row-1')

    await user.click(screen.getByTestId('sync-btn-1'))
    await screen.findByTestId('sync-modal')
    await user.click(screen.getByTestId('sync-cancel'))

    expect(screen.queryByTestId('sync-modal')).not.toBeInTheDocument()
    const syncCalls = postBodies.filter((p) => p.url.endsWith('/sync-xunji'))
    expect(syncCalls).toHaveLength(1)
    expect(syncCalls[0].body.confirmed).not.toBe(true)
  })

  it('加载失败显示错误提示', async () => {
    globalThis.fetch = vi.fn(() => Promise.resolve(mockResponse({ detail: 'boom' }, 500)))
    render(<BodyMetricsPage />)
    expect(await screen.findByRole('alert')).toBeInTheDocument()
  })
})
