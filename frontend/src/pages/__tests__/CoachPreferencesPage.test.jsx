import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiMock = vi.fn()
vi.mock('../../api/client', () => ({
  api: (...args) => apiMock(...args),
}))

import CoachPreferencesPage from '../CoachPreferencesPage'

const PREF = {
  id: 1,
  content: '右膝半月板损伤，深蹲忌讳过深',
  category: 'manual',
  tags: '伤病,忌讳',
  source: 'user',
  active: true,
  created_at: '2026-09-01T10:00:00',
  updated_at: '2026-09-01T10:00:00',
}

const DRAFT = {
  id: 10,
  content: '偏好高蛋白饮食',
  tags: '营养',
  source: 'ai_extract',
  status: 'pending',
  created_at: '2026-09-05T08:00:00',
  resolved_at: null,
}

function renderPage() {
  return render(
    <MemoryRouter>
      <CoachPreferencesPage />
    </MemoryRouter>,
  )
}

function mockLoad({ preferences = [], drafts = [] } = {}) {
  apiMock.mockImplementation((path, options = {}) => {
    if (path === '/api/coach/preferences' && !options.method) {
      return Promise.resolve({ preferences })
    }
    if (path === '/api/coach/drafts' && !options.method) {
      return Promise.resolve({ drafts })
    }
    if (path === '/api/coach/preferences' && options.method === 'POST') {
      return Promise.resolve({ ...PREF, id: 2, content: JSON.parse(options.body).content })
    }
    if (path.startsWith('/api/coach/preferences/') && options.method === 'PUT') {
      return Promise.resolve({ ...PREF, ...JSON.parse(options.body) })
    }
    if (path.startsWith('/api/coach/preferences/') && options.method === 'DELETE') {
      return Promise.resolve({ ok: true })
    }
    if (path.endsWith('/accept') && options.method === 'POST') {
      return Promise.resolve({ preference: PREF })
    }
    if (path.endsWith('/reject') && options.method === 'POST') {
      return Promise.resolve({ ok: true })
    }
    return Promise.reject(new Error(`unexpected api call: ${path} ${options.method}`))
  })
}

describe('CoachPreferencesPage', () => {
  beforeEach(() => {
    apiMock.mockReset()
    vi.spyOn(window, 'confirm').mockReturnValue(true)
  })

  it('test_renders_empty_state_when_no_preferences', async () => {
    mockLoad({ preferences: [], drafts: [] })
    renderPage()
    expect(
      await screen.findByText(
        /暂无须知。在下方添加你的长期偏好（如伤病\/忌讳\/目标），AI 会在下次点评时参考。/,
      ),
    ).toBeInTheDocument()
    expect(screen.queryByTestId('drafts-section')).not.toBeInTheDocument()
  })

  it('test_displays_existing_preferences_with_metadata', async () => {
    mockLoad({ preferences: [PREF], drafts: [] })
    renderPage()
    const item = await screen.findByTestId('preference-1')
    expect(item).toHaveTextContent('右膝半月板损伤，深蹲忌讳过深')
    expect(item).toHaveTextContent('伤病,忌讳')
    expect(item).toHaveTextContent('user')
    expect(item).toHaveTextContent('manual')
  })

  it('test_creates_new_preference_via_modal', async () => {
    let preferences = []
    apiMock.mockImplementation((path, options = {}) => {
      if (path === '/api/coach/preferences' && !options.method) {
        return Promise.resolve({ preferences })
      }
      if (path === '/api/coach/drafts' && !options.method) {
        return Promise.resolve({ drafts: [] })
      }
      if (path === '/api/coach/preferences' && options.method === 'POST') {
        const body = JSON.parse(options.body)
        preferences = [
          {
            ...PREF,
            id: 2,
            content: body.content,
            tags: body.tags,
          },
        ]
        return Promise.resolve(preferences[0])
      }
      return Promise.reject(new Error(`unexpected: ${path}`))
    })

    const user = userEvent.setup()
    renderPage()
    await screen.findByText(/暂无须知/)

    await user.click(screen.getByTestId('create-preference-btn'))
    expect(screen.getByTestId('preference-modal')).toBeInTheDocument()
    await user.type(screen.getByTestId('pref-content-input'), '每周三次力量训练')
    await user.click(screen.getByTestId('pref-save-btn'))

    await waitFor(() => {
      expect(apiMock).toHaveBeenCalledWith(
        '/api/coach/preferences',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ content: '每周三次力量训练', tags: null }),
        }),
      )
    })
    expect(await screen.findByText('每周三次力量训练')).toBeInTheDocument()
  })

  it('test_deletes_preference_with_confirmation', async () => {
    let preferences = [PREF]
    apiMock.mockImplementation((path, options = {}) => {
      if (path === '/api/coach/preferences' && !options.method) {
        return Promise.resolve({ preferences })
      }
      if (path === '/api/coach/drafts' && !options.method) {
        return Promise.resolve({ drafts: [] })
      }
      if (path === '/api/coach/preferences/1' && options.method === 'DELETE') {
        preferences = []
        return Promise.resolve({ ok: true })
      }
      return Promise.reject(new Error(`unexpected: ${path}`))
    })

    const user = userEvent.setup()
    renderPage()
    await screen.findByTestId('preference-1')

    await user.click(screen.getByTestId('delete-preference-1'))
    expect(window.confirm).toHaveBeenCalledWith('确定删除该须知？')

    await waitFor(() => {
      expect(apiMock).toHaveBeenCalledWith('/api/coach/preferences/1', {
        method: 'DELETE',
      })
    })
    expect(await screen.findByText(/暂无须知/)).toBeInTheDocument()
    expect(screen.queryByTestId('preference-1')).not.toBeInTheDocument()
  })

  it('test_displays_pending_drafts_when_present', async () => {
    mockLoad({ preferences: [], drafts: [DRAFT] })
    renderPage()
    expect(await screen.findByTestId('drafts-section')).toBeInTheDocument()
    expect(screen.getByText('AI 草稿（待确认）')).toBeInTheDocument()
    const draft = screen.getByTestId('draft-10')
    expect(draft).toHaveTextContent('偏好高蛋白饮食')
    expect(screen.getByTestId('accept-draft-10')).toBeInTheDocument()
    expect(screen.getByTestId('reject-draft-10')).toBeInTheDocument()
  })

  it('test_accepts_draft_calls_api_and_reloads', async () => {
    let drafts = [DRAFT]
    let preferences = []
    apiMock.mockImplementation((path, options = {}) => {
      if (path === '/api/coach/preferences' && !options.method) {
        return Promise.resolve({ preferences })
      }
      if (path === '/api/coach/drafts' && !options.method) {
        return Promise.resolve({ drafts })
      }
      if (path === '/api/coach/drafts/10/accept' && options.method === 'POST') {
        drafts = []
        preferences = [{ ...PREF, content: DRAFT.content, tags: DRAFT.tags, source: 'ai_extract' }]
        return Promise.resolve({ preference: preferences[0] })
      }
      return Promise.reject(new Error(`unexpected: ${path}`))
    })

    const user = userEvent.setup()
    renderPage()
    await screen.findByTestId('draft-10')

    await user.click(screen.getByTestId('accept-draft-10'))

    await waitFor(() => {
      expect(apiMock).toHaveBeenCalledWith('/api/coach/drafts/10/accept', { method: 'POST' })
    })
    expect(await screen.findByText('已采纳')).toBeInTheDocument()
    expect(screen.queryByTestId('draft-10')).not.toBeInTheDocument()
    expect(await screen.findByText('偏好高蛋白饮食')).toBeInTheDocument()
  })

  it('test_rejects_draft_calls_api_and_reloads', async () => {
    let drafts = [DRAFT]
    apiMock.mockImplementation((path, options = {}) => {
      if (path === '/api/coach/preferences' && !options.method) {
        return Promise.resolve({ preferences: [] })
      }
      if (path === '/api/coach/drafts' && !options.method) {
        return Promise.resolve({ drafts })
      }
      if (path === '/api/coach/drafts/10/reject' && options.method === 'POST') {
        drafts = []
        return Promise.resolve({ ok: true })
      }
      return Promise.reject(new Error(`unexpected: ${path}`))
    })

    const user = userEvent.setup()
    renderPage()
    await screen.findByTestId('draft-10')

    await user.click(screen.getByTestId('reject-draft-10'))

    await waitFor(() => {
      expect(apiMock).toHaveBeenCalledWith('/api/coach/drafts/10/reject', { method: 'POST' })
    })
    expect(await screen.findByText('已忽略')).toBeInTheDocument()
    expect(screen.queryByTestId('drafts-section')).not.toBeInTheDocument()
  })

  it('test_api_401_shows_not_logged_in', async () => {
    apiMock.mockRejectedValue({ status: 401, message: 'unauthorized' })
    renderPage()
    expect(await screen.findByRole('alert')).toHaveTextContent('未登录')
  })

  it('test_edit_modal_prefills_existing_values', async () => {
    mockLoad({ preferences: [PREF], drafts: [] })
    const user = userEvent.setup()
    renderPage()
    await screen.findByTestId('preference-1')

    await user.click(screen.getByTestId('edit-preference-1'))
    expect(screen.getByTestId('preference-modal')).toBeInTheDocument()
    expect(screen.getByTestId('pref-content-input')).toHaveValue(PREF.content)
    expect(screen.getByTestId('pref-tags-input')).toHaveValue(PREF.tags)
  })
})
