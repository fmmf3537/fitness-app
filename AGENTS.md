# AGENTS.md — multiuser-v2 项目 Agent Context

> 给后续接手 multiuser-v2 分支的 agent (含 Mavis、Coder、Cursor 等) 的"项目事实 + 决策"基线。
> 严格遵守 = 不返工、不越界、不过度设计。

## 项目事实

- **代码根**：`D:\kimi\fitness-app`
- **主分支**：`main`（冻结在 `d605491`，单用户版，已被 `BRANCH_STRATEGY.md` 永久冻结）
- **多用户分支**：`multiuser-v2`（永不合并 main，branch-guard hook 保护）
- **远端协议**：SSH（避 GFW 阻断 HTTPS 443）
- **部署**：本地 Docker Compose（5 服务：postgres / backend / frontend / caddy / backup）
- **部署入口**：host `http://localhost:8888`（caddy 8888 端口，避开本机 80 冲突）
- **Tailscale**：本机 IP `100.127.46.110`（账号 fmmf@，主机名 chris）
- **用户**：「小马哥」个人 + 家庭/朋友小圈子，**不公网**

## 规模基线（2026-08-26 决定）

**目标用户数 ≤ 10 人**。这是 hard cap，所有架构/性能决策按此基线。

| 项 | 当前实现 | 不用做 |
|---|---|---|
| Scheduler 同步 | `sync_all_users` 串行 for-loop（22:47/22:52） | 不并发化、不拆 worker |
| Leaderboard 预计算 | 23:30 cron 1 次/天 | 不改频、不实时算 |
| 数据库 | 单 Postgres 16-alpine | 不读写分离、不分库 |
| Token 缓存 | DB 查 `auth_token` 表（M2-4 已删进程内 `_ACTIVE_TOKENS`） | 不引入 Redis |
| Job 存储 | `MemoryJobStore`（单进程） | 不换 PersistentJobStore、不加队列 |
| 连接池 | SQLAlchemy 默认 | 不调优 |
| 部署规模 | 单机 Docker Compose | 不上 K8s、不上 swarm |

> **硬约束**：任何"加 Redis / 加 worker / 拆库 / 改并发"建议在 ≤ 10 人场景下都是过度设计，应直接拒绝。

## 历史教训

- **M0.5-5 越界事件**：Cursor 越界做 M0.5-6 + M0.5-7、改 4 个旧测试、虚假报告"原有用例未改"
  → 长期记忆已存，Cursor 提示词必须带强约束块、文件清单、原有用例未改硬性要求
- **M2-1 bcrypt 漏列**：`utils/password.py` 引 bcrypt 但 `requirements.txt` 漏列
  → 72e2392 已补 `bcrypt>=5.0,<6.0`
- **M2-5 Caddyfile 漏 /api 反代**：外部 POST 收 404（caddy `handle_path` strip 前缀）
  → 72e2392 已改用 `@api path /api/*` + `handle @api` 保留 path
- **M2-5 docker-compose 漏端口冲突**：本机 80 被 2 月前 `ats_nginx` 容器占
  → 72e2392 已改 caddy host 端口 80→8888

## 工作流

- **Cursor 写 + 我审核 + commit**：见 `docs/cursor-prompts/` 模板
- **提示词写法**：详尽（45KB+）让 Cursor 一次到位；简化（15KB）会触发 Cursor 推断/补全返工
  - 4 类关键决策点必须详尽：schema 完整 / 业务函数 JSDoc / 错误码表 / 测试断言细节
  - 样板可省：Zod schema / controller / 路由挂载 / 5 角色 RBAC 结构
- **测试基线**：后端 985 passed / 前端 306/306 passed
- **commit 格式**：`<type>(<scope>): <subject>`，type = feat / fix / chore / refactor / docs / test
- **pre-commit hook**：仅在 main 分支拦截 push，multiuser-v2 不受影响

## 关键路径

- 部署脚本：`backend/scripts/create_first_admin.py`（建第一个 admin）
- 部署配置：`deploy/Caddyfile` + `docker-compose.yml` + `.env`（dev 简化版）
- 迁移脚本：`backend/scripts/migrate_to_multiuser.py`（单用户库 → 多用户）
- 审计报告：`docs/AUDIT_2026.md`（5 个 P0 漏洞清单）
- 分支策略：`BRANCH_STRATEGY.md`（7 节，含"永不合并 main"）

## 状态机（2026-08-26）

| Phase | 状态 |
|---|---|
| M1 多用户数据模型 | ✅ done (54c0df2) |
| M2 收尾 + P0 修复 | ✅ done (54c0df2) |
| M3 外部账号隔离 | ✅ done (2b11353, b3bd658, 3342609, f9739ad) |
| M4 同步调度器 + 管理员后台 | ✅ done (8bb933b, 8256605) |
| M5 排行榜 + 前端 | ✅ done (9249e20, 0bbce64) |
| M2-5 Docker 部署补漏 | ✅ done (72e2392) |
| Admin 账号初始化 | ✅ done (7a4dfa1) |
| 本地端到端验证 | ✅ done (admin/Admin@2026 登录 200) |
| Tailscale 跨设备验证 | ⏳ pending |
| 腾讯云 CVM 迁移 | ⏳ pending |
| M6-1/2/3 E2E 联调 | ⏳ pending |
| GO_LIVE_CHECKLIST | ⏳ pending |
