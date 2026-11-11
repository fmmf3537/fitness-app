# 可行性分析报告：纯手机客户端版（去服务器化）

> 生成时间：2026-09-14
> 分析基于：当前 main 分支（commit d43a5a8，UIX-09 暗色模式）
> 分析人：AI Agent（基于代码实读，非推测）

---

## 1. 结论先行

**技术上可行，但不推荐。** 工程量大、核心功能（佳明同步）有硬阻塞、数据安全降级、定时任务在移动端不可靠。如果目标是减少服务器维护负担，有更优的替代方案（见 §6）。

---

## 2. 当前架构盘点（实读代码）

### 2.1 后端规模

| 模块 | 文件数 | 总行数 | 说明 |
|------|--------|--------|------|
| adapters/ | 4 | ~1,447 | garmin (738)、llm (365)、xunji (268)、xunji_body (76) |
| services/ | 24 | ~5,585 | ai (2,118)、screenshot、matcher、sync、writeback、backfill 等 |
| api/ | 19 | ~1,915 | 30+ 个 REST 端点 |
| 其他（models/config/scheduler 等） | ~15 | ~1,471 | SQLAlchemy 模型、Alembic 迁移、APScheduler |
| **合计** | **56** | **~10,418** | Python 3.11 |

### 2.2 前端规模

| 项 | 数量 |
|---|---|
| JSX 组件/页面 | 78 个文件 |
| JS 工具/hooks | 29 个文件 |
| API 调用点 | ~35 处（全部经 `api()`/`apiForm()`） |
| 测试 | 381 个用例（43 个测试文件） |
| Capacitor 配置 | 已有，但 `server.url` 直连生产服务器 |

### 2.3 外部依赖

| 依赖 | 类型 | 用途 | 移动端可替代性 |
|------|------|------|----------------|
| **Garmin (garth)** | Python 库 | 佳明数据同步（活动/睡眠/HRV/体脂） | ❌ 需 JS 重写，Garmin 风控严格 |
| **Xunji API** | HTTP REST | 训记训练数据拉取/写回 | ✅ 可直接 fetch |
| **LLM (DeepSeek/Kimi/MiniMax)** | HTTP REST | AI 报告/教练对话/截图识别 | ✅ 可直接 fetch（OpenAI 兼容协议） |
| **fitparse** | Python 库 | FIT/TCX/GPX 文件解析 | ⚠️ 有 JS 替代（fit-file-parser），需验证 |
| **reportlab** | Python 库 | PDF 导出 | ⚠️ 有 JS 替代（jsPDF），功能裁剪 |
| **PostgreSQL** | 数据库 | 生产数据存储 | ✅ SQLite 可替代 |
| **APScheduler** | Python 库 | 定时任务（每日同步/周月复盘/备份） | ❌ 移动端后台不可靠 |
| **Alembic** | Python 库 | 数据库迁移 | ⚠️ 需 JS 迁移方案（drizzle/better-sqlite3 migrations） |

### 2.4 定时任务清单（7 个 cron job）

| 任务 | 触发时间 | 功能 |
|------|----------|------|
| daily_sync_today | 22:47 | 拉取今日训记+佳明数据 |
| daily_sync_prev_day | 22:52 | 拉取昨日数据（兜底） |
| health_check_hourly | 每小时 :11 | 健康检查 |
| plan_cache_daily | 23:03 | 计划缓存刷新 |
| weekly_review | 周日 21:13 | AI 周复盘生成 |
| monthly_review | 每月 1 日 09:23 | AI 月复盘生成 |
| db_backup_daily | 03:17 | 数据库备份 |

---

## 3. 逐模块可行性评估

### 3.1 ✅ 可以直接迁移（低风险）

| 模块 | 说明 | 迁移方式 |
|------|------|----------|
| **前端 UI** | React + Tailwind，已在 Capacitor WebView 中运行 | 不改代码，改 `capacitor.config.ts` 去掉 `server.url`，走离线壳模式 |
| **API client** | `client.js` 是所有 HTTP 调用的唯一入口 | 把 `api()` 从 `fetch(path)` 改为调用本地服务层（JS 函数），接口签名不变 |
| **LLM 调用** | DeepSeek/Kimi/MiniMax 都是 OpenAI 兼容 HTTP API | 前端直接 fetch，Key 存手机本地（Capacitor Preferences） |
| **截图识别** | Kimi 多模态 API（base64 图片上传） | 前端直接调 LLM vision API，不经后端 |
| **训练计划** | plans service 是纯逻辑（日期计算+模板渲染） | 移植为 JS 纯函数 |
| **统计计算** | stats service 是 SQL 聚合 + 格式化 | 改用 SQLite 查询 + JS 计算 |
| **Skinfold 皮脂钳** | 纯数学公式 | 移植为 JS 函数 |
| **数据匹配** | matcher service 是规则引擎 | 移植为 JS 纯函数 |

### 3.2 ⚠️ 可以迁移但有取舍（中风险）

| 模块 | 说明 | 取舍点 |
|------|------|--------|
| **SQLite 替代 PostgreSQL** | 用 `@capacitor-community/sqlite` | 需重写所有 SQLAlchemy 模型为 JS 迁移 + 查询；Alembic 迁移历史需重新管理 |
| **FIT 文件解析** | fitparse → fit-file-parser (npm) | 功能覆盖度需验证，边界 case 可能不同 |
| **PDF 导出** | reportlab → jsPDF | 排版能力下降，复杂表格/图表可能需简化 |
| **教练记忆** | memory_distill service | 逻辑可移植，但 prompt 工程需重新调优 |
| **海报生成** | poster service（HTML → 图片） | 可用 Canvas API 替代，但质量下降 |
| **Xunji 同步** | HTTP API + 限频 | 可直接 fetch，限频逻辑用 JS 实现；但写回训记需要 Key 暴露在手机端 |

### 3.3 ❌ 难以迁移（高风险/阻塞）

| 模块 | 阻塞原因 | 影响 |
|------|----------|------|
| **佳明同步 (garth)** | garth 是 Python 专用库，处理 Garmin 的 OAuth2 + token 缓存 + IP 级 429 风控。虽然有 `garmin-connect` npm 包，但 Garmin 对非官方客户端的风控极严格，JS 版 token 管理不如 Python 成熟。**一旦 Garmin 改 API 或加强风控，JS 版可能随时挂掉且无人维护。** | **这是最大阻塞项。** 没有佳明数据，HRV/睡眠/体脂/活动心率全部缺失，趋势页和 AI 报告质量大幅下降。 |
| **定时任务** | Android Doze 模式 + 电池优化会杀死后台进程。WorkManager/Foreground Service 只能做到"尽量准时"，不能保证每天 22:47 准点执行。iOS 更严格，后台任务几乎不可控。 | 每日自动同步不可靠 → 用户需手动打开 App 触发同步 → 体验降级。周复盘/月复盘可能漏跑。 |
| **数据库备份** | 服务器每天 03:17 自动 pg_dump，保留 30 天。手机上没有等效方案。 | 数据丢失风险大幅上升。手机坏了/丢了 = 所有训练数据没了。 |
| **数据量** | 多年训练数据（训记 2023 起 + 佳明 2017 起）可能积累数万条记录。SQLite 在手机上性能可接受，但全量查询 + ECharts 渲染可能卡顿。 | 大数据量下移动端体验下降。 |

---

## 4. 工程量估算

### 4.1 直接移植（JS 重写）

| 模块 | 预估工作量 | 说明 |
|------|-----------|------|
| API client 改造 | 1 天 | `client.js` 从 fetch 改为调本地服务层 |
| SQLite schema + 迁移 | 2-3 天 | 重写 models.py 为 SQL migration，对齐 Alembic 历史 |
| Xunji adapter | 1 天 | HTTP fetch + 限频，逻辑简单 |
| LLM adapter | 1 天 | HTTP fetch，已有 OpenAI 兼容协议 |
| 训练计划/统计/匹配 | 2-3 天 | 纯逻辑移植 |
| Skinfold/皮脂钳 | 0.5 天 | 数学公式 |
| 截图识别 | 0.5 天 | 直接调 LLM vision |
| 教练对话 | 1 天 | LLM chat + 上下文管理 |
| 前端离线壳 | 0.5 天 | capacitor.config.ts 改回离线模式 |
| **小计** | **~10-12 天** | |

### 4.2 需要攻坚/替代方案

| 模块 | 预估工作量 | 说明 |
|------|-----------|------|
| **佳明同步 JS 版** | **5-10 天** | 最大不确定性。garmin-connect npm 包功能不全，可能需要直接 HTTP 调 Garmin API + 自行管理 OAuth token。风控调试耗时不可控。 |
| **定时任务替代** | 2-3 天 | Android WorkManager + 手动触发兜底 + 本地通知提醒 |
| **FIT 解析 JS 版** | 1-2 天 | fit-file-parser 验证 + 边界 case 修复 |
| **PDF 导出 JS 版** | 1-2 天 | jsPDF 排版调优 |
| **数据库备份方案** | 1 天 | SQLite 导出文件 + 手动/云备份引导 |
| **测试重写** | 3-5 天 | 381 个测试用例中，涉及后端的需重写为本地测试 |
| **小计** | **~13-23 天** | |

### 4.3 总估算

| 场景 | 工作量 | 风险 |
|------|--------|------|
| **乐观**（佳明 JS 版顺利） | **~23-30 天** | 中 |
| **悲观**（佳明 JS 版卡住） | **~30-45 天** | 高 |
| **不含佳明**（放弃佳明数据） | **~15-20 天** | 低 |

---

## 5. 风险评估矩阵

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| Garmin JS 版不可用 | **高** | 致命 | 放弃佳明自动同步，改手动 FIT 导入 |
| 定时任务不可靠 | **高** | 高 | 手动触发 + 本地通知提醒 |
| 数据丢失（无备份） | **中** | 致命 | SQLite 导出 + 引导用户手动备份到云盘 |
| 手机性能瓶颈 | **低** | 中 | 分页加载 + 懒渲染 |
| 开发周期超预期 | **中** | 中 | 分阶段交付，先核心功能后边缘功能 |
| 测试覆盖下降 | **中** | 中 | 保留 vitest，重写测试为本地 mock |

---

## 6. 替代方案推荐

### 方案 A：保持现状（推荐）

**理由**：当前架构已经是最优解——Docker Compose 一键部署、自动备份、定时同步、数据安全。服务器成本约 ¥50-100/月（2C4G 云主机），换来的是数据零丢失风险和全功能可用。

**改进方向**：如果想减少维护负担，可以：
- 用 GitHub Actions 自动部署（已在 `DEPLOY-V6-GITHUB.md` 中提供方案）
- 加服务器监控告警（ServerChan 已有，只需确认 webhook 配置）

### 方案 B：混合模式（次推荐）

保留服务器做数据同步和定时任务，但让手机端可以**离线查看**数据：
- 前端走 Capacitor 离线壳模式
- 启动时从服务器拉数据缓存到本地 SQLite
- 离线时展示缓存数据，恢复网络后自动同步
- **好处**：手机没网也能看日历/趋势/报告，但同步和 AI 功能仍需网络

### 方案 C：纯本地 + 手动佳明导入

放弃佳明自动同步，改为：
- 用户从 Garmin Connect 导出 FIT 文件 → 手机 App 导入
- 训记数据通过 Xunji API 直接拉取（可直接 fetch）
- LLM 功能直接调 API
- **代价**：佳明数据需手动导入，HRV/睡眠等自动同步数据缺失

### 方案 D：BaaS 替代（Firebase/Supabase）

用 Supabase（PostgreSQL + Auth + Edge Functions）替代自建服务器：
- 数据库托管在 Supabase
- 定时任务用 Supabase Edge Functions + cron
- 前端直连 Supabase REST API
- **好处**：免运维，但仍是"有服务器"架构，只是不用自己管

---

## 7. 决策建议

| 你的核心诉求 | 推荐方案 |
|-------------|----------|
| 减少服务器维护 | 方案 A + GitHub Actions 自动部署 |
| 手机没网也能用 | 方案 B（混合离线模式） |
| 彻底不要服务器 | 方案 C（放弃佳明自动同步） |
| 不想管服务器 | 方案 D（Supabase 托管） |
| 以上都不是 | 保持现状 |

**我的建议**：先明确你的核心痛点是什么。如果是"服务器太贵/太难维护"，方案 A 的 GitHub Actions 自动部署已经能解决 90% 的问题。如果是"手机没网也想用"，方案 B 更实际。纯本地方案（方案 C）的代价太大，除非你确定可以放弃佳明自动同步。

---

## 8. 附录：当前系统数据流图

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│  Garmin     │────►│  garth (Py)  │────►│  PostgreSQL │
│  Connect    │     │  429风控     │     │             │
└─────────────┘     └──────────────┘     │             │
                                         │  workouts   │
┌─────────────┐     ┌──────────────┐     │  plans      │
│  训记       │────►│  Xunji API   │────►│  metrics    │
│  Open API   │     │  15s限频     │     │  reports    │
└─────────────┘     └──────────────┘     │  coach      │
                                         │  ...        │
┌─────────────┐     ┌──────────────┐     │             │
│  DeepSeek/  │◄────│  LLM Adapter │◄────│  settings   │
│  Kimi/MiniMax│     │  OpenAI兼容  │     │  (Fernet)   │
└─────────────┘     └──────────────┘     └──────┬──────┘
                                                 │
                    ┌──────────────┐              │
                    │  APScheduler  │──────────────┘
                    │  7 cron jobs │
                    └──────┬───────┘
                           │
                    ┌──────▼───────┐
                    │  FastAPI     │
                    │  30+ 端点    │
                    └──────┬───────┘
                           │ HTTP
                    ┌──────▼───────┐
                    │  React SPA   │
                    │  (Capacitor) │
                    └──────────────┘
```

纯手机版需要把整条链路压缩到手机上，其中 Garmin (garth) 和 APScheduler 是最大的技术障碍。
