import { beforeEach, describe, expect, it, vi } from 'vitest'

const isNativePlatform = vi.fn()
const writeFile = vi.fn()
const share = vi.fn()

vi.mock('@capacitor/core', () => ({
  Capacitor: { isNativePlatform: (...args) => isNativePlatform(...args) },
}))
vi.mock('@capacitor/filesystem', () => ({
  Filesystem: { writeFile: (...args) => writeFile(...args) },
  Directory: { Cache: 'CACHE' },
}))
vi.mock('@capacitor/share', () => ({
  Share: { share: (...args) => share(...args) },
}))

import { sharePosterImage, isNativeShare } from '../sharePoster'

const DATA_URL = 'data:image/png;base64,QUJD'
const FILENAME = 'fitness-poster-2026-08-12.png'

describe('sharePosterImage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('原生端：写缓存文件后调系统分享面板', async () => {
    isNativePlatform.mockReturnValue(true)
    writeFile.mockResolvedValue({ uri: 'file:///cache/fitness-poster-2026-08-12.png' })
    share.mockResolvedValue({})

    const result = await sharePosterImage({ dataUrl: DATA_URL, filename: FILENAME, title: '训练海报' })

    expect(writeFile).toHaveBeenCalledWith({
      path: FILENAME,
      data: 'QUJD', // 去掉 dataURL 前缀后的纯 base64
      directory: 'CACHE',
      recursive: true,
    })
    expect(share).toHaveBeenCalledWith({
      title: '训练海报',
      text: '训练海报',
      url: 'file:///cache/fitness-poster-2026-08-12.png',
      dialogTitle: '分享训练海报',
    })
    expect(result).toEqual({ mode: 'native', uri: 'file:///cache/fitness-poster-2026-08-12.png' })
  })

  it('浏览器端：降级为 PNG 下载，不触碰原生插件', async () => {
    isNativePlatform.mockReturnValue(false)
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})

    const result = await sharePosterImage({ dataUrl: DATA_URL, filename: FILENAME })

    expect(click).toHaveBeenCalledTimes(1)
    expect(writeFile).not.toHaveBeenCalled()
    expect(share).not.toHaveBeenCalled()
    expect(result).toEqual({ mode: 'download' })
    click.mockRestore()
  })

  it('原生分享失败时错误向上抛出（由调用方提示）', async () => {
    isNativePlatform.mockReturnValue(true)
    writeFile.mockRejectedValue(new Error('disk full'))
    await expect(sharePosterImage({ dataUrl: DATA_URL, filename: FILENAME })).rejects.toThrow('disk full')
  })
})

describe('isNativeShare', () => {
  it('透传 Capacitor 平台判断', () => {
    isNativePlatform.mockReturnValue(true)
    expect(isNativeShare()).toBe(true)
    isNativePlatform.mockReturnValue(false)
    expect(isNativeShare()).toBe(false)
  })
})
