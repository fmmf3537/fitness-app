import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import SettingsPage from '../SettingsPage'

function mockResponse(data, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => data }
}

const LLM_SETTINGS = {
  default_llm: 'deepseek',
  providers: [
    {
      name: 'deepseek',
      base_url: 'https://api.deepseek.com',
      default_model: 'deepseek-chat',
      implemented: true,
      has_key: true,
    },
    {
      name: 'qwen',
      base_url: 'https://dashscope.aliyuncs.com',
      default_model: 'qwen-plus',
      implemented: true,
      has_key: false,
    },
  ],
}

const USAGE = {
  month: '2026-08',
  total_calls: 12,
  total_cost: 0.1234,
  by_provider: [
    {
      provider: 'deepseek',
      model: 'deepseek-chat',
      calls: 12,
      prompt_tokens: 1000,
      completion_tokens: 2000,
      cost: 0.1234,
    },
  ],
}

function installFetch({ putStatus = 200 } = {}) {
  globalThis.fetch = vi.fn((url, options = {}) => {
    if (url === '/api/settings/llm' && options.method === 'PUT') {
      if (putStatus >= 400) {
        return Promise.resolve(mockResponse({ detail: 'Key 验证失败' }, putStatus))
      }
      return Promise.resolve(
        mockResponse({ ok: true, provider: 'deepseek', default_llm: 'deepseek' }),
      )
    }
    if (url === '/api/settings/llm') {
      return Promise.resolve(mockResponse(LLM_SETTINGS))
    }
    if (url.startsWith('/api/settings/llm/usage')) {
      return Promise.resolve(mockResponse(USAGE))
    }
    return Promise.resolve(mockResponse({ detail: 'not found' }, 404))
  })
}

describe('SettingsPage', () => {
  beforeEach(() => {
    localStorage.setItem('fh_token', 'test-token')
    installFetch()
  })

  it('正常渲染 provider 列表与本月用量', async () => {
    render(<SettingsPage />)
    expect(await screen.findByTestId('llm-provider-deepseek')).toBeInTheDocument()
    expect(screen.getByTestId('llm-provider-qwen')).toBeInTheDocument()
    expect(screen.getByTestId('llm-provider-deepseek').textContent).toContain('已配置')
    expect(screen.getByTestId('llm-provider-deepseek').textContent).toContain('默认')
    expect(screen.getByTestId('llm-provider-qwen').textContent).toContain('未配置')

    expect(await screen.findByTestId('llm-usage')).toBeInTheDocument()
    expect(screen.getByTestId('usage-total-calls').textContent).toContain('12')
    expect(screen.getByTestId('usage-total-cost').textContent).toContain('0.1234')
    expect(screen.getByTestId('llm-usage').textContent).toContain('deepseek-chat')
  })

  it('输入新 Key 保存成功显示提示并发起 PUT', async () => {
    const user = userEvent.setup()
    render(<SettingsPage />)
    await screen.findByTestId('llm-provider-deepseek')

    await user.type(screen.getByTestId('key-input-deepseek'), 'sk-new-key')
    await user.click(screen.getByTestId('save-key-deepseek'))

    expect(await screen.findByText(/保存成功/)).toBeInTheDocument()
    expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/settings/llm',
      expect.objectContaining({
        method: 'PUT',
        body: JSON.stringify({ provider: 'deepseek', api_key: 'sk-new-key', set_default: false }),
      }),
    )
  })

  it('勾选设为默认后保存携带 set_default=true', async () => {
    const user = userEvent.setup()
    render(<SettingsPage />)
    await screen.findByTestId('llm-provider-qwen')

    await user.type(screen.getByTestId('key-input-qwen'), 'sk-qwen')
    await user.click(screen.getByTestId('set-default-qwen'))
    await user.click(screen.getByTestId('save-key-qwen'))

    await vi.waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        '/api/settings/llm',
        expect.objectContaining({
          method: 'PUT',
          body: JSON.stringify({ provider: 'qwen', api_key: 'sk-qwen', set_default: true }),
        }),
      )
    })
  })

  it('保存失败显示 role="alert" 错误', async () => {
    installFetch({ putStatus: 400 })
    const user = userEvent.setup()
    render(<SettingsPage />)
    await screen.findByTestId('llm-provider-deepseek')

    await user.type(screen.getByTestId('key-input-deepseek'), 'sk-bad')
    await user.click(screen.getByTestId('save-key-deepseek'))

    expect(await screen.findByRole('alert')).toBeInTheDocument()
  })

  it('设置加载失败显示错误提示', async () => {
    globalThis.fetch = vi.fn(() => Promise.resolve(mockResponse({ detail: 'boom' }, 500)))
    render(<SettingsPage />)
    expect(await screen.findByRole('alert')).toBeInTheDocument()
  })
})
