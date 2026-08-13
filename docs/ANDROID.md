# 安卓 APP 打包指南（V3-1 · Capacitor）

> 方案背景见《开发提示词手册.md》Sprint 8 背景锚点：Capacitor WebView 套壳，
> `server.url` 直连生产服务 `http://118.24.143.172:8080`（WebView 与后端同源，零 CORS 改造；
> 前端更新走 docker 重建即生效，不必重发 APK）。

## 1. 本机环境要求（Windows）

| 依赖 | 版本 | 说明 |
|---|---|---|
| Node.js | ≥ 20 | 前端构建 |
| JDK | 17（Temurin 17 已验证） | Gradle 构建；`java -version` 可查 |
| Android Studio | 任意近期版本 | 仅用于安装/管理 SDK，不必用它打开工程 |
| Android SDK | Platform 34 + Build-Tools 34.0.0 + platform-tools | 默认路径 `%LOCALAPPDATA%\Android\Sdk` |

SDK 未安装时（命令行方式，无需打开 Android Studio）：

```powershell
# 1) 下载命令行工具并解压到 %LOCALAPPDATA%\Android\Sdk\cmdline-tools\latest
#    https://dl.google.com/android/repository/commandlinetools-win-11076708_latest.zip
# 2) 安装组件并接受许可
sdkmanager.bat --licenses
sdkmanager.bat "platform-tools" "platforms;android-34" "build-tools;34.0.0"
```

首次构建前需在 `frontend/android/local.properties` 写入 SDK 路径（该文件已 gitignore，不入库）：

```properties
sdk.dir=C:\\Users\\<用户名>\\AppData\\Local\\Android\\Sdk
```

## 2. 打包命令

```powershell
cd frontend
npm install                 # 首次或依赖变更后
npm run build               # 产出 dist（webDir，供将来离线壳模式使用）
npx cap sync android        # 同步 web 资源与配置到 android 工程
cd android
.\gradlew.bat assembleDebug     # debug APK（先验证）
.\gradlew.bat assembleRelease   # release APK（debug 签名，单用户不上架，不做签名加固）
```

> 注：`android/gradle/wrapper/gradle-wrapper.properties` 的 `distributionUrl` 已改为腾讯云镜像
> （`mirrors.cloud.tencent.com/gradle/`，直连 services.gradle.org 超时），并相应关闭
> `validateDistributionUrl`。海外网络环境可改回官方地址。

## 3. APK 输出路径

| 构建 | 路径 |
|---|---|
| debug | `frontend/android/app/build/outputs/apk/debug/app-debug.apk` |
| release | `frontend/android/app/build/outputs/apk/release/app-release.apk`（debug 签名） |

## 4. 安装方法

- **微信/QQ 传文件**：把 APK 发到手机「文件传输助手」，点击安装（需在系统设置允许"安装未知来源应用"）；
- **adb**（手机开 USB 调试并连接电脑）：

  ```powershell
  adb install -r frontend\android\app\build\outputs\apk\release\app-release.apk
  ```

安装后打开「健身看板」，即通过 WebView 直连 `http://118.24.143.172:8080`，与浏览器访问同一后端。

## 5. 配置校验

```powershell
cd frontend
npm run test:capacitor    # 断言 appId/appName/server.url/usesCleartextTraffic/图标文件
```

CI 中同样运行该脚本（Android 构建本身不进 CI，无 SDK 环境）。

## 6. 关键配置速查

- `frontend/capacitor.config.ts`：`appId: com.fmmf.fitnesshub`、`appName: 健身看板`、
  `server.url: http://118.24.143.172:8080`、`webDir: dist`、`androidScheme` 保持默认 http；
- `frontend/android/app/src/main/AndroidManifest.xml`：已开 `android:usesCleartextTraffic="true"`（HTTP 明文必需）；
- 图标/启动屏源文件：`frontend/assets-src/`（icon.svg / splash.svg 及渲染出的 PNG，
  修改后执行 `npx capacitor-assets generate --android --assetPath assets-src` 重新生成全尺寸）；
- `frontend/android/` 入库；`local.properties`、`*.keystore`/`*.jks`、`build/` 均已 gitignore。
