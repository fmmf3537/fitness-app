/**
 * V3-8b：跨环境 UUID v4 生成。
 *
 * 背景：crypto.randomUUID() 仅在安全上下文（HTTPS / localhost）可用，
 * 本项目 APP 与浏览器走 HTTP 明文（WebView 非安全上下文），
 * 直接调用会同步抛 TypeError（曾导致追问发送按钮真机"点不动"）。
 *
 * 降级链：crypto.randomUUID → crypto.getRandomValues 手工构造
 * （非安全上下文也可用，版本位/变体位按 RFC 4122 设置）→ Math.random 兜底
 * （仅作幂等键用途，可接受）。
 */
export function uuidv4() {
  if (
    typeof crypto !== 'undefined' &&
    typeof crypto.randomUUID === 'function'
  ) {
    return crypto.randomUUID()
  }
  const bytes = new Uint8Array(16)
  if (
    typeof crypto !== 'undefined' &&
    typeof crypto.getRandomValues === 'function'
  ) {
    crypto.getRandomValues(bytes)
  } else {
    for (let i = 0; i < bytes.length; i++) {
      bytes[i] = Math.floor(Math.random() * 256)
    }
  }
  bytes[6] = (bytes[6] & 0x0f) | 0x40 // version 4
  bytes[8] = (bytes[8] & 0x3f) | 0x80 // variant 10xx
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0'))
  return (
    hex.slice(0, 4).join('') +
    '-' +
    hex.slice(4, 6).join('') +
    '-' +
    hex.slice(6, 8).join('') +
    '-' +
    hex.slice(8, 10).join('') +
    '-' +
    hex.slice(10).join('')
  )
}
