import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import SettingsPage from '../SettingsPage'

function mockResponse(data, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => data }
}

const LLM_SETTINGS = {
  default_llm: 'deepseek',
  suggested_fallback: null,
  providers: [
    {
      name: 'deepseek',
      base_url: 'https://api.deepseek.com',
      default_model: 'deepseek-chat',
      implemented: true,
      has_key: true,
      consecutive_failures: 0,
    },
    {
      name: 'qwen',
      base_url: 'https://dashscope.aliyuncs.com',
      default_model: 'qwen-plus',
      implemented: true,
      has_key: false,
      consecutive_failures: 0,
    },
  ],
}

const FAILING_SETTINGS = {
  default_llm: 'deepseek',
  suggested_fallback: 'minimax',
  providers: [
    {
      name: 'deepseek',
      base_url: 'https://api.deepseek.com',
      default_model: 'deepseek-chat',
      implemented: true,
      has_key: true,
      consecutive_failures: 2,
    },
    {
      name: 'minimax',
      base_url: 'https://api.minimaxi.com',
      default_model: 'MiniMax-M2',
      implemented: true,
      has_key: true,
      consecutive_failures: 0,
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

function installFetch({
  putStatus = 200,
  settings = LLM_SETTINGS,
  deleted = [],
  profile = { gender: null, birth_date: null },
  profilePutStatus = 200,
} = {}) {
  const putBodies = []
  globalThis.fetch = vi.fn((url, options = {}) => {
    if (url === '/api/workouts/deleted') {
      return Promise.resolve(mockResponse({ workouts: deleted }))
    }
    if (url === '/api/settings/llm' && options.method === 'PUT') {
      if (putStatus >= 400) {
        return Promise.resolve(mockResponse({ detail: 'Key 验证失败' }, putStatus))
      }
      return Promise.resolve(
        mockResponse({ ok: true, provider: 'deepseek', default_llm: 'deepseek' }),
      )
    }
    if (url === '/api/settings/llm') {
      return Promise.resolve(mockResponse(settings))
    }
    if (url.startsWith('/api/settings/llm/usage')) {
      return Promise.resolve(mockResponse(USAGE))
    }
    if (url === '/api/settings/profile' && options.method === 'PUT') {
      putBodies.push(JSON.parse(options.body))
      if (profilePutStatus >= 400) {
        return Promise.resolve(
          mockResponse({ detail: '出生日期非法' }, profilePutStatus),
        )
      }
      return Promise.resolve(mockResponse(profile))
    }
    if (url === '/api/settings/profile') {
      return Promise.resolve(mockResponse(profile))
    }
    return Promise.resolve(mockResponse({ detail: 'not found' }, 404))
  })
  return { putBodies }
}

describe('SettingsPage', () => {
  beforeEach(() => {
    localStorage.setItem('fh_token', 'test-token')
    installFetch()
  })

  describe('已删除的训练（V3-11）', () => {
    const DELETED = [
      {
        id: 9,
        date: '2026-08-16',
        title: '胸部训练',
        match_status: 'auto_matched',
        deleted_at: '2026-08-19T10:00:00',
      },
    ]

    it('展示已删除列表，点击恢复后从列表消失', async () => {
      const user = userEvent.setup()
      let deleted = DELETED
      installFetch({ deleted })
      const baseFetch = globalThis.fetch
      globalThis.fetch = vi.fn((url, options = {}) => {
        if (url === '/api/workouts/deleted') {
          return Promise.resolve(mockResponse({ workouts: deleted }))
        }
        if (url === '/api/workouts/9/restore' && options.method === 'POST') {
          deleted = []
          return Promise.resolve(mockResponse({ ok: true, id: 9 }))
        }
        return baseFetch(url, options)
      })
      render(<SettingsPage />)

      const item = await screen.findByTestId('deleted-workout-9')
      expect(item).toHaveTextContent('胸部训练')
      expect(item).toHaveTextContent('2026-08-16')

      await user.click(screen.getByTestId('restore-workout-9'))

      expect(await screen.findByText(/暂无已删除的训练/)).toBeInTheDocument()
      expect(screen.queryByTestId('deleted-workout-9')).not.toBeInTheDocument()
    })

    it('无已删除训练时显示空态', async () => {
      render(<SettingsPage />)
      expect(await screen.findByText(/暂无已删除的训练/)).toBeInTheDocument()
    })
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
    // 窄屏可横向滚动：月度用量表外层包 overflow-x-auto 容器
    const usageTable = screen.getByTestId('llm-usage').querySelector('table')
    expect(usageTable.parentElement).toHaveClass('overflow-x-auto')
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

  // ---------- V2-1：三模型切换与失败降级 ----------

  it('已配置 Key 的非默认 provider 显示「设为默认」快捷按钮，点击仅切默认不传 Key', async () => {
    const withKey = {
      ...LLM_SETTINGS,
      providers: LLM_SETTINGS.providers.map((p) =>
        p.name === 'qwen' ? { ...p, has_key: true } : p,
      ),
    }
    installFetch({ settings: withKey })
    const user = userEvent.setup()
    render(<SettingsPage />)
    await screen.findByTestId('llm-provider-deepseek')

    const btn = screen.getByTestId('quick-default-qwen')
    await user.click(btn)

    await vi.waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        '/api/settings/llm',
        expect.objectContaining({
          method: 'PUT',
          body: JSON.stringify({ provider: 'qwen', api_key: '', set_default: true }),
        }),
      )
    })
  })

  it('默认 provider 不提供快捷切换按钮', async () => {
    render(<SettingsPage />)
    await screen.findByTestId('llm-provider-deepseek')
    expect(screen.queryByTestId('quick-default-deepseek')).not.toBeInTheDocument()
  })

  it('默认模型连续失败 ≥2 次时显示降级横幅，一键切备用模型', async () => {
    installFetch({ settings: FAILING_SETTINGS })
    const user = userEvent.setup()
    render(<SettingsPage />)

    const banner = await screen.findByTestId('llm-fallback-banner')
    expect(banner.textContent).toContain('deepseek')
    expect(banner.textContent).toContain('minimax')

    await user.click(screen.getByTestId('fallback-switch-btn'))
    await vi.waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        '/api/settings/llm',
        expect.objectContaining({
          method: 'PUT',
          body: JSON.stringify({ provider: 'minimax', api_key: '', set_default: true }),
        }),
      )
    })
  })

  it('无连续失败时不显示降级横幅', async () => {
    render(<SettingsPage />)
    await screen.findByTestId('llm-provider-deepseek')
    expect(screen.queryByTestId('llm-fallback-banner')).not.toBeInTheDocument()
  })

  // ---------- V4-4：个人资料（性别 + 出生日期，皮脂钳公式所需）----------

  it('profile GET 返回 male + 日期 → 输入框正确回显', async () => {
    installFetch({ profile: { gender: 'male', birth_date: '1990-04-15' } })
    render(<SettingsPage />)

    expect(await screen.findByTestId('profile-section')).toBeInTheDocument()
    expect(screen.getByTestId('profile-gender')).toHaveValue('male')
    expect(screen.getByTestId('profile-birth-date')).toHaveValue('1990-04-15')
  })

  it('profile 保存：PUT body 含 gender/birth_date → 显示「个人资料已保存」', async () => {
    const { putBodies } = installFetch({
      profile: { gender: null, birth_date: null },
    })
    const user = userEvent.setup()
    render(<SettingsPage />)
    await screen.findByTestId('profile-section')

    // 日期输入在 jsdom 下用 fireEvent.change 更稳定
    await user.selectOptions(screen.getByTestId('profile-gender'), 'male')
    fireEvent.change(screen.getByTestId('profile-birth-date'), {
      target: { value: '1990-04-15' },
    })
    await user.click(screen.getByTestId('profile-save'))

    expect(await screen.findByText(/个人资料已保存/)).toBeInTheDocument()
    expect(putBodies).toContainEqual(
      expect.objectContaining({ gender: 'male', birth_date: '1990-04-15' }),
    )
  })
})
