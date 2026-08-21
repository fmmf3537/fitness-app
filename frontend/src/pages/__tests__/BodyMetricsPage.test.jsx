import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as echarts from 'echarts'
import BodyMetricsPage from '../BodyMetricsPage'
import { installMatchMedia } from '../../test/mockMatchMedia'

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

const EXTRACT_RESULT = {
  date: '2026-08-18',
  metrics: [
    { type: 'weight', value: 86.7 },
    { type: 'bodyfat', value: 25.5 },
    { type: 'bmi', value: 29.3 },
  ],
}

const CONFIRM_RESULT = { imported: [], count: 2, warnings: [], sync: null }

/** 按 URL/方法路由的 fetch mock；postBodies 收集所有 POST 请求体。 */
function mockFetch({ metrics = [], trends = EMPTY_TRENDS } = {}) {
  const postBodies = []
  globalThis.fetch = vi.fn((url, options = {}) => {
    if (options.method === 'POST' && typeof options.body === 'string') {
      postBodies.push({ url, body: JSON.parse(options.body) })
    }
    if (url === '/api/body-metrics/extract-image') {
      return Promise.resolve(mockResponse(EXTRACT_RESULT))
    }
    if (url === '/api/body-metrics/confirm-import') {
      return Promise.resolve(mockResponse(CONFIRM_RESULT))
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
    vi.clearAllMocks()
    localStorage.setItem('fh_token', 'test-token')
  })

  afterEach(() => {
    installMatchMedia(false)
  })

  /** 所有图表实例最终 setOption 的 option 列表。 */
  function renderedOptions() {
    return echarts.init.mock.results.map((r) => r.value.setOption.mock.calls.at(-1)?.[0])
  }

  it('加载记录与趋势并渲染录入表单、图表、记录列表', async () => {
    mockFetch({ metrics: [WEIGHT_ROW, HEIGHT_ROW] })
    render(<BodyMetricsPage />)

    expect(await screen.findByTestId('metric-form')).toBeInTheDocument()
    // 趋势切换器：默认展示体重
    expect(screen.getByTestId('trend-chart-weight')).toBeInTheDocument()
    expect(screen.getByTestId('trend-type-select')).toBeInTheDocument()
    expect(screen.getByTestId('metric-row-1')).toBeInTheDocument()
    expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/stats/trends?weeks=12',
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: 'Bearer test-token' }),
      }),
    )
  })

  it('趋势切换器：分组选项 + 切换后渲染对应指标图', async () => {
    mockFetch({ metrics: [WEIGHT_ROW, HEIGHT_ROW] })
    const user = userEvent.setup()
    render(<BodyMetricsPage />)
    await screen.findByTestId('trend-chart-weight')

    const select = screen.getByTestId('trend-type-select')
    // 身高在「日常记录」分组
    expect(select.querySelector('optgroup[label="日常记录"]')).toBeTruthy()
    expect(screen.queryByTestId('trend-chart-height')).not.toBeInTheDocument()

    await user.selectOptions(select, 'height')
    expect(await screen.findByTestId('trend-chart-height')).toBeInTheDocument()
    expect(screen.queryByTestId('trend-chart-weight')).not.toBeInTheDocument()
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

  it('移动端断点：双轴图 time 轴 {MM}-{dd} 模板，指标图移动端 grid', async () => {
    installMatchMedia(true)
    mockFetch({ metrics: [WEIGHT_ROW] })
    render(<BodyMetricsPage />)
    await screen.findByTestId('trend-chart-weight')
    // T29：findBy 只保证 DOM 已提交，echarts.init/setOption 在 passive effect 中异步执行，
    // 须轮询等待 effect 刷新后再读 option，否则高负载时读到空 mock.results 偶发 TypeError
    await vi.waitFor(() => {
      const options = renderedOptions()
      const dual = options.find((o) => o?.xAxis?.type === 'time')
      const trend = options.find(
        (o) => o?.xAxis?.type === 'category' && o?.series?.[0]?.name === '体重',
      )
      expect(dual?.xAxis.axisLabel).toEqual({ rotate: 45, fontSize: 10, formatter: '{MM}-{dd}' })
      expect(dual?.legend?.type).toBe('scroll')
      expect(trend?.grid).toEqual({ left: 40, right: 12, top: 56, bottom: 48 })
      expect(trend?.xAxis.axisLabel.rotate).toBe(45)
      expect(trend?.xAxis.axisLabel.formatter('2026-08-03')).toBe('08-03')
      expect(trend?.yAxis.name).toBeUndefined()
    })
  })

  it('桌面断点：option 保持基线布局（无移动端改造）', async () => {
    mockFetch({ metrics: [WEIGHT_ROW] })
    render(<BodyMetricsPage />)
    await screen.findByTestId('trend-chart-weight')
    // 同上（T29）：轮询等待 passive effect 完成 setOption
    await vi.waitFor(() => {
      const options = renderedOptions()
      const dual = options.find((o) => o?.xAxis?.type === 'time')
      const trend = options.find(
        (o) => o?.xAxis?.type === 'category' && o?.series?.[0]?.name === '体重',
      )
      expect(trend?.grid).toEqual({ left: 50, right: 20, top: 40, bottom: 30 })
      expect(trend?.xAxis.axisLabel).toBeUndefined()
      expect(dual?.grid).toEqual({ left: 50, right: 50, top: 40, bottom: 30 })
      expect(dual?.xAxis.axisLabel).toBeUndefined()
    })
  })
})

describe('BodyMetricsPage 体脂秤图片导入（V3-9）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.setItem('fh_token', 'test-token')
  })

  afterEach(() => {
    installMatchMedia(false)
  })

  it('入口按钮打开导入面板', async () => {
    mockFetch({ metrics: [] })
    const user = userEvent.setup()
    render(<BodyMetricsPage />)
    await screen.findByTestId('metric-form')

    expect(screen.queryByTestId('image-import-panel')).not.toBeInTheDocument()
    await user.click(screen.getByTestId('open-image-import'))
    expect(screen.getByTestId('image-import-panel')).toBeInTheDocument()
  })

  it('上传 → 识别 → 确认页渲染（日期可改/逐条可编辑/默认全选/同步默认不勾）', async () => {
    mockFetch({ metrics: [] })
    const user = userEvent.setup()
    render(<BodyMetricsPage />)
    await screen.findByTestId('metric-form')

    await user.click(screen.getByTestId('open-image-import'))
    const file = new File(['jpg'], 'report.jpg', { type: 'image/jpeg' })
    await user.upload(screen.getByTestId('scale-file-input'), file)
    await user.click(screen.getByTestId('extract-image-btn'))

    await screen.findByTestId('import-preview')
    expect(screen.getByTestId('import-date')).toHaveValue('2026-08-18')
    expect(screen.getByTestId('import-select-weight')).toBeChecked()
    expect(screen.getByTestId('import-select-bodyfat')).toBeChecked()
    expect(screen.getByTestId('import-select-bmi')).toBeChecked()
    expect(screen.getByTestId('import-value-weight')).toHaveValue(86.7)
    // 同步体重/体脂到训记默认不勾选
    expect(screen.getByTestId('import-sync-xunji')).not.toBeChecked()
  })

  it('确认入库：编辑数值 + 取消勾选 + 勾选同步 → 请求体正确，成功 toast', async () => {
    const postBodies = mockFetch({ metrics: [] })
    const user = userEvent.setup()
    render(<BodyMetricsPage />)
    await screen.findByTestId('metric-form')

    await user.click(screen.getByTestId('open-image-import'))
    await user.upload(
      screen.getByTestId('scale-file-input'),
      new File(['jpg'], 'report.jpg', { type: 'image/jpeg' }),
    )
    await user.click(screen.getByTestId('extract-image-btn'))
    await screen.findByTestId('import-preview')

    // 编辑 bmi 数值、取消勾选 bodyfat、勾选同步训记
    const bmiInput = screen.getByTestId('import-value-bmi')
    await user.clear(bmiInput)
    await user.type(bmiInput, '30.1')
    await user.click(screen.getByTestId('import-select-bodyfat'))
    await user.click(screen.getByTestId('import-sync-xunji'))
    await user.click(screen.getByTestId('confirm-import-btn'))

    await vi.waitFor(() => {
      const confirmCalls = postBodies.filter((p) => p.url === '/api/body-metrics/confirm-import')
      expect(confirmCalls).toHaveLength(1)
    })
    const body = postBodies.find((p) => p.url === '/api/body-metrics/confirm-import').body
    expect(body.date).toBe('2026-08-18')
    expect(body.sync_xunji).toBe(true)
    expect(body.metrics).toEqual([
      { type: 'weight', value: 86.7, selected: true },
      { type: 'bodyfat', value: 25.5, selected: false },
      { type: 'bmi', value: 30.1, selected: true },
    ])
    expect(await screen.findByTestId('import-success')).toBeInTheDocument()
  })

  it('识别失败显示错误', async () => {
    mockFetch({ metrics: [] })
    globalThis.fetch = vi.fn((url) => {
      if (url === '/api/body-metrics/extract-image') {
        return Promise.resolve(mockResponse({ detail: '识别失败' }, 422))
      }
      if (url.startsWith('/api/body-metrics')) {
        return Promise.resolve(mockResponse({ metrics: [] }))
      }
      if (url.startsWith('/api/stats/trends')) {
        return Promise.resolve(mockResponse(EMPTY_TRENDS))
      }
      return Promise.resolve(mockResponse({ detail: 'not found' }, 404))
    })
    const user = userEvent.setup()
    render(<BodyMetricsPage />)
    await screen.findByTestId('metric-form')

    await user.click(screen.getByTestId('open-image-import'))
    await user.upload(
      screen.getByTestId('scale-file-input'),
      new File(['jpg'], 'report.jpg', { type: 'image/jpeg' }),
    )
    await user.click(screen.getByTestId('extract-image-btn'))
    expect(await screen.findByTestId('import-error')).toBeInTheDocument()
  })
})
