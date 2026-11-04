import { spawn } from 'node:child_process'
import { mkdtempSync, rmSync, writeFileSync, mkdirSync } from 'node:fs'
import path from 'node:path'

const root = process.cwd()
const chromePath = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
const vitePort = 7100
const debugPort = 9223
const profile = mkdtempSync(path.join(root, '.settings-browser-'))
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

async function assertPortFree(port) {
  try {
    await fetch(`http://127.0.0.1:${port}/`, { signal: AbortSignal.timeout(1000) })
    throw new Error(`Port ${port} is already in use`)
  } catch (error) {
    if (error.message.includes('already in use')) throw error
  }
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
  async waitFor(expression, timeout = 10000) {
    const start = Date.now()
    while (Date.now() - start < timeout) {
      if (await this.eval(expression)) return
      await sleep(150)
    }
    throw new Error(`Timed out waiting for ${expression}`)
  }
}

const kimiProvider = {
  name: 'kimi',
  base_url: 'https://api.moonshot.cn/v1',
  default_model: 'kimi-k3.1-pro',
  selected_model: 'kimi-k3.1-pro',
  implemented: true,
  has_key: true,
  consecutive_failures: 0,
  models: [
    {
      id: 'kimi-k3.1-pro', label: 'Kimi K3.1 Pro（推荐）',
      prompt: 13, completion: 68, cached_prompt: 1.3,
      cache_write_5m: 13, cache_write_1h: 26,
    },
    {
      id: 'kimi-k3.1-pro-highspeed', label: 'Kimi K3.1 Pro 高速版',
      prompt: 26, completion: 136, cached_prompt: 1.3,
      cache_write_5m: 26, cache_write_1h: 52,
    },
    {
      id: 'kimi-k3', label: 'Kimi K3（3.0）',
      prompt: 20, completion: 100, cached_prompt: 2,
      cache_write_5m: 20, cache_write_1h: 40,
    },
  ],
}

try {
  await assertPortFree(vitePort)
  await assertPortFree(debugPort)
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
  await cdp.send('Emulation.setEmulatedMedia', {
    features: [{ name: 'prefers-reduced-motion', value: 'reduce' }],
  })
  await cdp.send('Page.addScriptToEvaluateOnNewDocument', {
    source: `
      localStorage.setItem('fh_token', 'browser-test-token');
      localStorage.setItem('fh_onboarding_v1_done', '1');
      window.__modelPutBodies = [];
      const provider = ${JSON.stringify(kimiProvider)};
      const json = (body, status = 200) => Promise.resolve({
        ok: status >= 200 && status < 300, status,
        json: () => Promise.resolve(body),
      });
      window.fetch = (input, options = {}) => {
        const url = String(input);
        if (url === '/api/settings/llm' && options.method === 'PUT') {
          const body = JSON.parse(options.body);
          window.__modelPutBodies.push(body);
          provider.selected_model = body.model;
          return json({ ok: true });
        }
        if (url === '/api/settings/llm') {
          return json({ default_llm: 'kimi', suggested_fallback: null, providers: [provider] });
        }
        if (url.startsWith('/api/settings/llm/usage')) {
          return json({ month: '2026-11', total_calls: 0, total_cost: 0, by_provider: [] });
        }
        if (url === '/api/workouts/deleted') return json({ workouts: [] });
        if (url === '/api/settings/profile') return json({ gender: null, birth_date: null });
        if (url.includes('/api/match-candidates')) return json({ candidates: [] });
        if (url.includes('/api/sync/status')) return json({ running: false, status: null });
        return json({});
      };
    `,
  })
  await cdp.send('Page.navigate', { url: `http://127.0.0.1:${vitePort}/settings` })
  await cdp.waitFor(`document.querySelector('[data-testid="model-select-kimi"]')?.value === 'kimi-k3.1-pro'`)
  await sleep(400)
  const initial = await cdp.eval(`(() => {
    const select = document.querySelector('[data-testid="model-select-kimi"]');
    const pricing = document.querySelector('[data-testid="model-pricing-kimi"]').textContent;
    return {
      selected: select.value,
      options: [...select.options].map(option => option.value),
      pricing,
      defaultPrice: pricing.includes('输入 ¥13') && pricing.includes('输出 ¥68') && pricing.includes('缓存命中 ¥1.3'),
      overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth,
    };
  })()`)

  await cdp.eval(`(() => {
    const select = document.querySelector('[data-testid="model-select-kimi"]');
    select.value = 'kimi-k3';
    select.dispatchEvent(new Event('change', { bubbles: true }));
  })()`)
  await cdp.waitFor(`document.querySelector('[data-testid="model-pricing-kimi"]')?.textContent.includes('输出 ¥100')`)
  await cdp.waitFor(`window.__modelPutBodies.length === 1 && !document.querySelector('[data-testid="model-select-kimi"]').disabled`)
  await cdp.eval(`document.querySelector('[data-testid="model-select-kimi"]').scrollIntoView({ block: 'center' })`)
  await sleep(500)
  const switched = await cdp.eval(`(() => {
    const pricing = document.querySelector('[data-testid="model-pricing-kimi"]').textContent;
    return {
      selected: document.querySelector('[data-testid="model-select-kimi"]').value,
      putBodies: window.__modelPutBodies,
      pricing,
      k3Price: pricing.includes('输入 ¥20') && pricing.includes('输出 ¥100') && pricing.includes('缓存命中 ¥2'),
      savedMessage: document.body.innerText.includes('已选择模型 kimi-k3'),
      overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth,
    };
  })()`)

  mkdirSync(path.join(root, '..', 'outputs'), { recursive: true })
  const screenshot = await cdp.send('Page.captureScreenshot', { format: 'png' })
  const screenshotPath = path.join(root, '..', 'outputs', 'settings-kimi-models-mobile.png')
  writeFileSync(screenshotPath, Buffer.from(screenshot.data, 'base64'))

  const expectedBody = { provider: 'kimi', api_key: '', set_default: false, model: 'kimi-k3' }
  const expectedOptions = ['kimi-k3.1-pro', 'kimi-k3.1-pro-highspeed', 'kimi-k3']
  if (initial.selected !== 'kimi-k3.1-pro' || !initial.defaultPrice || initial.overflow ||
      JSON.stringify(initial.options) !== JSON.stringify(expectedOptions)) {
    throw new Error(`Initial UI assertion failed: ${JSON.stringify(initial)}`)
  }
  if (switched.selected !== 'kimi-k3' || !switched.k3Price || !switched.savedMessage || switched.overflow ||
      JSON.stringify(switched.putBodies[0]) !== JSON.stringify(expectedBody)) {
    throw new Error(`Model switch assertion failed: ${JSON.stringify(switched)}`)
  }
  if (cdp.errors.length) throw new Error(`Browser errors: ${JSON.stringify(cdp.errors)}`)
  console.log(JSON.stringify({ ok: true, initial, switched, screenshotPath }, null, 2))
  await cdp.send('Browser.close')
} finally {
  if (ws) ws.close()
  if (chrome && chrome.exitCode === null) chrome.kill()
  if (vite && vite.exitCode === null) vite.kill()
  await sleep(500)
  rmSync(profile, { recursive: true, force: true })
}
