import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiMock = vi.fn()
vi.mock('../../api/client', () => ({
  api: (...args) => apiMock(...args),
}))

vi.mock('../../utils/uuid', () => ({
  uuidv4: () => 'fixed-request-id-0001',
}))

vi.mock('../../hooks/useIsMobile', () => ({
  default: () => false,
}))

import CoachChatPage from '../CoachChatPage'

const MSG_USER = {
  id: 1,
  role: 'user',
  content: '深蹲膝盖疼怎么办？',
  model: null,
  prompt_tokens: null,
  completion_tokens: null,
  cost_estimate: null,
  created_at: '2026-09-06T10:00:00',
}

const MSG_ASSISTANT = {
  id: 2,
  role: 'assistant',
  content: '**建议**降低深度，加强髋外展',
  model: 'deepseek-chat',
  prompt_tokens: 120,
  completion_tokens: 80,
  cost_estimate: 0.002,
  created_at: '2026-09-06T10:00:05',
  context_refs: {
    recent_workouts: 3,
    upcoming_plan_days: 2,
    movement_records: ['杠铃卧推'],
    preferences: 1,
    memories: 2,
    training_data_through: '2026-09-06',
    plan_fetched_at: '2026-09-06T09:30:00',
  },
}

const POST_RESULT = {
  user_message: {
    id: 3,
    role: 'user',
    content: '下周怎么练？',
    created_at: '2026-09-06T10:05:00',
  },
  assistant_message: {
    id: 4,
    role: 'assistant',
    content: '建议减量一轮，以技术为主',
    model: 'deepseek-chat',
    prompt_tokens: 100,
    completion_tokens: 50,
    cost_estimate: 0.001,
    created_at: '2026-09-06T10:05:05',
  },
}

function renderPage() {
  return render(
    <MemoryRouter>
      <CoachChatPage />
    </MemoryRouter>,
  )
}

function mockGet(messages = []) {
  apiMock.mockImplementation((path, options = {}) => {
    if (path === '/api/coach/chat' && !options.method) {
      return Promise.resolve({ messages })
    }
    if (path === '/api/coach/chat' && options.method === 'POST') {
      return Promise.resolve(POST_RESULT)
    }
    if (path === '/api/coach/chat' && options.method === 'DELETE') {
      return Promise.resolve({ ok: true, deleted: messages.length })
    }
    return Promise.reject(new Error(`unexpected api call: ${path} ${options.method}`))
  })
}

describe('CoachChatPage', () => {
  beforeEach(() => {
    apiMock.mockReset()
  })

  it('test_renders_empty_state_when_no_messages', async () => {
    mockGet([])
    renderPage()
    expect(await screen.findByTestId('chat-empty')).toBeInTheDocument()
    expect(screen.getByText('跟教练说点什么吧')).toBeInTheDocument()
    expect(
      screen.getByText('比如「我深蹲时膝盖疼，下周训练怎么调？」'),
    ).toBeInTheDocument()
  })

  it('test_displays_messages_in_chronological_order', async () => {
    // 故意乱序返回，页面应按 created_at 正序渲染
    mockGet([MSG_ASSISTANT, MSG_USER])
    renderPage()
    await screen.findByTestId('chat-msg-user-1')
    const userEl = screen.getByTestId('chat-msg-user-1')
    const asstEl = screen.getByTestId('chat-msg-assistant-2')
    expect(
      userEl.compareDocumentPosition(asstEl) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy()
    expect(userEl).toHaveTextContent('深蹲膝盖疼怎么办？')
    expect(asstEl).toHaveTextContent('建议降低深度，加强髋外展')
    // metaLine：assistant 仅时间 +「由 AI 教练生成」，不上屏 tokens/成本
    const asstWrap = screen.getByTestId('chat-msg-wrap-assistant-2')
    expect(asstWrap.textContent).toContain('由 AI 教练生成')
    expect(asstWrap.textContent).not.toMatch(/tokens/)
    expect(asstWrap.textContent).not.toMatch(/¥/)
    expect(screen.getByTestId('chat-context-refs')).toHaveTextContent('最近 3 次训练')
    expect(screen.getByTestId('chat-context-refs')).toHaveTextContent('杠铃卧推纪录')
    expect(screen.getByTestId('chat-context-refs')).toHaveTextContent('训练数据截至 2026-09-06')
  })

  it('test_user_message_appears_on_right', async () => {
    mockGet([MSG_USER, MSG_ASSISTANT])
    renderPage()
    const userWrap = await screen.findByTestId('chat-msg-wrap-user-1')
    const asstWrap = screen.getByTestId('chat-msg-wrap-assistant-2')
    expect(userWrap.className).toMatch(/justify-end/)
    expect(asstWrap.className).toMatch(/justify-start/)
    expect(screen.getByTestId('chat-msg-user-1').className).toMatch(/bg-indigo-600/)
    expect(screen.getByTestId('chat-msg-assistant-2').className).toMatch(/bg-gray-100/)
  })

  it('test_sends_message_and_appends_to_thread', async () => {
    mockGet([])
    const user = userEvent.setup()
    renderPage()
    await screen.findByTestId('chat-empty')

    const input = screen.getByTestId('chat-input')
    await user.type(input, '下周怎么练？')
    // deferred POST：立即 resolve 会瞬时替换 pending 气泡（竞态），改为手动放行
    let resolvePost
    const postGate = new Promise((resolve) => {
      resolvePost = resolve
    })
    const baseImpl = apiMock.getMockImplementation()
    apiMock.mockImplementation((path, options = {}) => {
      if (path === '/api/coach/chat' && options.method === 'POST') {
        return postGate
      }
      return baseImpl(path, options)
    })
    await user.click(screen.getByTestId('chat-send'))

    // 乐观上屏：输入框立即清空，pending 气泡出现
    expect(input).toHaveValue('')
    const pending = await screen.findByTestId('chat-msg-user-pending-fixed-request-id-0001')
    expect(pending.className).toMatch(/opacity-70/)

    resolvePost(POST_RESULT)

    await waitFor(() => {
      expect(apiMock).toHaveBeenCalledWith(
        '/api/coach/chat',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({
            content: '下周怎么练？',
            client_request_id: 'fixed-request-id-0001',
          }),
        }),
      )
    })
    expect(await screen.findByTestId('chat-msg-user-3')).toHaveTextContent('下周怎么练？')
    expect(screen.getByTestId('chat-msg-assistant-4')).toHaveTextContent(
      '建议减量一轮，以技术为主',
    )
    expect(input).toHaveValue('')
  })

  it('test_retry_uses_same_client_request_id', async () => {
    let postCount = 0
    apiMock.mockImplementation((path, options = {}) => {
      if (path === '/api/coach/chat' && !options.method) {
        return Promise.resolve({ messages: [] })
      }
      if (path === '/api/coach/chat' && options.method === 'POST') {
        postCount += 1
        if (postCount === 1) {
          return Promise.reject({ status: 500, message: 'server error' })
        }
        return Promise.resolve(POST_RESULT)
      }
      return Promise.reject(new Error(`unexpected: ${path}`))
    })

    const user = userEvent.setup()
    renderPage()
    await screen.findByTestId('chat-empty')

    await user.type(screen.getByTestId('chat-input'), '下周怎么练？')
    await user.click(screen.getByTestId('chat-send'))

    // 失败气泡：红边 + 气泡旁重试；输入框已清空
    const failedBubble = await screen.findByTestId(
      'chat-msg-user-pending-fixed-request-id-0001',
    )
    expect(failedBubble.className).toMatch(/border-red-300/)
    expect(screen.getByTestId('chat-retry')).toBeInTheDocument()
    expect(screen.getByTestId('chat-input')).toHaveValue('')
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()

    await user.click(screen.getByTestId('chat-retry'))

    expect(await screen.findByTestId('chat-msg-assistant-4')).toBeInTheDocument()
    const postCalls = apiMock.mock.calls.filter((c) => c[1]?.method === 'POST')
    expect(postCalls).toHaveLength(2)
    const firstId = JSON.parse(postCalls[0][1].body).client_request_id
    const secondId = JSON.parse(postCalls[1][1].body).client_request_id
    expect(firstId).toBe('fixed-request-id-0001')
    expect(secondId).toBe(firstId)
  })

  it('test_clear_messages_button_calls_delete_api', async () => {
    let messages = [MSG_USER, MSG_ASSISTANT]
    apiMock.mockImplementation((path, options = {}) => {
      if (path === '/api/coach/chat' && !options.method) {
        return Promise.resolve({ messages })
      }
      if (path === '/api/coach/chat' && options.method === 'DELETE') {
        messages = []
        return Promise.resolve({ ok: true, deleted: 2 })
      }
      return Promise.reject(new Error(`unexpected: ${path}`))
    })

    const user = userEvent.setup()
    renderPage()
    await screen.findByTestId('chat-msg-user-1')

    await user.click(screen.getByTestId('chat-clear-btn'))
    expect(await screen.findByTestId('confirm-dialog')).toBeInTheDocument()
    await user.click(screen.getByTestId('confirm-dialog-confirm'))

    await waitFor(() => {
      expect(apiMock).toHaveBeenCalledWith('/api/coach/chat', { method: 'DELETE' })
    })
    expect(await screen.findByTestId('chat-empty')).toBeInTheDocument()
    expect(screen.queryByTestId('chat-msg-user-1')).not.toBeInTheDocument()
  })

  it('test_api_401_shows_not_logged_in', async () => {
    apiMock.mockRejectedValue({ status: 401, message: 'unauthorized' })
    renderPage()
    expect(await screen.findByRole('alert')).toHaveTextContent('未登录')
  })

  it('test_enter_key_sends_shift_enter_inserts_newline', async () => {
    mockGet([])
    const user = userEvent.setup()
    renderPage()
    await screen.findByTestId('chat-empty')
    const input = screen.getByTestId('chat-input')

    await user.type(input, '第一行{Shift>}{Enter}{/Shift}第二行')
    expect(apiMock.mock.calls.filter((c) => c[1]?.method === 'POST')).toHaveLength(0)
    expect(input.value).toContain('\n')

    await user.type(input, '{Enter}')
    await waitFor(() => {
      expect(apiMock.mock.calls.filter((c) => c[1]?.method === 'POST')).toHaveLength(1)
    })
    const body = JSON.parse(apiMock.mock.calls.find((c) => c[1]?.method === 'POST')[1].body)
    expect(body.content).toContain('第一行')
    expect(body.content).toContain('第二行')
  })

  it('非 embedded 渲染页首 h1「跟教练聊聊」与清空按钮', async () => {
    mockGet([])
    renderPage()
    expect(await screen.findByRole('heading', { name: '跟教练聊聊' })).toBeInTheDocument()
    expect(screen.getByTestId('chat-clear-btn')).toBeInTheDocument()
  })

  it('embedded 时不渲染页首 h1，清空按钮仍保留', async () => {
    mockGet([])
    render(
      <MemoryRouter>
        <CoachChatPage embedded />
      </MemoryRouter>,
    )
    expect(await screen.findByTestId('chat-empty')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: '跟教练聊聊' })).not.toBeInTheDocument()
    expect(screen.getByTestId('chat-clear-btn')).toBeInTheDocument()
  })
})
