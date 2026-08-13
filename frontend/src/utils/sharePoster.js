/**
 * V3-5 海报分享出口：
 * - 原生端（Capacitor.isNativePlatform()）：写缓存文件后调系统分享面板
 *   （可直发微信/朋友圈；缓存目录分享走 Capacitor 模板内置 FileProvider，无需额外权限）；
 * - 浏览器端降级：触发 PNG 下载。
 */
import { Capacitor } from '@capacitor/core'
import { Filesystem, Directory } from '@capacitor/filesystem'
import { Share } from '@capacitor/share'

/** 当前平台是否走原生分享（用于按钮文案等） */
export function isNativeShare() {
  return Capacitor.isNativePlatform()
}

/** 浏览器端降级：dataURL 触发下载 */
export function downloadDataUrl(dataUrl, filename) {
  const a = document.createElement('a')
  a.href = dataUrl
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
}

/**
 * 分享海报图片。
 * @returns {Promise<{mode: 'native', uri: string} | {mode: 'download'}>}
 */
export async function sharePosterImage({ dataUrl, filename = 'fitness-poster.png', title = '训练海报' }) {
  if (Capacitor.isNativePlatform()) {
    const base64 = String(dataUrl).split(',')[1] || ''
    const saved = await Filesystem.writeFile({
      path: filename,
      data: base64,
      directory: Directory.Cache,
      recursive: true,
    })
    await Share.share({
      title,
      text: title,
      url: saved.uri,
      dialogTitle: '分享训练海报',
    })
    return { mode: 'native', uri: saved.uri }
  }
  downloadDataUrl(dataUrl, filename)
  return { mode: 'download' }
}
