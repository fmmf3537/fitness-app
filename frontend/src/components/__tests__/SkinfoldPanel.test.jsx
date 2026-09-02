import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import SkinfoldPanel from '../SkinfoldPanel'
import { installMatchMedia } from '../../test/mockMatchMedia'

function mockResponse(data, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => data }
}

const METHODS_META = [
  {
    key: 'jp3_male',
    name_zh: 'Jackson-Pollock 3 点（男）',
    sites: [
      { key: 'chest', name_zh: '胸' },
      { key: 'abdomen', name_zh: '腹' },
      { key: 'thigh', name_zh: '大腿' },
    ],
    sex: 'male',
    self_test: 'yes',
  },
  {
    key: 'jp3_female',
    name_zh: 'Jackson-Pollock 3 点（女）',
    sites: [
      { key: 'triceps', name_zh: '肱三头' },
      { key: 'suprailiac', name_zh: '髂前上棘' },
      { key: 'thigh', name_zh: '大腿' },
    ],
    sex: 'female',
    self_test: 'assist',
  },
  {
    key: 'dw4',
    name_zh: 'Durnin-Womersley 4 点',
    sites: [
      { key: 'biceps', name_zh: '肱二头' },
      { key: 'triceps', name_zh: '肱三头' },
      { key: 'subscapular', name_zh: '肩胛下' },
      { key: 'suprailiac', name_zh: '髂前上棘' },
    ],
    sex: null,
    self_test: 'no',
  },
  {
    key: 'jp7',
    name_zh: 'Jackson-Pollock 7 点',
    sites: [
      { key: 'chest', name_zh: '胸' },
      { key: 'midaxillary', name_zh: '腋中' },
      { key: 'triceps', name_zh: '肱三头' },
      { key: 'subscapular', name_zh: '肩胛下' },
      { key: 'abdomen', name_zh: '腹' },
      { key: 'suprailiac', name_zh: '髂前上棘' },
      { key: 'thigh', name_zh: '大腿' },
    ],
    sex: null,
    self_test: 'no',
  },
]

function mockMethodsFetch({ profile = { gender: 'male', birth_date: '1990-01-01' } } = {}) {
  globalThis.fetch = vi.fn((url) => {
    if (url === '/api/skinfold/methods') {
      return Promise.resolve(mockResponse({ methods: METHODS_META, profile }))
    }
    if (url.startsWith('/api/skinfold/records')) {
      return Promise.resolve(mockResponse({ records: [] }))
    }
    return Promise.resolve(mockResponse({ detail: 'not found' }, 404))
  })
}

/** 路由皮肤 / 测量记录 / POST 提交；返回所有 POST 请求体。 */
function mockFullFetch({
  profile = { gender: 'male', birth_date: '1990-01-01' },
  records = [],
  postResponse = {
    record: {
      id: 1,
      date: '2026-09-02',
      method: 'jp3_male',
      method_zh: 'Jackson-Pollock 3 点（男）',
      sites: { chest: 8, abdomen: 18, thigh: 14 },
      density: 1.06,
      bodyfat_result: 13.61,
      note: null,
    },
    body_metric: { id: 99, date: '2026-09-02', type: 'bodyfat', value: 13.61, unit: '%' },
  },
  postStatus = 200,
} = {}) {
  const postBodies = []
  globalThis.fetch = vi.fn((url, options = {}) => {
    if (options.method === 'POST' && url === '/api/skinfold/records') {
      postBodies.push({ url, body: JSON.parse(options.body) })
      return Promise.resolve(mockResponse(postResponse, postStatus))
    }
    if (url === '/api/skinfold/methods') {
      return Promise.resolve(mockResponse({ methods: METHODS_META, profile }))
    }
    if (url.startsWith('/api/skinfold/records')) {
      return Promise.resolve(mockResponse({ records }))
    }
    return Promise.resolve(mockResponse({ detail: 'not found' }, 404))
  })
  return postBodies
}

describe('SkinfoldPanel（V4-4）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.setItem('fh_token', 'test-token')
  })

  afterEach(() => {
    installMatchMedia(false)
  })

  it('male 用户：jp3_male 卡片在推荐区，其余 3 方案折叠在更多方案内', async () => {
    mockMethodsFetch({ profile: { gender: 'male', birth_date: '1990-01-01' } })
    render(<SkinfoldPanel />)

    const jp3Male = await screen.findByTestId('method-card-jp3_male')
    expect(jp3Male).toBeInTheDocument()

    // 其他方案在「更多方案」折叠区，点开才可见
    expect(screen.queryByTestId('method-card-jp3_female')).not.toBeInTheDocument()
    expect(screen.queryByTestId('method-card-dw4')).not.toBeInTheDocument()
    expect(screen.queryByTestId('method-card-jp7')).not.toBeInTheDocument()

    const user = userEvent.setup()
    await user.click(screen.getByTestId('more-methods'))
    expect(screen.getByTestId('method-card-jp3_female')).toBeInTheDocument()
    expect(screen.getByTestId('method-card-dw4')).toBeInTheDocument()
    expect(screen.getByTestId('method-card-jp7')).toBeInTheDocument()
  })

  it('female 用户：jp3_female 推荐置顶', async () => {
    mockMethodsFetch({ profile: { gender: 'female', birth_date: '1992-05-05' } })
    render(<SkinfoldPanel />)

    expect(await screen.findByTestId('method-card-jp3_female')).toBeInTheDocument()
    expect(screen.queryByTestId('method-card-jp3_male')).not.toBeInTheDocument()
  })

  it('自测标注：jp3_male 显示 ✅ 可自测，dw4 显示 ❌ 需辅助', async () => {
    mockMethodsFetch()
    render(<SkinfoldPanel />)

    expect(await screen.findByTestId('self-test-jp3_male')).toHaveTextContent('✅ 可自测')

    const user = userEvent.setup()
    await user.click(screen.getByTestId('more-methods'))
    expect(screen.getByTestId('self-test-dw4')).toHaveTextContent('❌ 需辅助')
  })

  it('上次值回显：mock records 返回 1 条 → 部位输入框预填且显示上次测量', async () => {
    const record = {
      id: 1,
      date: '2026-08-20',
      method: 'jp3_male',
      method_zh: 'Jackson-Pollock 3 点（男）',
      sites: { chest: 8, abdomen: 18, thigh: 14 },
      density: 1.06,
      bodyfat_result: 13.5,
      note: null,
    }
    mockFullFetch({ records: [record] })
    render(<SkinfoldPanel />)

    expect(await screen.findByTestId('last-record')).toHaveTextContent(
      '上次测量：2026-08-20 · 体脂率 13.5%',
    )
    expect(screen.getByTestId('site-input-chest')).toHaveValue(8)
    expect(screen.getByTestId('site-input-abdomen')).toHaveValue(18)
    expect(screen.getByTestId('site-input-thigh')).toHaveValue(14)
  })

  it('前端校验：某部位填 1 或 61 → 显示错误且不发起 POST', async () => {
    const postBodies = mockFullFetch()
    const user = userEvent.setup()
    render(<SkinfoldPanel />)

    await screen.findByTestId('method-card-jp3_male')

    await user.type(screen.getByTestId('site-input-chest'), '1')
    await user.type(screen.getByTestId('site-input-abdomen'), '20')
    await user.type(screen.getByTestId('site-input-thigh'), '61')
    await user.click(screen.getByTestId('submit-skinfold'))

    expect(await screen.findByTestId('site-error-chest')).toBeInTheDocument()
    expect(screen.getByTestId('site-error-thigh')).toBeInTheDocument()
    expect(postBodies).toHaveLength(0)
  })

  it('成功提交：填齐合法值 → POST body 正确、成功文案展示、onSaved 被调用', async () => {
    const onSaved = vi.fn()
    const postBodies = mockFullFetch()
    const user = userEvent.setup()
    render(<SkinfoldPanel onSaved={onSaved} />)

    await screen.findByTestId('method-card-jp3_male')

    await user.type(screen.getByTestId('site-input-chest'), '8')
    await user.type(screen.getByTestId('site-input-abdomen'), '18')
    await user.type(screen.getByTestId('site-input-thigh'), '14')
    await user.click(screen.getByTestId('submit-skinfold'))

    await vi.waitFor(() => {
      expect(postBodies).toHaveLength(1)
    })
    expect(postBodies[0]).toEqual({
      url: '/api/skinfold/records',
      body: expect.objectContaining({
        method: 'jp3_male',
        sites: { chest: 8, abdomen: 18, thigh: 14 },
        date: expect.any(String),
      }),
    })
    expect(await screen.findByTestId('skinfold-success')).toHaveTextContent(
      '已保存 · 体脂率 13.61%',
    )
    expect(onSaved).toHaveBeenCalled()
  })

  it('缺资料引导：profile 字段为 null → 显示引导条 + 提交按钮禁用', async () => {
    mockMethodsFetch({ profile: { gender: null, birth_date: null } })
    render(<SkinfoldPanel />)

    expect(await screen.findByTestId('skinfold-profile-guide')).toBeInTheDocument()
    expect(screen.getByTestId('submit-skinfold')).toBeDisabled()
  })
})