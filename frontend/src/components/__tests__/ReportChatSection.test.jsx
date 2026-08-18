import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ReportChatSection from '../ReportChatSection'

function mockResponse(data, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => data }
}

const HISTORY = {
  messages: [
    {
      id: 1,
      report_id: 7,
      role: 'user',
      content: '这次强度够吗？',
      created_at: '2026-08-03T23:10:00',
    },
    {
      id: 2,
      report_id: 7,
      role: 'assistant',
      content: '**强度足够**，注意恢复',
      model: 'deepseek-chat',
      prompt_tokens: 100,
      completion_tokens: 50,
      created_at: '2026-08-03T23:10:05',
    },
  ],
}

const POST_RESULT = {
  user_message: { id: 3, report_id: 7, role: 'user', content: '下次怎么加重？' },
  assistant_message: { id: 4, report_id: 7, role: 'assistant', content: '建议下次加 2.5kg' },
}

describe('ReportChatSection', () => {
  beforeEach(() => {
    localStorage.setItem('fh_token', 'test-token')
    globalThis.fetch = vi.fn((url, options) => {
      if (options?.method === 'POST') return Promise.resolve(mockResponse(POST_RESULT))
      return Promise.resolve(mockResponse(HISTORY))
    })
  })

  it('空态折叠：默认只显示入口，展开后拉取历史并渲染气泡', async () => {
    const user = userEvent.setup()
    render(<ReportChatSection reportId={7} />)
    expect(screen.getByTestId('chat-expand-btn')).toBeInTheDocument()
    expect(screen.queryByTestId('chat-input')).not.toBeInTheDocument()
    expect(globalThis.fetch).not.toHaveBeenCalled()

    await user.click(screen.getByTestId('chat-expand-btn'))

    expect(await screen.findByTestId('chat-thread')).toBeInTheDocument()
    expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/ai-reports/7/messages',
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: 'Bearer test-token' }),
      }),
    )
    // 用户右气泡 / assistant 左气泡
    expect(screen.getByTestId('chat-msg-user-1')).toHaveTextContent('这次强度够吗？')
    const assistantBubble = screen.getByTestId('chat-msg-assistant-2')
    expect(assistantBubble).toHaveTextContent('强度足够')
    expect(assistantBubble.querySelector('strong')).toHaveTextContent('强度足够')
  })

  it('发送流转：POST 携带 content 与 client_request_id，回复上屏且输入框清空', async () => {
    const user = userEvent.setup()
    render(<ReportChatSection reportId={7} />)
    await user.click(screen.getByTestId('chat-expand-btn'))
    const input = await screen.findByTestId('chat-input')

    await user.type(input, '下次怎么加重？')
    await user.click(screen.getByTestId('chat-send'))

    expect(await screen.findByTestId('chat-msg-user-3')).toBeInTheDocument()
    expect(screen.getByTestId('chat-msg-assistant-4')).toHaveTextContent('建议下次加 2.5kg')
    const postCall = globalThis.fetch.mock.calls.find((c) => c[1]?.method === 'POST')
    expect(postCall[0]).toBe('/api/ai-reports/7/messages')
    const body = JSON.parse(postCall[1].body)
    expect(body.content).toBe('下次怎么加重？')
    expect(body.client_request_id).toBeTruthy()
    expect(input).toHaveValue('')
  })

  it('回车发送、Shift+回车换行不发送', async () => {
    const user = userEvent.setup()
    render(<ReportChatSection reportId={7} />)
    await user.click(screen.getByTestId('chat-expand-btn'))
    const input = await screen.findByTestId('chat-input')

    await user.type(input, '第一行{Shift>}{Enter}{/Shift}第二行')
    expect(globalThis.fetch.mock.calls.filter((c) => c[1]?.method === 'POST')).toHaveLength(0)

    await user.type(input, '{Enter}')
    expect(await screen.findByTestId('chat-msg-user-3')).toBeInTheDocument()
    const postCall = globalThis.fetch.mock.calls.find((c) => c[1]?.method === 'POST')
    expect(JSON.parse(postCall[1].body).content).toContain('第一行')
  })

  it('发送中显示「教练思考中」且按钮禁用', async () => {
    let resolvePost
    globalThis.fetch = vi.fn((url, options) => {
      if (options?.method === 'POST') {
        return new Promise((resolve) => {
          resolvePost = () => resolve(mockResponse(POST_RESULT))
        })
      }
      return Promise.resolve(mockResponse(HISTORY))
    })
    const user = userEvent.setup()
    render(<ReportChatSection reportId={7} />)
    await user.click(screen.getByTestId('chat-expand-btn'))
    const input = await screen.findByTestId('chat-input')

    await user.type(input, '问题')
    await user.click(screen.getByTestId('chat-send'))

    expect(await screen.findByTestId('chat-thinking')).toHaveTextContent('教练思考中')
    expect(screen.getByTestId('chat-send')).toBeDisabled()

    resolvePost()
    expect(await screen.findByTestId('chat-msg-assistant-4')).toBeInTheDocument()
    expect(screen.queryByTestId('chat-thinking')).not.toBeInTheDocument()
    // 发送结束、输入框已清空，按钮恢复「发送」文案（空输入时禁用属预期）
    expect(screen.getByTestId('chat-send')).toHaveTextContent('发送')
  })

  it('发送失败可重试，重试复用同一 client_request_id', async () => {
    let postCount = 0
    globalThis.fetch = vi.fn((url, options) => {
      if (options?.method === 'POST') {
        postCount += 1
        if (postCount === 1) return Promise.resolve(mockResponse({ detail: 'bad' }, 500))
        return Promise.resolve(mockResponse(POST_RESULT))
      }
      return Promise.resolve(mockResponse(HISTORY))
    })
    const user = userEvent.setup()
    render(<ReportChatSection reportId={7} />)
    await user.click(screen.getByTestId('chat-expand-btn'))
    const input = await screen.findByTestId('chat-input')

    await user.type(input, '问题')
    await user.click(screen.getByTestId('chat-send'))

    expect(await screen.findByRole('alert')).toBeInTheDocument()
    const retry = await screen.findByTestId('chat-retry')
    await user.click(retry)

    expect(await screen.findByTestId('chat-msg-assistant-4')).toBeInTheDocument()
    const postCalls = globalThis.fetch.mock.calls.filter((c) => c[1]?.method === 'POST')
    expect(postCalls).toHaveLength(2)
    const firstId = JSON.parse(postCalls[0][1].body).client_request_id
    const secondId = JSON.parse(postCalls[1][1].body).client_request_id
    expect(secondId).toBe(firstId)
  })

  it('空白内容不发送', async () => {
    const user = userEvent.setup()
    render(<ReportChatSection reportId={7} />)
    await user.click(screen.getByTestId('chat-expand-btn'))
    await screen.findByTestId('chat-input')

    await user.click(screen.getByTestId('chat-send'))
    expect(globalThis.fetch.mock.calls.filter((c) => c[1]?.method === 'POST')).toHaveLength(0)
  })

  it('切换报告后对话状态重置（折叠 + 清空）', async () => {
    const user = userEvent.setup()
    const { rerender } = render(<ReportChatSection reportId={7} />)
    await user.click(screen.getByTestId('chat-expand-btn'))
    expect(await screen.findByTestId('chat-thread')).toBeInTheDocument()

    rerender(<ReportChatSection reportId={8} />)

    expect(screen.queryByTestId('chat-thread')).not.toBeInTheDocument()
    expect(screen.getByTestId('chat-expand-btn')).toBeInTheDocument()
  })
})
