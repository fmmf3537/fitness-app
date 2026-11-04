import { spawn } from 'node:child_process'
import { mkdtempSync, rmSync, writeFileSync, mkdirSync } from 'node:fs'
import path from 'node:path'

const root = process.cwd()
const chromePath = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
const vitePort = 7100
const debugPort = 9223
const profile = mkdtempSync(path.join(root, '.rematch-browser-'))
let vite
let chrome
let ws

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))
async function waitFor(url, timeout = 20000) {
  const start = Date.now()
  while (Date.now() - start < timeout) {
    try {
      const response = await fetch(url)
      if (response.ok) return response
    } catch { /* startup retry */ }
    await sleep(150)
  }
  throw new Error(`Timed out waiting for ${url}`)
}

class Cdp {
  constructor(socket) {
    this.socket = socket
    this.id = 0
    this.pending = new Map()
    this.errors = []
    socket.addEventListener('message', (event) => {
      const message = JSON.parse(event.data)
      if (message.id) {
        const pending = this.pending.get(message.id)
        if (!pending) return
        this.pending.delete(message.id)
        if (message.error) pending.reject(new Error(JSON.stringify(message.error)))
        else pending.resolve(message.result)
      }
      if (message.method === 'Runtime.exceptionThrown') {
        this.errors.push(message.params.exceptionDetails.text)
      }
    })
  }
  send(method, params = {}) {
    const id = ++this.id
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject })
      this.socket.send(JSON.stringify({ id, method, params }))
    })
  }
  async eval(expression) {
    const result = await this.send('Runtime.evaluate', {
      expression, returnByValue: true, awaitPromise: true,
    })
    if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails))
    return result.result.value
  }
  async waitText(text, present = true, timeout = 10000) {
    const start = Date.now()
    while (Date.now() - start < timeout) {
      const found = await this.eval(`document.body.innerText.includes(${JSON.stringify(text)})`)
      if (found === present) return
      await sleep(150)
    }
    throw new Error(`Timed out waiting for text ${text} present=${present}`)
  }
}

const candidate = {
  id: 2,
  reason: 'garmin_only_strength',
  status: 'pending',
  created_at: '2026-08-03T12:00:00',
  workout_id: 2,
  xunji_train: null,
  garmin_activity: {
    id: 2, activity_id: 'g1', activity_type: 'strength_training', name: '力量训练',
    start_ts: '2026-08-03T10:05:00', end_ts: '2026-08-03T11:00:00',
    duration_s: 3300, calories: 300, avg_hr: 118, max_hr: 150,
  },
}
const xunji = {
  id: 1, datestr: '2026-08-03', title: '胸', start_ms: 1754224800000, end_ms: 1754228400000,
}

try {
  vite = spawn(process.execPath, [
    path.join(root, 'node_modules/vite/bin/vite.js'),
    '--host', '127.0.0.1', '--port', String(vitePort), '--strictPort',
  ], { cwd: root, stdio: 'ignore' })
  await waitFor(`http://127.0.0.1:${vitePort}/`)

  chrome = spawn(chromePath, [
    '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
    `--remote-debugging-port=${debugPort}`, `--user-data-dir=${profile}`, 'about:blank',
  ], { stdio: 'ignore' })
  await waitFor(`http://127.0.0.1:${debugPort}/json/version`)
  const pages = await (await fetch(`http://127.0.0.1:${debugPort}/json/list`)).json()
  const page = pages.find((item) => item.type === 'page')
  ws = new WebSocket(page.webSocketDebuggerUrl)
  await new Promise((resolve, reject) => {
    ws.addEventListener('open', resolve, { once: true })
    ws.addEventListener('error', reject, { once: true })
  })
  const cdp = new Cdp(ws)
  await cdp.send('Page.enable')
  await cdp.send('Runtime.enable')
  await cdp.send('Emulation.setDeviceMetricsOverride', {
    width: 390, height: 844, deviceScaleFactor: 1, mobile: true,
  })
  await cdp.send('Page.addScriptToEvaluateOnNewDocument', {
    source: `
      localStorage.setItem('fh_token', 'browser-test-token');
      localStorage.setItem('fh_onboarding_v1_done', '1');
      window.__rematchConfirmed = false;
      const candidate = ${JSON.stringify(candidate)};
      const xunji = ${JSON.stringify(xunji)};
      const json = (body, status = 200) => Promise.resolve({
        ok: status >= 200 && status < 300, status,
        json: () => Promise.resolve(body),
      });
      window.fetch = (input) => {
        const url = String(input);
        if (url.includes('/rematch/preview')) return json({
          action: 'merge', reason: 'auto', overlap_ratio: 1,
          xunji_workout_id: 1, garmin_workout_id: 2, keep_workout_id: 1,
          xunji_train: xunji, garmin_activity: candidate.garmin_activity,
          workout: { date: '2026-08-03', title: '胸', duration_s: 3300 },
        });
        if (url.endsWith('/api/workouts/rematch')) {
          window.__rematchConfirmed = true;
          return json({ action: 'merge', workout_id: 1 });
        }
        if (url.includes('/api/match-candidates')) {
          return json({ candidates: window.__rematchConfirmed ? [] : [candidate] });
        }
        if (url.includes('/api/sync/status')) {
          return json({ running: false, status: null });
        }
        return json({});
      };
    `,
  })
  await cdp.send('Page.navigate', { url: `http://127.0.0.1:${vitePort}/candidates` })
  await cdp.waitText('重新匹配')
  const initial = await cdp.eval(`({
    rematch: document.body.innerText.includes('重新匹配'),
    dismiss: document.body.innerText.includes('无需补录'),
    merge: [...document.querySelectorAll('button')].some(b => b.textContent.trim() === '合并'),
    overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth,
  })`)
  await cdp.eval(`[...document.querySelectorAll('button')].find(b => b.textContent.trim() === '重新匹配').click()`)
  await cdp.waitText('重新匹配预览')
  const preview = await cdp.eval(`({
    title: document.body.innerText.includes('胸部训练') || document.body.innerText.includes('胸'),
    overlap: document.body.innerText.includes('时间重叠 100%'),
    dialog: Boolean(document.querySelector('[data-testid="rematch-preview"]')),
    overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth,
  })`)
  mkdirSync(path.join(root, '..', 'outputs'), { recursive: true })
  const screenshot = await cdp.send('Page.captureScreenshot', { format: 'png' })
  const screenshotPath = path.join(root, '..', 'outputs', 'rematch-preview-mobile.png')
  writeFileSync(screenshotPath, Buffer.from(screenshot.data, 'base64'))
  await cdp.eval(`[...document.querySelectorAll('button')].find(b => b.textContent.trim() === '确认合并').click()`)
  await cdp.waitText('没有待确认的候选')
  const completed = await cdp.eval(`({
    confirmed: window.__rematchConfirmed,
    empty: document.body.innerText.includes('没有待确认的候选'),
  })`)
  if (!initial.rematch || !initial.dismiss || initial.merge || initial.overflow) {
    throw new Error(`Initial UI assertion failed: ${JSON.stringify(initial)}`)
  }
  if (!preview.dialog || !preview.overlap || preview.overflow) {
    throw new Error(`Preview UI assertion failed: ${JSON.stringify(preview)}`)
  }
  if (!completed.confirmed || !completed.empty || cdp.errors.length) {
    throw new Error(`Completion assertion failed: ${JSON.stringify({ completed, errors: cdp.errors })}`)
  }
  console.log(JSON.stringify({ ok: true, initial, preview, completed, screenshotPath }, null, 2))
  await cdp.send('Browser.close')
} finally {
  if (ws) ws.close()
  if (chrome && chrome.exitCode === null) chrome.kill()
  if (vite && vite.exitCode === null) vite.kill()
  await sleep(300)
  rmSync(profile, { recursive: true, force: true })
}
