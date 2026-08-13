import type { CapacitorConfig } from '@capacitor/cli'

const config: CapacitorConfig = {
  appId: 'com.fmmf.fitnesshub',
  appName: '健身看板',
  // webDir 保留 dist：当前以 server.url 直连生产服务（WebView 与后端同源，零 CORS 改造，
  // 前端更新走 docker 重建即生效）；将来可切回离线壳模式。
  webDir: 'dist',
  server: {
    url: 'http://118.24.143.172:8080',
    // androidScheme 保持默认 http，配合 Manifest 的 usesCleartextTraffic
  },
}

export default config
