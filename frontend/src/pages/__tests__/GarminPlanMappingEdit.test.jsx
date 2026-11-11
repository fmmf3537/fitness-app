import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import PlansPage from '../PlansPage'
import { ToastProvider } from '../../components/ui/Toast'

vi.mock('echarts', () => ({
  init: () => ({ setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn() }),
}))

const DATE = '2026-08-12'
const HASH_A = 'a'.repeat(64)

function response(data, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => data,
    blob: async () => new Blob(['x']),
  }
}

function makeSync(overrides = {}) {
  return {
    status: 'not_synced', phase: null, source_hash: HASH_A, synced_hash: null,
    workout_id: null, workout_schedule_id: null, attempt_count: 0,
    error_code: null, last_error: null, ...overrides,
  }
}

const GROUP = {
  source_sets: '1-2', count: 2, set_type: 'working', weight_kg: 20, reps: 8, rest_seconds: 60,
}

function makeMovements() {
  return [
    {
      name: '杠铃卧推',
      garmin_display_name: 'Barbell Bench Press',
      category: 'BENCH_PRESS',
      exerciseName: 'BENCH_PRESS',
      support_level: 'p0_verified',
      groups: [GROUP],
    },
    {
      name: '哑铃飞鸟',
      garmin_display_name: 'Dumbbell Fly',
      category: 'FLY',
      exerciseName: 'DUMBBELL_FLY',
      support_level: 'p2_verified',
      groups: [GROUP],
    },
  ]
}

function makePreview(overrides = {}) {
  return {
    source_key: `xunji-plan:v1:universal:1:${DATE}`,
    source_hash: HASH_A,
    preview_only: true,
    remote_write_eligible: true,
    sync: makeSync(),
    pending_review: [],
    stats: {
      movements: 2, sets: 4, warmup_sets: 0, working_sets: 4, repeat_groups: 2, rest_seconds: 240,
    },
    movements: makeMovements(),
    ...overrides,
  }
}

function makeUpcoming(sync = makeSync()) {
  return {
    from: DATE,
    to: DATE,
    days: [{
      date: DATE,
      is_rest: false,
      plan_ref: 'universal:1',
      plan_name: '测试计划',
      title: '胸部训练',
      movements: [{ name: '杠铃卧推', target_sets: [{ weight: 20, unit: 'kg', reps: 8 }] }],
      garmin_sync: sync,
    }],
  }
}

const MAPPING_BENCH = {
  id: 11,
  xunji_name: '杠铃卧推',
  garmin_category: 'BENCH_PRESS',
  garmin_exercise_name: 'BENCH_PRESS',
  garmin_display_name: 'Barbell Bench Press',
  weight_strategy: 'total',
  status: 'active',
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
    ['/api/plans/upcoming', overrides.upcoming ?? makeUpcoming()],
    [`/api/plans/${DATE}/garmin/preview`, overrides.preview ?? makePreview()],
    ['/api/exercise-mappings/catalog', overrides.catalog ?? CATALOG],
    ['/api/exercise-mappings/11', overrides.patch ?? MAPPING_BENCH],
    ['/api/exercise-mappings', overrides.mappings ?? { items: [MAPPING_BENCH], total: 1, page: 1, page_size: 50, pages: 1 }],
    ['/api/plans/review/', response({}, 404)],
  ]
}

function renderPage() {
  return render(
    <MemoryRouter>
      <ToastProvider>
        <PlansPage />
      </ToastProvider>
    </MemoryRouter>,
  )
}

async function openPreview(user) {
  await user.click(await screen.findByTestId(`garmin-preview-button-${DATE}`))
  await screen.findByTestId('garmin-preview-modal')
}

describe('Garmin 预览就地纠错与 draft 引导', () => {
  beforeEach(() => {
    localStorage.setItem('fh_token', 'test-token')
    vi.useFakeTimers({ shouldAdvanceTime: true })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('test_edit_button_renders_per_movement', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    globalThis.fetch = routeFetch(defaultRoutes())
    renderPage()
    await openPreview(user)
    expect(screen.getByTestId('garmin-edit-mapping-0')).toHaveTextContent('映射不对？')
    expect(screen.getByTestId('garmin-edit-mapping-1')).toHaveTextContent('映射不对？')
  })

  it('test_open_editor_shows_current_mapping', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    globalThis.fetch = routeFetch(defaultRoutes())
    renderPage()
    await openPreview(user)
    await user.click(screen.getByTestId('garmin-edit-mapping-0'))
    const current = await screen.findByTestId('edit-current-mapping')
    expect(current).toHaveTextContent('BENCH_PRESS')
    expect(current).toHaveTextContent('BENCH_PRESS')
    expect(current.textContent).toMatch(/BENCH_PRESS\s*\/\s*BENCH_PRESS/)
  })

  it('test_editor_looks_up_mapping_by_name', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    globalThis.fetch = routeFetch(defaultRoutes())
    renderPage()
    await openPreview(user)
    await user.click(screen.getByTestId('garmin-edit-mapping-0'))
    await screen.findByTestId('garmin-mapping-editor')
    await waitFor(() => {
      const lookup = globalThis.fetch.mock.calls.find(([url]) => (
        url.startsWith('/api/exercise-mappings?') && url.includes('keyword=')
      ))
      expect(lookup).toBeTruthy()
      expect(decodeURIComponent(lookup[0])).toContain('杠铃卧推')
    })
  })

  it('test_catalog_search_filters_results', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    let lastCatalogUrl = ''
    globalThis.fetch = routeFetch(defaultRoutes({
      catalog: (url) => {
        lastCatalogUrl = url
        return response(CATALOG)
      },
    }))
    renderPage()
    await openPreview(user)
    await user.click(screen.getByTestId('garmin-edit-mapping-0'))
    await screen.findByTestId('garmin-mapping-editor')
    const search = screen.getByTestId('edit-catalog-search')
    await user.clear(search)
    await user.type(search, 'Squat')
    await act(async () => { await vi.advanceTimersByTimeAsync(350) })
    await waitFor(() => {
      expect(lastCatalogUrl).toContain('/api/exercise-mappings/catalog?')
      expect(lastCatalogUrl).toContain('q=Squat')
      expect(lastCatalogUrl).toContain('limit=20')
    })
    expect(await screen.findByTestId('edit-catalog-result-0')).toBeInTheDocument()
    expect(screen.getByTestId('edit-catalog-result-2')).toHaveTextContent('Barbell Squat')
  })

  it('test_select_catalog_result_fills_selection', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    globalThis.fetch = routeFetch(defaultRoutes())
    renderPage()
    await openPreview(user)
    await user.click(screen.getByTestId('garmin-edit-mapping-0'))
    await screen.findByTestId('garmin-mapping-editor')
    await act(async () => { await vi.advanceTimersByTimeAsync(350) })
    await user.click(await screen.findByTestId('edit-catalog-result-0'))
    expect(screen.getByTestId('edit-selected')).toHaveTextContent('已选：Bench Press')
  })

  it('test_save_patches_mapping', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    let patchBody = null
    let previewCalls = 0
    globalThis.fetch = routeFetch(defaultRoutes({
      preview: () => {
        previewCalls += 1
        return response(makePreview())
      },
      patch: (url, options) => {
        if (options.method === 'PATCH') {
          patchBody = JSON.parse(options.body)
          return response({ ...MAPPING_BENCH, ...patchBody })
        }
        return response(MAPPING_BENCH)
      },
    }))
    renderPage()
    await openPreview(user)
    await user.click(screen.getByTestId('garmin-edit-mapping-0'))
    await screen.findByTestId('garmin-mapping-editor')
    await act(async () => { await vi.advanceTimersByTimeAsync(350) })
    await user.click(await screen.findByTestId('edit-catalog-result-0'))
    await user.click(screen.getByTestId('edit-save'))
    await waitFor(() => {
      expect(patchBody).toEqual(expect.objectContaining({
        garmin_category: 'BENCH_PRESS',
        garmin_exercise_name: 'BENCH_PRESS',
      }))
    })
    const patchCall = globalThis.fetch.mock.calls.find(([url, options]) => (
      url === '/api/exercise-mappings/11' && options.method === 'PATCH'
    ))
    expect(patchCall).toBeTruthy()
    await waitFor(() => {
      expect(screen.queryByTestId('garmin-mapping-editor')).not.toBeInTheDocument()
      expect(previewCalls).toBeGreaterThanOrEqual(2)
    })
  })

  it('test_save_422_shows_message', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    globalThis.fetch = routeFetch(defaultRoutes({
      patch: (url, options) => {
        if (options.method === 'PATCH') {
          return response({
            detail: { code: 'INVALID_MAPPING', message: '该目录项与动作类型不匹配' },
          }, 422)
        }
        return response(MAPPING_BENCH)
      },
    }))
    renderPage()
    await openPreview(user)
    await user.click(screen.getByTestId('garmin-edit-mapping-0'))
    await screen.findByTestId('garmin-mapping-editor')
    await act(async () => { await vi.advanceTimersByTimeAsync(350) })
    await user.click(await screen.findByTestId('edit-catalog-result-0'))
    await user.click(screen.getByTestId('edit-save'))
    expect(await screen.findByTestId('edit-error')).toHaveTextContent('该目录项与动作类型不匹配')
    expect(screen.getByTestId('edit-save')).not.toBeDisabled()
  })

  it('test_mapping_not_found_disables_save', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    globalThis.fetch = routeFetch(defaultRoutes({
      mappings: { items: [], total: 0, page: 1, page_size: 50, pages: 0 },
    }))
    renderPage()
    await openPreview(user)
    await user.click(screen.getByTestId('garmin-edit-mapping-0'))
    const editor = await screen.findByTestId('garmin-mapping-editor')
    await waitFor(() => {
      expect(within(editor).getByText(/尚无映射记录/)).toBeInTheDocument()
    })
    expect(screen.getByTestId('edit-save')).toBeDisabled()
  })

  it('test_pending_review_alert_renders', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    globalThis.fetch = routeFetch(defaultRoutes({
      preview: makePreview({
        pending_review: [
          {
            xunji_name: '杠铃卧推',
            suggested_category: 'BENCH_PRESS',
            suggested_exercise: 'BENCH_PRESS',
          },
          {
            xunji_name: '哑铃飞鸟',
            suggested_category: 'FLY',
            suggested_exercise: 'DUMBBELL_FLY',
          },
        ],
      }),
    }))
    renderPage()
    await openPreview(user)
    const alert = await screen.findByTestId('pending-review-alert')
    expect(alert).toHaveTextContent('杠铃卧推')
    expect(alert).toHaveTextContent('哑铃飞鸟')
    expect(alert).toHaveTextContent('2 个动作尚未复核映射')
  })

  it('test_pending_review_alert_hidden_when_empty', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    globalThis.fetch = routeFetch(defaultRoutes({
      preview: makePreview({ pending_review: [] }),
    }))
    renderPage()
    await openPreview(user)
    expect(screen.queryByTestId('pending-review-alert')).not.toBeInTheDocument()
  })

  it('test_mapping_not_approved_hint_on_422', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    globalThis.fetch = routeFetch(defaultRoutes({
      preview: () => response({
        detail: {
          code: 'PLAN_MAPPING_UNSUPPORTED',
          issues: [{
            code: 'MAPPING_NOT_APPROVED',
            movement: '杠铃卧推',
            message: '映射尚未复核',
          }],
        },
      }, 422),
    }))
    renderPage()
    await openPreview(user)
    expect(await screen.findByTestId('mapping-not-approved-hint')).toHaveTextContent('请先去复核')
  })

  it('test_unknown_exercise_does_not_show_approved_hint', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    globalThis.fetch = routeFetch(defaultRoutes({
      preview: () => response({
        detail: {
          code: 'PLAN_MAPPING_UNSUPPORTED',
          issues: [{
            code: 'UNKNOWN_EXERCISE',
            movement: '未知动作',
            message: '目录中找不到该动作',
          }],
        },
      }, 422),
    }))
    renderPage()
    await openPreview(user)
    await screen.findByTestId('garmin-preview-issues')
    expect(screen.queryByTestId('mapping-not-approved-hint')).not.toBeInTheDocument()
  })
})
