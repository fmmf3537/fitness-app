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

const ITEM_ACTIVE = {
  id: 2,
  xunji_name: '哑铃飞鸟',
  garmin_category: 'FLY',
  garmin_exercise_name: 'DUMBBELL_FLY',
  garmin_display_name: 'Dumbbell Fly',
  weight_strategy: 'per_hand',
  status: 'active',
  confidence: 'medium',
  source: 'user',
  verified_level: 'displayed',
  mapping_version: 2,
  not_applicable_reason: null,
  note: null,
  candidate_count: 0,
}

const ITEM_NA = {
  id: 3,
  xunji_name: '有氧慢跑',
  garmin_category: null,
  garmin_exercise_name: null,
  garmin_display_name: null,
  weight_strategy: null,
  status: 'not_applicable',
  confidence: 'none',
  source: 'batch',
  verified_level: 'none',
  mapping_version: 1,
  not_applicable_reason: 'cardio',
  note: null,
  candidate_count: 0,
}

const LIST_DEFAULT = {
  items: [ITEM_DRAFT, ITEM_ACTIVE, ITEM_NA],
  total: 3,
  page: 1,
  page_size: 50,
  pages: 2,
}

const STALE_ROW = {
  sync_id: 10,
  plan_ref: 'universal:1',
  training_date: '2026-08-12',
  workout_id: 'w1',
  workout_schedule_id: 's1',
  stored_hash: 'aaa',
  current_hash: 'bbb',
}

const CATALOG = [
  { category: 'BENCH_PRESS', exercise: 'BENCH_PRESS', name: 'Bench Press' },
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
    ['/api/exercise-mappings/2/disable', overrides.disable ?? { ...ITEM_ACTIVE, status: 'disabled' }],
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

describe('ExerciseMappingsPage', () => {
  beforeEach(() => {
    localStorage.setItem('fh_token', 'test-token')
    vi.useFakeTimers({ shouldAdvanceTime: true })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('test_renders_coverage_numbers', async () => {
    globalThis.fetch = routeFetch(defaultRoutes())
    renderPage()
    expect(await screen.findByTestId('coverage-total')).toHaveTextContent('1091')
    expect(screen.getByTestId('coverage-with-candidate')).toHaveTextContent('708')
    expect(screen.getByTestId('coverage-high')).toHaveTextContent('222')
    expect(screen.getByTestId('coverage-strength')).toHaveTextContent('708/927')
  })

  it('test_renders_list_rows', async () => {
    globalThis.fetch = routeFetch(defaultRoutes())
    renderPage()
    const row1 = await screen.findByTestId('mapping-row-1')
    expect(within(row1).getByText('杠铃卧推')).toBeInTheDocument()
    expect(within(row1).getByText('draft')).toBeInTheDocument()
    expect(within(row1).getByText('high')).toBeInTheDocument()
    expect(within(row1).getByText('总重')).toBeInTheDocument()
    expect(within(row1).getByText('2 个候选')).toBeInTheDocument()
    expect(screen.getByTestId('mapping-row-2')).toBeInTheDocument()
  })

  it('test_filter_by_status', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    globalThis.fetch = routeFetch(defaultRoutes())
    renderPage()
    await screen.findByTestId('mapping-list')
    await user.selectOptions(screen.getByTestId('filter-status'), 'draft')
    await waitFor(() => {
      const listCalls = globalThis.fetch.mock.calls.filter(([url]) =>
        url.startsWith('/api/exercise-mappings?') && url.includes('status=draft'))
      expect(listCalls.length).toBeGreaterThan(0)
    })
  })

  it('test_filter_by_confidence', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    globalThis.fetch = routeFetch(defaultRoutes())
    renderPage()
    await screen.findByTestId('mapping-list')
    await user.selectOptions(screen.getByTestId('filter-confidence'), 'high')
    await waitFor(() => {
      const listCalls = globalThis.fetch.mock.calls.filter(([url]) =>
        url.startsWith('/api/exercise-mappings?') && url.includes('confidence=high'))
      expect(listCalls.length).toBeGreaterThan(0)
    })
  })

  it('test_keyword_search', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    globalThis.fetch = routeFetch(defaultRoutes())
    renderPage()
    await screen.findByTestId('filter-keyword')
    await user.type(screen.getByTestId('filter-keyword'), '卧推')
    await act(async () => {
      await vi.advanceTimersByTimeAsync(350)
    })
    await waitFor(() => {
      const listCalls = globalThis.fetch.mock.calls.filter(([url]) =>
        url.startsWith('/api/exercise-mappings?') && url.includes('keyword='))
      expect(listCalls.some(([url]) => decodeURIComponent(url).includes('keyword=卧推'))).toBe(true)
    })
  })

  it('test_pagination_next_page', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    globalThis.fetch = routeFetch(defaultRoutes())
    renderPage()
    await screen.findByTestId('page-next')
    await user.click(screen.getByTestId('page-next'))
    await waitFor(() => {
      const listCalls = globalThis.fetch.mock.calls.filter(([url]) =>
        url.startsWith('/api/exercise-mappings?') && url.includes('page=2'))
      expect(listCalls.length).toBeGreaterThan(0)
    })
  })

  it('test_activate_button_calls_api', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    globalThis.fetch = routeFetch(defaultRoutes())
    renderPage()
    await screen.findByTestId('mapping-activate-1')
    const before = globalThis.fetch.mock.calls.length
    await user.click(screen.getByTestId('mapping-activate-1'))
    await waitFor(() => {
      const activateCalls = globalThis.fetch.mock.calls.filter(([url, options]) =>
        url.includes('/api/exercise-mappings/1/activate') && options?.method === 'POST')
      expect(activateCalls.length).toBe(1)
    })
    await waitFor(() => {
      const afterList = globalThis.fetch.mock.calls.slice(before).filter(([url]) =>
        url.startsWith('/api/exercise-mappings?') || url.startsWith('/api/exercise-mappings/coverage'))
      expect(afterList.length).toBeGreaterThan(0)
    })
  })

  it('test_activate_hidden_for_not_applicable', async () => {
    globalThis.fetch = routeFetch(defaultRoutes())
    renderPage()
    await screen.findByTestId('mapping-row-3')
    expect(screen.queryByTestId('mapping-activate-3')).not.toBeInTheDocument()
  })

  it('test_disable_button_calls_api', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    globalThis.fetch = routeFetch(defaultRoutes())
    renderPage()
    await screen.findByTestId('mapping-disable-2')
    await user.click(screen.getByTestId('mapping-disable-2'))
    await waitFor(() => {
      const disableCalls = globalThis.fetch.mock.calls.filter(([url, options]) =>
        url.includes('/api/exercise-mappings/2/disable') && options?.method === 'POST')
      expect(disableCalls.length).toBe(1)
    })
  })

  it('test_edit_panel_opens_and_saves', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    let patched = null
    globalThis.fetch = routeFetch(defaultRoutes({
      detail: (url, options) => {
        if (options?.method === 'PATCH') {
          patched = JSON.parse(options.body)
          return response({ ...ITEM_DRAFT, ...patched })
        }
        return response({ ...ITEM_DRAFT, candidates: [] })
      },
    }))
    renderPage()
    await user.click(await screen.findByTestId('mapping-edit-1'))
    expect(await screen.findByTestId('edit-panel')).toBeInTheDocument()
    await waitFor(() => {
      expect(screen.getByTestId('edit-category').querySelectorAll('option').length).toBeGreaterThan(1)
    })
    await user.selectOptions(screen.getByTestId('edit-category'), 'SQUAT')
    await user.click(screen.getByTestId('edit-save'))
    await waitFor(() => {
      expect(patched).not.toBeNull()
      expect(patched.garmin_category).toBe('SQUAT')
    })
    await waitFor(() => {
      expect(screen.queryByTestId('edit-panel')).not.toBeInTheDocument()
    })
  })

  it('test_edit_422_shows_message', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    globalThis.fetch = routeFetch(defaultRoutes({
      detail: (url, options) => {
        if (options?.method === 'PATCH') {
          return response({
            detail: { code: 'INVALID_CATEGORY', message: '类别不在 Garmin 目录中' },
          }, 422)
        }
        return response({ ...ITEM_DRAFT, candidates: [] })
      },
    }))
    renderPage()
    await user.click(await screen.findByTestId('mapping-edit-1'))
    await screen.findByTestId('edit-panel')
    await user.click(screen.getByTestId('edit-save'))
    expect(await screen.findByTestId('edit-error')).toHaveTextContent('类别不在 Garmin 目录中')
    expect(screen.getByTestId('edit-panel')).toBeInTheDocument()
  })

  it('test_batch_activate_calls_api', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    globalThis.fetch = routeFetch(defaultRoutes())
    renderPage()
    await user.click(await screen.findByTestId('batch-activate'))
    await waitFor(() => {
      const batchCalls = globalThis.fetch.mock.calls.filter(([url, options]) =>
        url.startsWith('/api/exercise-mappings/batch-activate') && options?.method === 'POST')
      expect(batchCalls.length).toBe(1)
    })
    expect(await screen.findByText(/已采纳 5 条/)).toBeInTheDocument()
  })

  it('test_stale_alert_renders_when_present', async () => {
    globalThis.fetch = routeFetch(defaultRoutes({ stale: [STALE_ROW] }))
    renderPage()
    const alert = await screen.findByTestId('stale-alert')
    expect(alert).toHaveTextContent('有 1 条已同步训练使用的映射已更新')
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    await user.click(within(alert).getByRole('button', { name: '展开' }))
    expect(screen.getByTestId('stale-list')).toHaveTextContent('universal:1')
    expect(screen.getByTestId('stale-list')).toHaveTextContent('2026-08-12')
  })

  it('test_stale_alert_hidden_when_empty', async () => {
    globalThis.fetch = routeFetch(defaultRoutes({ stale: [] }))
    renderPage()
    await screen.findByTestId('coverage-panel')
    expect(screen.queryByTestId('stale-alert')).not.toBeInTheDocument()
  })

  it('test_error_state_on_list_failure', async () => {
    globalThis.fetch = routeFetch(defaultRoutes({
      list: () => response({ detail: 'server error' }, 500),
    }))
    renderPage()
    expect(await screen.findByTestId('list-error')).toBeInTheDocument()
  })
})
