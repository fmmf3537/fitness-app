// 校验脚本自身用例：篡改配置应报红（TDD）
import { describe, it, expect, beforeAll, afterAll } from 'vitest'
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { checkCapacitorConfig } from './check-capacitor-config.mjs'

const __dirname = dirname(fileURLToPath(import.meta.url))
const FRONTEND_ROOT = join(__dirname, '..')

const VALID_CONFIG = `import type { CapacitorConfig } from '@capacitor/cli'

const config: CapacitorConfig = {
  appId: 'com.fmmf.fitnesshub',
  appName: '健身看板',
  webDir: 'dist',
  server: {
    url: 'http://118.24.143.172:8080',
  },
}

export default config
`

const VALID_MANIFEST = `<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android">
    <application android:usesCleartextTraffic="true" android:label="@string/app_name">
    </application>
</manifest>
`

function writeFixture(root, { config = VALID_CONFIG, manifest = VALID_MANIFEST, withIcon = true, withSplash = true, withGeneratedIcon = true } = {}) {
  mkdirSync(root, { recursive: true })
  writeFileSync(join(root, 'capacitor.config.ts'), config)
  const manifestPath = join(root, 'android/app/src/main/AndroidManifest.xml')
  mkdirSync(dirname(manifestPath), { recursive: true })
  writeFileSync(manifestPath, manifest)
  mkdirSync(join(root, 'assets-src'), { recursive: true })
  if (withIcon) writeFileSync(join(root, 'assets-src', 'icon.png'), 'png')
  if (withSplash) writeFileSync(join(root, 'assets-src', 'splash.png'), 'png')
  if (withGeneratedIcon) {
    const resDir = join(root, 'android/app/src/main/res/mipmap-xxhdpi')
    mkdirSync(resDir, { recursive: true })
    writeFileSync(join(resDir, 'ic_launcher.png'), 'png')
  }
  return root
}

let tmp

beforeAll(() => {
  tmp = mkdtempSync(join(tmpdir(), 'capcfg-'))
})

afterAll(() => {
  rmSync(tmp, { recursive: true, force: true })
})

describe('checkCapacitorConfig fixtures', () => {
  it('合法配置通过（0 错误）', () => {
    const dir = writeFixture(join(tmp, 'ok'))
    expect(checkCapacitorConfig(dir)).toEqual([])
  })

  it('篡改 appId 报红', () => {
    const dir = writeFixture(join(tmp, 'bad-appid'), {
      config: VALID_CONFIG.replace('com.fmmf.fitnesshub', 'com.evil.hacked'),
    })
    expect(checkCapacitorConfig(dir).join('\n')).toMatch(/appId/)
  })

  it('篡改 server.url 报红', () => {
    const dir = writeFixture(join(tmp, 'bad-url'), {
      config: VALID_CONFIG.replace('http://118.24.143.172:8080', 'http://evil.example.com'),
    })
    expect(checkCapacitorConfig(dir).join('\n')).toMatch(/server\.url|url/)
  })

  it('Manifest 缺少 usesCleartextTraffic 报红', () => {
    const dir = writeFixture(join(tmp, 'no-cleartext'), {
      manifest: VALID_MANIFEST.replace(' android:usesCleartextTraffic="true"', ''),
    })
    expect(checkCapacitorConfig(dir).join('\n')).toMatch(/usesCleartextTraffic/)
  })

  it('缺少图标源文件报红', () => {
    const dir = writeFixture(join(tmp, 'no-icon'), { withIcon: false })
    expect(checkCapacitorConfig(dir).join('\n')).toMatch(/icon/)
  })

  it('缺少 Android 生成图标报红', () => {
    const dir = writeFixture(join(tmp, 'no-gen-icon'), { withGeneratedIcon: false })
    expect(checkCapacitorConfig(dir).join('\n')).toMatch(/ic_launcher/)
  })
})

describe('checkCapacitorConfig 真实仓库', () => {
  it('当前仓库配置应全部通过', () => {
    expect(checkCapacitorConfig(FRONTEND_ROOT)).toEqual([])
  })
})
