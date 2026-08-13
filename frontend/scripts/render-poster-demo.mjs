/**
 * V3-5 海报效果预览页生成器（开发辅助，不进运行时包）：
 * 把 src/utils/poster.js（及其依赖 status.js）内联进一个独立 HTML，
 * 用无头浏览器打开即可截图得到海报效果图。
 *
 * 用法：node scripts/render-poster-demo.mjs [输出路径.html]
 */
import { readFileSync, writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const out = process.argv[2] || join(here, 'poster-demo.html')

function inline(rel) {
  return readFileSync(join(here, '..', rel), 'utf8')
    .replace(/^import .*$/gm, '') // 去掉跨文件 import（status.js 已内联）
    .replace(/^export default /gm, '')
    .replace(/^export /gm, '')
}

const statusJs = inline('src/utils/status.js')
const posterJs = inline('src/utils/poster.js')

const demo = {
  date: '2026-08-12',
  title: '胸部训练 · 推日',
  score: 88,
  oneLiner: '卧推 100kg 稳了，下次冲 102.5，睡眠再补一小时更完美',
  volumeKg: 8240,
  durationS: 4020,
  calories: 486,
  pr: true,
}

const html = `<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>poster demo</title>
<style>body{margin:0;background:#e5e7eb;display:flex;justify-content:center;padding:24px}
canvas{width:540px;height:720px;border-radius:12px;box-shadow:0 8px 30px rgba(0,0,0,.18)}</style>
</head>
<body>
<script>
${statusJs}
${posterJs}
const data = ${JSON.stringify(demo)}
const canvas = renderPosterCanvas(data)
document.body.appendChild(canvas)
</script>
</body>
</html>
`

writeFileSync(out, html, 'utf8')
console.log(`poster demo written: ${out}`)
