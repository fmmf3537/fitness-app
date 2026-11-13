import { act, render as renderUI, screen, waitFor, within } from '@testing-library/react'
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

function catalogCallsWithCategory() {
  return globalThis.fetch.mock.calls.filter(([url]) =>
    url.startsWith('/api/exercise-mappings/catalog?') && url.includes('category='))
}

async function openEditAndFlushList(user) {
  await user.click(await screen.findByTestId('mapping-edit-1'))
  expect(await screen.findByTestId('edit-panel')).toBeInTheDocument()
  await act(async () => {
    await vi.advanceTimersByTimeAsync(300)
  })
}

describe('ExerciseMappingsExercisePicker', () => {
  beforeEach(() => {
    localStorage.setItem('fh_token', 'test-token')
    vi.useFakeTimers({ shouldAdvanceTime: true })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('test_lists_category_actions_without_typing', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    globalThis.fetch = routeFetch(defaultRoutes())
    renderPage()
    await openEditAndFlushList(user)

    await waitFor(() => {
      expect(catalogCallsWithCategory().length).toBeGreaterThan(0)
    })
    const last = catalogCallsWithCategory().at(-1)[0]
    expect(last).toContain('category=BENCH_PRESS')
    expect(last).not.toMatch(/[?&]q=/)

    expect(screen.getByTestId('edit-exercise-result-0')).toBeInTheDocument()
    expect(screen.queryByText(/请先选择 Garmin Category/)).not.toBeInTheDocument()
    expect(screen.queryByText(/没有匹配的动作/)).not.toBeInTheDocument()
  })

  it('test_shows_count_and_hint', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    globalThis.fetch = routeFetch(defaultRoutes())
    renderPage()
    await openEditAndFlushList(user)

    await waitFor(() => {
      expect(screen.getByTestId('edit-exercise-result-0')).toBeInTheDocument()
    })
    expect(screen.getByText(/Garmin 动作（\d+ 条）/)).toBeInTheDocument()
    expect(screen.getByText(/不需要手输英文名/)).toBeInTheDocument()
  })

  it('test_typing_filters_within_category', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    globalThis.fetch = routeFetch(defaultRoutes())
    renderPage()
    await openEditAndFlushList(user)

    await user.type(screen.getByTestId('edit-exercise-search'), 'Neutral')
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300)
    })

    await waitFor(() => {
      const withQ = catalogCallsWithCategory().filter(([url]) => url.includes('q='))
      expect(withQ.length).toBeGreaterThan(0)
      const last = withQ.at(-1)[0]
      expect(last).toContain('category=BENCH_PRESS')
      expect(decodeURIComponent(last)).toMatch(/[?&]q=Neutral/)
    })
  })

  it('test_click_item_fills_exercise', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    globalThis.fetch = routeFetch(defaultRoutes())
    renderPage()
    await openEditAndFlushList(user)

    await waitFor(() => {
      expect(screen.getByTestId('edit-exercise-result-1')).toBeInTheDocument()
    })
    await user.click(screen.getByTestId('edit-exercise-result-1'))

    const panel = screen.getByTestId('edit-panel')
    expect(panel).toHaveTextContent('当前：NEUTRAL_GRIP_DUMBBELL_BENCH_PRESS')
    expect(panel).toHaveTextContent('Neutral Grip Dumbbell Bench Press')
  })

  it('test_current_item_highlighted', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    globalThis.fetch = routeFetch(defaultRoutes())
    renderPage()
    await openEditAndFlushList(user)

    const currentBtn = await screen.findByTestId('edit-exercise-result-0')
    expect(within(currentBtn).getByText('当前')).toBeInTheDocument()
    expect(currentBtn.className).toMatch(/bg-brand-50/)
  })

  it('test_empty_category_shows_guidance', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    globalThis.fetch = routeFetch(defaultRoutes())
    renderPage()
    await openEditAndFlushList(user)

    await waitFor(() => {
      expect(screen.getByTestId('edit-category').querySelectorAll('option').length).toBeGreaterThan(1)
    })
    await user.selectOptions(screen.getByTestId('edit-category'), '')

    expect(await screen.findByText(/请先选择 Garmin Category/)).toBeInTheDocument()
    expect(screen.queryByTestId('edit-exercise-result-0')).not.toBeInTheDocument()
  })

  it('test_changing_category_reloads', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    globalThis.fetch = routeFetch(defaultRoutes())
    renderPage()
    await openEditAndFlushList(user)

    await waitFor(() => {
      expect(screen.getByTestId('edit-category').querySelectorAll('option').length).toBeGreaterThan(1)
    })
    const before = catalogCallsWithCategory().length
    await user.selectOptions(screen.getByTestId('edit-category'), 'SQUAT')
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300)
    })

    await waitFor(() => {
      const after = catalogCallsWithCategory().slice(before)
      expect(after.some(([url]) => url.includes('category=SQUAT'))).toBe(true)
    })
  })

  it('test_truncation_hint_when_full_page', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    const fullPage = Array.from({ length: 100 }, (_, i) => ({
      category: 'BENCH_PRESS',
      exercise: `EXERCISE_${i}`,
      name: `Exercise ${i}`,
    }))
    globalThis.fetch = routeFetch(defaultRoutes({
      catalog: (url) => {
        if (url.includes('category=')) return response(fullPage)
        return response(CATALOG)
      },
    }))
    renderPage()
    await openEditAndFlushList(user)

    expect(await screen.findByText('已显示前 100 条，可用搜索缩小范围')).toBeInTheDocument()
  })
})
