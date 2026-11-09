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

const providers = [
  {
    name: 'deepseek', base_url: 'https://api.deepseek.com/v1',
    default_model: 'deepseek-flash', selected_model: 'deepseek-flash',
    implemented: true, has_key: true, consecutive_failures: 0,
    models: [
      {
        id: 'deepseek-flash', label: 'DeepSeek V4.1 Flash（推荐）',
        prompt: 2, completion: 8, cached_prompt: 0.04,
        pricing_note: '按高峰价估算；闲时半价（法定节假日以账单为准）',
      },
      {
        id: 'deepseek-v4-pro', label: 'DeepSeek V4 Pro（旗舰）',
        prompt: 9, completion: 27, cached_prompt: 0.3,
        pricing_note: '按高峰价估算；闲时半价（法定节假日以账单为准）',
      },
    ],
  },
  {
    name: 'minimax', base_url: 'https://api.minimaxi.com/v1',
    default_model: 'MiniMax-M3', selected_model: 'MiniMax-M3',
    implemented: true, has_key: true, consecutive_failures: 0,
    models: [
      {
        id: 'MiniMax-M3', label: 'MiniMax M3（旗舰）',
        prompt: 2.1, completion: 8.4, cached_prompt: 0.42,
        pricing_note: '≤512k 输入永久五折后价格；更长输入按高阶价估算',
      },
      {
        id: 'MiniMax-M3.1-Flash', label: 'MiniMax M3.1 Flash（快速低价）',
        prompt: 1, completion: 4, cached_prompt: 0.1,
        pricing_note: '标准服务价格；优先服务为标准价的 1.5 倍',
      },
    ],
  },
  {
    name: 'kimi', base_url: 'https://api.moonshot.cn/v1',
    default_model: 'kimi-k3.1-pro', selected_model: 'kimi-k3.1-pro',
    implemented: true, has_key: true, consecutive_failures: 0,
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
  },
]

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
      window.__modelTestBodies = [];
      const providers = ${JSON.stringify(providers)};
      const json = (body, status = 200) => Promise.resolve({
        ok: status >= 200 && status < 300, status,
        json: () => Promise.resolve(body),
      });
      window.fetch = (input, options = {}) => {
        const url = String(input);
        if (url === '/api/settings/llm' && options.method === 'PUT') {
          const body = JSON.parse(options.body);
          window.__modelPutBodies.push(body);
          const provider = providers.find(item => item.name === body.provider);
          provider.selected_model = body.model;
          return json({ ok: true });
        }
        if (url === '/api/settings/llm/test' && options.method === 'POST') {
          const body = JSON.parse(options.body);
          window.__modelTestBodies.push(body);
          if (body.provider === 'kimi') {
            return json({
              ok: false, code: 'output_truncated',
              message: '模型返回空正文，输出额度可能被推理消耗',
              latency_ms: 1200, detail: 'finish_reason=length',
            });
          }
          const success = body.provider === 'deepseek'
            ? { latency_ms: 1575, prompt_tokens: 38, completion_tokens: 11, cost_estimate: 0.000164 }
            : { latency_ms: 1604, prompt_tokens: 205, completion_tokens: 3, cost_estimate: 0.00024066 };
          return json({
            ok: true, code: 'ok', message: '模型可用：返回正常正文',
            detail: 'finish_reason=stop', ...success,
          });
        }
        if (url === '/api/settings/llm') {
          return json({ default_llm: 'kimi', suggested_fallback: null, providers });
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
    const read = name => {
      const select = document.querySelector('[data-testid="model-select-' + name + '"]');
      return { selected: select.value, options: [...select.options].map(option => option.value) };
    };
    return {
      deepseek: read('deepseek'), minimax: read('minimax'), kimi: read('kimi'),
      overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth,
    };
  })()`)

  await cdp.eval(`document.querySelector('[data-testid="test-model-deepseek"]').click()`)
  await cdp.waitFor(`document.querySelector('[data-testid="model-test-result-deepseek"]')?.textContent.includes('tokens 38+11')`)
  const deepseekTest = await cdp.eval(`(() => {
    const result = document.querySelector('[data-testid="model-test-result-deepseek"]');
    return {
      text: result.textContent,
      successStyle: result.className.includes('border-emerald-200'),
      requestBodies: window.__modelTestBodies.slice(),
    };
  })()`)

  await cdp.eval(`(() => {
    const select = document.querySelector('[data-testid="model-select-minimax"]');
    select.value = 'MiniMax-M3.1-Flash';
    select.dispatchEvent(new Event('change', { bubbles: true }));
  })()`)
  await cdp.waitFor(`document.querySelector('[data-testid="model-pricing-minimax"]')?.textContent.includes('输出 ¥4')`)
  await cdp.waitFor(`window.__modelPutBodies.length === 1 && !document.querySelector('[data-testid="model-select-minimax"]').disabled`)
  await cdp.eval(`document.querySelector('[data-testid="test-model-minimax"]').click()`)
  await cdp.waitFor(`document.querySelector('[data-testid="model-test-result-minimax"]')?.textContent.includes('tokens 205+3')`)
  const minimaxTest = await cdp.eval(`(() => ({
    selected: document.querySelector('[data-testid="model-select-minimax"]').value,
    pricing: document.querySelector('[data-testid="model-pricing-minimax"]').textContent,
    result: document.querySelector('[data-testid="model-test-result-minimax"]').textContent,
    putBodies: window.__modelPutBodies,
    requestBodies: window.__modelTestBodies,
  }))()`)

  await cdp.eval(`document.querySelector('[data-testid="test-model-kimi"]').click()`)
  await cdp.waitFor(`document.querySelector('[data-testid="model-test-result-kimi"]')?.textContent.includes('输出额度可能被推理消耗')`)
  await cdp.eval(`document.querySelector('[data-testid="model-test-result-kimi"]').scrollIntoView({ block: 'center' })`)
  await sleep(400)
  const kimiTest = await cdp.eval(`(() => {
    const result = document.querySelector('[data-testid="model-test-result-kimi"]');
    return {
      text: result.textContent,
      failureStyle: result.className.includes('border-red-200'),
      requestBodies: window.__modelTestBodies,
      overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth,
    };
  })()`)

  mkdirSync(path.join(root, '..', 'outputs'), { recursive: true })
  const screenshot = await cdp.send('Page.captureScreenshot', { format: 'png' })
  const screenshotPath = path.join(root, '..', 'outputs', 'settings-model-availability-mobile.png')
  writeFileSync(screenshotPath, Buffer.from(screenshot.data, 'base64'))

  const expectedOptions = {
    deepseek: ['deepseek-flash', 'deepseek-v4-pro'],
    minimax: ['MiniMax-M3', 'MiniMax-M3.1-Flash'],
    kimi: ['kimi-k3.1-pro', 'kimi-k3.1-pro-highspeed', 'kimi-k3'],
  }
  for (const [name, selected] of Object.entries({
    deepseek: 'deepseek-flash', minimax: 'MiniMax-M3', kimi: 'kimi-k3.1-pro',
  })) {
    if (initial[name].selected !== selected ||
        JSON.stringify(initial[name].options) !== JSON.stringify(expectedOptions[name])) {
      throw new Error(`Initial ${name} assertion failed: ${JSON.stringify(initial[name])}`)
    }
  }
  if (initial.overflow || kimiTest.overflow) throw new Error('Mobile horizontal overflow detected')
  if (!deepseekTest.successStyle || !deepseekTest.text.includes('耗时 1575 ms') ||
      !deepseekTest.text.includes('估算 ¥0.000164') ||
      JSON.stringify(deepseekTest.requestBodies[0]) !== JSON.stringify({ provider: 'deepseek', model: 'deepseek-flash' })) {
    throw new Error(`DeepSeek test assertion failed: ${JSON.stringify(deepseekTest)}`)
  }
  if (minimaxTest.selected !== 'MiniMax-M3.1-Flash' || !minimaxTest.pricing.includes('输入 ¥1') ||
      !minimaxTest.result.includes('估算 ¥0.000241') ||
      JSON.stringify(minimaxTest.putBodies[0]) !== JSON.stringify({
        provider: 'minimax', api_key: '', set_default: false, model: 'MiniMax-M3.1-Flash',
      }) || JSON.stringify(minimaxTest.requestBodies[1]) !== JSON.stringify({
        provider: 'minimax', model: 'MiniMax-M3.1-Flash',
      })) {
    throw new Error(`MiniMax test assertion failed: ${JSON.stringify(minimaxTest)}`)
  }
  if (!kimiTest.failureStyle || !kimiTest.text.includes('finish_reason=length') ||
      JSON.stringify(kimiTest.requestBodies[2]) !== JSON.stringify({
        provider: 'kimi', model: 'kimi-k3.1-pro',
      })) {
    throw new Error(`Kimi failure assertion failed: ${JSON.stringify(kimiTest)}`)
  }
  if (cdp.errors.length) throw new Error(`Browser errors: ${JSON.stringify(cdp.errors)}`)
  console.log(JSON.stringify({ ok: true, initial, deepseekTest, minimaxTest, kimiTest, screenshotPath }, null, 2))
  await cdp.send('Browser.close')
} finally {
  if (ws) ws.close()
  if (chrome && chrome.exitCode === null) chrome.kill()
  if (vite && vite.exitCode === null) vite.kill()
  await sleep(500)
  rmSync(profile, { recursive: true, force: true })
}
