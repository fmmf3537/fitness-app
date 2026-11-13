import { act, render as renderUI, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ExerciseMappingsPage from '../ExerciseMappingsPage'
import { ToastProvider } from '../../components/ui/Toast'

function response(data, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => data,
  }
}

const COVERAGE = {
  total: 1091,
  by_status: { draft: 911, active: 16, disabled: 0, not_applicable: 164, missing: 0 },
  by_confidence: { high: 222, medium: 264, low: 206, none: 235, not_applicable: 164 },
  by_verified_level: { none: 1075, catalog: 0, created: 0, displayed: 16 },
  coverage: {
    with_candidate: 708,
    with_candidate_pct: 64.9,
    high: 222,
    high_pct: 20.3,
    strength_total: 927,
    strength_with_candidate: 708,
    strength_with_candidate_pct: 76.4,
  },
}

const ITEM_DRAFT = {
  id: 1,
  xunji_name: '杠铃卧推',
  garmin_category: 'BENCH_PRESS',
  garmin_exercise_name: 'BENCH_PRESS',
  garmin_display_name: 'Bench Press',
  weight_strategy: 'total',
  status: 'draft',
  confidence: 'high',
  source: 'batch',
  verified_level: 'none',
  mapping_version: 1,
  not_applicable_reason: null,
  note: null,
  candidate_count: 2,
}

const LIST_DEFAULT = {
  items: [ITEM_DRAFT],
  total: 1,
  page: 1,
  page_size: 50,
  pages: 1,
}

const CATALOG = [
  { category: 'BENCH_PRESS', exercise: 'BENCH_PRESS', name: 'Bench Press' },
  { category: 'BENCH_PRESS', exercise: 'NEUTRAL_GRIP_DUMBBELL_BENCH_PRESS', name: 'Neutral Grip Dumbbell Bench Press' },
  { category: 'BENCH_PRESS', exercise: 'INCLINE_DUMBBELL_BENCH_PRESS', name: 'Incline Dumbbell Bench Press' },
  { category: 'FLY', exercise: 'DUMBBELL_FLY', name: 'Dumbbell Fly' },
  { category: 'SQUAT', exercise: 'BARBELL_SQUAT', name: 'Barbell Squat' },
]

const XUNJI_ITEMS = [
  {
    xunji_name: '上斜哑铃卧推',
    match_rank: 0,
    category: 'BENCH_PRESS',
    exercise: 'INCLINE_DUMBBELL_BENCH_PRESS',
    name: 'Incline Dumbbell Bench Press',
    confidence: 'high',
    rank: 1,
    reason: '姿态+器械+部位命中',
  },
  {
    xunji_name: '上斜哑铃飞鸟',
    match_rank: 1,
    category: 'FLY',
    exercise: 'INCLINE_DUMBBELL_FLY',
    name: 'Incline Dumbbell Fly',
    confidence: 'medium',
    rank: 1,
    reason: '姿态+器械命中',
  },
]

function routeFetch(routes) {
  return vi.fn((url, options = {}) => {
    for (const [match, handler] of routes) {
      if (url.startsWith(match)) {
        return Promise.resolve(typeof handler === 'function' ? handler(url, options) : response(handler))
      }
    }
    return Promise.resolve(response({}, 404))
  })
}

function defaultRoutes(overrides = {}) {
  return [
    ['/api/exercise-mappings/coverage', overrides.coverage ?? COVERAGE],
    ['/api/exercise-mappings/stale-syncs', overrides.stale ?? []],
    // catalog-search-xunji 必须在 catalog 之前（startsWith）
    ['/api/exercise-mappings/catalog-search-xunji', overrides.xunji ?? { items: XUNJI_ITEMS }],
    ['/api/exercise-mappings/catalog', overrides.catalog ?? CATALOG],
    ['/api/exercise-mappings/batch-activate', overrides.batch ?? { activated: 5, skipped: 1 }],
    ['/api/exercise-mappings/1/activate', overrides.activate ?? ITEM_DRAFT],
    ['/api/exercise-mappings/1', overrides.detail ?? { ...ITEM_DRAFT, candidates: [] }],
    ['/api/exercise-mappings', overrides.list ?? LIST_DEFAULT],
  ]
}

function renderPage() {
  return renderUI(
    <MemoryRouter>
      <ToastProvider>
        <ExerciseMappingsPage />
      </ToastProvider>
    </MemoryRouter>,
  )
}

function xunjiCalls() {
  return globalThis.fetch.mock.calls.filter(([url]) =>
    url.startsWith('/api/exercise-mappings/catalog-search-xunji'))
}

function catalogQueryCalls() {
  return globalThis.fetch.mock.calls.filter(([url]) =>
    url.startsWith('/api/exercise-mappings/catalog?'))
}

async function openEditAndFlushList(user) {
  await user.click(await screen.findByTestId('mapping-edit-1'))
  expect(await screen.findByTestId('edit-panel')).toBeInTheDocument()
  await act(async () => {
    await vi.advanceTimersByTimeAsync(300)
  })
}

describe('ExerciseMappingsChineseSearch', () => {
  beforeEach(() => {
    localStorage.setItem('fh_token', 'test-token')
    vi.useFakeTimers({ shouldAdvanceTime: true })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('test_chinese_query_calls_xunji_endpoint', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    globalThis.fetch = routeFetch(defaultRoutes())
    renderPage()
    await openEditAndFlushList(user)

    const catalogBefore = catalogQueryCalls().length
    await user.type(screen.getByTestId('edit-exercise-search'), '上斜哑铃')
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300)
    })

    await waitFor(() => {
      expect(xunjiCalls().length).toBeGreaterThan(0)
    })
    const last = xunjiCalls().at(-1)[0]
    expect(decodeURIComponent(last)).toMatch(/catalog-search-xunji\?.*q=上斜哑铃/)
    const catalogAfterChinese = catalogQueryCalls().slice(catalogBefore)
    expect(catalogAfterChinese.length).toBe(0)
  })

  it('test_english_query_still_uses_catalog', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    globalThis.fetch = routeFetch(defaultRoutes())
    renderPage()
    await openEditAndFlushList(user)

    await user.type(screen.getByTestId('edit-exercise-search'), 'incline')
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300)
    })

    await waitFor(() => {
      const withQ = catalogQueryCalls().filter(([url]) => url.includes('q='))
      expect(withQ.length).toBeGreaterThan(0)
      expect(decodeURIComponent(withQ.at(-1)[0])).toMatch(/[?&]q=incline/)
    })
    expect(xunjiCalls().length).toBe(0)
  })

  it('test_chinese_result_shows_xunji_and_confidence', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    globalThis.fetch = routeFetch(defaultRoutes())
    renderPage()
    await openEditAndFlushList(user)

    await user.type(screen.getByTestId('edit-exercise-search'), '上斜哑铃')
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300)
    })

    const row0 = await screen.findByTestId('edit-exercise-result-0')
    // 训记名与箭头在同一个 span 里（"上斜哑铃卧推 → INCLINE_..."），
    // 用整行文本断言，不要用精确 getByText 拆词匹配
    expect(row0).toHaveTextContent('上斜哑铃卧推')
    expect(row0).toHaveTextContent('INCLINE_DUMBBELL_BENCH_PRESS')
    expect(screen.getByTestId('edit-exercise-confidence-0')).toHaveTextContent('high')
  })

  it('test_click_chinese_result_fills_exercise', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    globalThis.fetch = routeFetch(defaultRoutes())
    renderPage()
    await openEditAndFlushList(user)

    await user.type(screen.getByTestId('edit-exercise-search'), '上斜哑铃')
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300)
    })

    await user.click(await screen.findByTestId('edit-exercise-result-0'))

    const panel = screen.getByTestId('edit-panel')
    expect(panel).toHaveTextContent('当前：INCLINE_DUMBBELL_BENCH_PRESS')
    expect(panel).toHaveTextContent('Incline Dumbbell Bench Press')
  })

  it('test_current_mapping_pinned_to_prevent_overwrite', async () => {
    // 中文搜索返回的是算法候选，可能不如已确认的映射；
    // 当前映射必须置顶显示，避免用户误覆盖（侧平举场景）。
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    globalThis.fetch = routeFetch(defaultRoutes())
    renderPage()
    await openEditAndFlushList(user)
    await user.type(screen.getByTestId('edit-exercise-search'), '上斜哑铃')
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300)
    })
    const pinned = await screen.findByTestId('edit-exercise-current-pinned')
    expect(pinned).toHaveTextContent('当前映射')
    expect(pinned).toHaveTextContent(ITEM_DRAFT.garmin_exercise_name)
  })

  it('test_chinese_no_match_empty_state', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    globalThis.fetch = routeFetch(defaultRoutes({
      xunji: { items: [] },
    }))
    renderPage()
    await openEditAndFlushList(user)

    await user.type(screen.getByTestId('edit-exercise-search'), '完全不存在')
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300)
    })

    expect(await screen.findByText('没有匹配到训记动作，换个关键词试试')).toBeInTheDocument()
  })

  it('test_placeholder_mentions_chinese', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    globalThis.fetch = routeFetch(defaultRoutes())
    renderPage()
    await openEditAndFlushList(user)

    expect(screen.getByTestId('edit-exercise-search').placeholder).toMatch(/中文/)
  })
})
