// Capacitor 配置校验脚本（V3-1）
// 断言 capacitor.config.ts 关键配置、AndroidManifest 明文流量开关、图标文件存在。
// CLI: node scripts/check-capacitor-config.mjs  → 有错误时退出码 1
import { existsSync, readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const FRONTEND_ROOT = join(__dirname, '..')

const EXPECTED = {
  appId: 'com.fmmf.fitnesshub',
  appName: '健身看板',
  serverUrl: 'http://118.24.143.172:8080',
  webDir: 'dist',
}

/**
 * 校验指定根目录下的 Capacitor 配置，返回错误信息数组（空数组 = 全部通过）。
 * @param {string} rootDir frontend 根目录
 * @returns {string[]} 错误列表
 */
export function checkCapacitorConfig(rootDir = FRONTEND_ROOT) {
  const errors = []

  // 1. capacitor.config.ts 关键配置
  const configPath = join(rootDir, 'capacitor.config.ts')
  if (!existsSync(configPath)) {
    errors.push(`capacitor.config.ts 不存在: ${configPath}`)
  } else {
    const config = readFileSync(configPath, 'utf-8')
    if (!config.includes(`appId: '${EXPECTED.appId}'`) && !config.includes(`appId: "${EXPECTED.appId}"`)) {
      errors.push(`capacitor.config.ts appId 应为 '${EXPECTED.appId}'`)
    }
    if (!config.includes(`appName: '${EXPECTED.appName}'`) && !config.includes(`appName: "${EXPECTED.appName}"`)) {
      errors.push(`capacitor.config.ts appName 应为 '${EXPECTED.appName}'`)
    }
    if (!config.includes(EXPECTED.serverUrl)) {
      errors.push(`capacitor.config.ts server.url 应为 '${EXPECTED.serverUrl}'`)
    }
    if (!config.includes(`webDir: '${EXPECTED.webDir}'`) && !config.includes(`webDir: "${EXPECTED.webDir}"`)) {
      errors.push(`capacitor.config.ts webDir 应为 '${EXPECTED.webDir}'`)
    }
  }

  // 2. AndroidManifest.xml 明文流量开关
  const manifestPath = join(rootDir, 'android', 'app', 'src', 'main', 'AndroidManifest.xml')
  if (!existsSync(manifestPath)) {
    errors.push(`AndroidManifest.xml 不存在: ${manifestPath}`)
  } else {
    const manifest = readFileSync(manifestPath, 'utf-8')
    if (!manifest.includes('android:usesCleartextTraffic="true"')) {
      errors.push('AndroidManifest.xml 缺少 android:usesCleartextTraffic="true"（HTTP 明文流量必须开启）')
    }
  }

  // 3. 图标源文件（assets-src/ 入库）
  const iconSrc = ['icon.png', 'icon.svg'].some((f) => existsSync(join(rootDir, 'assets-src', f)))
  if (!iconSrc) {
    errors.push('assets-src/ 缺少图标源文件（icon.png 或 icon.svg）')
  }
  const splashSrc = ['splash.png', 'splash.svg'].some((f) => existsSync(join(rootDir, 'assets-src', f)))
  if (!splashSrc) {
    errors.push('assets-src/ 缺少启动屏源文件（splash.png 或 splash.svg）')
  }

  // 4. Android 已生成的启动图标（抽查 xxhdpi）
  const genIcon = ['ic_launcher.png', 'ic_launcher.webp'].some((f) =>
    existsSync(join(rootDir, 'android', 'app', 'src', 'main', 'res', 'mipmap-xxhdpi', f)),
  )
  if (!genIcon) {
    errors.push('android 工程缺少已生成的 ic_launcher（mipmap-xxhdpi），请运行 npx capacitor-assets generate --android')
  }

  return errors
}

// CLI 入口（被 import 时不执行）
if (process.argv[1] && fileURLToPath(import.meta.url) === join(process.argv[1])) {
  const errors = checkCapacitorConfig(FRONTEND_ROOT)
  if (errors.length > 0) {
    console.error('✗ Capacitor 配置校验失败：')
    for (const e of errors) console.error(`  - ${e}`)
    process.exit(1)
  }
  console.log('✓ Capacitor 配置校验通过')
}
