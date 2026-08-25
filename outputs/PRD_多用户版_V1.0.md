# PRD —— 健身数据整合分析与指导 APP · 多用户版（V3-MULTI）

> 版本 V1.1 · 2026-08-24 · 已 review 定稿
> 本文档在 V1 PRD（单用户版）基础上扩展，不重复陈述已实现的单用户功能，只定义多用户化的新增与变更。
> 与《开发计划.md》的关系：本 PRD 落地后，原"阶段三 V2"任务编号顺延，多用户任务以 M-x 前缀命名。

> **V1.1 修订记录（2026-08-24，二次评审六项风险对策落地）**
> 1. 多用户+账号密码场景下 HTTPS 由可选升为强制（§5.1、§8 R5、§9 M-M6 新增 M6-4）；
> 2. 新增合并红线：M2-5 完成前禁止部署/合并 main，M1-4 回填完成前禁止合并（§8 R6、§9）；
> 3. 认证 token 由"内存 JWT-like"改为不透明随机 token 落 `auth_token` 表（§4、§6.1），重启不丢会话、停用立即失效；
> 4. M2-5 增加"全局隔离测试"强制项（A/B 两用户遍历全部端点互不可见）；
> 5. 佳明 token 存储位置统一为 settings 表（DB），删除"按用户分缓存目录"方案（US-M4、§5.1）；
> 6. §4 补齐 `auth_token` 与 `leaderboard_cache` 两张新表定义。

---

## 1. 背景与目标

当前系统为单用户自用（PRD §8 明确"不做多用户"），已完成 MVP/V1/V2 及 Sprint 9 全部功能。现需扩展支持**家人/训练伙伴小圈子（2~10 人）**使用，核心目标：

- 每个用户拥有独立账号、独立数据、独立外部凭据（佳明/训记/LLM）；
- 管理员（原唯一用户）可管理用户生命周期、查看全局健康状态；
- 提供圈子排行榜作为轻量社交激励，不引入复杂社交功能；
- 全面转向 PostgreSQL，消除 SQLite 并发瓶颈。

## 2. 用户角色

| 角色 | 说明 | 权限边界 |
|------|------|----------|
| 管理员 | 系统所有者（原单用户） | 用户 CRUD、查看/代改任意用户数据、查看全局健康面板、**自身完整功能（与普通用户完全一致，不受任何限制）** |
| 普通用户 | 被邀请的熟人 | 仅自身数据 CRUD、自身外部账号绑定、自身 AI 报告、排行榜查看 |

> **管理员 = 超级用户**：管理员首先是普通用户，拥有全部功能（同步/融合/AI/排行榜/设置）；在此之上叠加管理权限。管理员的外部账号绑定、数据同步、AI 调用、排行榜参与等，与普通用户完全同规则运行。

## 3. 用户故事与验收标准

### US-M1 用户生命周期管理（MVP）
> 作为管理员，我希望在后台创建/停用/重置用户，无需数据库操作。

- AC1：管理员可通过界面创建用户（用户名 + 初始密码），用户名全局唯一；
- AC2：管理员可停用/启用用户，停用后该用户登录立即失效（删除该用户 auth_token 行）；
- AC3：管理员可重置任意用户密码，重置后旧密码失效；
- AC4：用户创建时生成默认设置记录（未绑定佳明/训记/LLM，未参与任何排行榜）；
- AC5：用户列表页显示每用户：绑定状态（佳明/训记/LLM）、最近同步时间、当月 LLM token 用量。

### US-M2 用户登录与认证（MVP）
> 作为用户，我希望用管理员给我的用户名密码登录，且只能看到自己的数据。

- AC1：登录接口接受 username + password，验证通过返回 Bearer token；
- AC2：token 有效期 7 天，过期或管理员停用后 401；token 持久化在 `auth_token` 表，**服务重启不丢会话**；
- AC3：密码存储使用 bcrypt（work factor ≥ 12），禁止明文/可逆加密；
- AC4：所有现有 API 路由（workouts/sync/ai_reports/...）的 `require_auth` 依赖注入当前 user_id，查询自动追加 `WHERE user_id = :current_user`；
- AC5：未登录访问任何受保护路由返回 401（与现有行为一致）。

### US-M3 数据模型多用户改造（MVP）
> 作为系统，我希望所有业务数据表都有 user_id，且现有数据无损迁移。

- AC1：以下表新增 `user_id INTEGER NOT NULL REFERENCES users(id)`：
  - `settings`（改为每用户一行，原单行表废弃）
  - `xunji_train`、`garmin_activity`、`garmin_daily`、`body_metric`
  - `workout`、`match_candidate`、`xunji_plan`（计划缓存可按用户隔离，避免 A 用户看到 B 用户的计划）
  - `ai_report`、`llm_call`、`job_run`
  - `match_candidate`、`report_chat_message`
- AC2：所有现有 UNIQUE 约束改为复合 UNIQUE（`user_id` + 原字段）；
- AC3：提供 Alembic 迁移脚本，将存量数据全部挂到管理员 user_id；
- AC4：迁移后数据行数与迁移前一致，关键表抽样核对通过。

### US-M4 外部账号绑定（MVP）
> 作为用户，我希望绑定自己的佳明/训记账号，至少绑一个才能用核心功能。

- AC1：设置页提供佳明（邮箱+密码）、训记（API Key）、训记身体数据（API Key）三个绑定入口；
- AC2：佳明绑定流程：输入凭据 → garth 登录验证 → token 加密存入 `settings.garmin_token_store_enc`（Fernet，按用户隔离，**统一存数据库，不使用文件缓存目录**，备份随 pg_dump 走）；
- AC3：训记绑定流程：输入 Key → 真实 ping 验证（调用 `api_trains_for_llm_v2` 拉昨日数据）→ 加密存储；
- AC4：绑定状态机：`none` → `xunji_only` / `garmin_only` / `both`，前端根据状态展示不同功能入口（见 §5.2）；
- AC5：解绑任一账号时，提示"历史数据保留，但后续不再同步"，确认后执行。

### US-M5 每日同步多用户调度（MVP）
> 作为系统，我希望每晚自动为所有已绑定用户同步数据，互不干扰。

- AC1：每日 22:47 起，按 user_id 顺序逐户执行 `daily_sync`（复用现有逻辑，注入 user_id）；
- AC2：每用户同步内部仍遵守佳明 429 退避、训记 15s/45s 限频；
- AC3：单用户同步失败不影响后续用户，失败写 `job_run` 并继续；
- AC4：佳明 token 从 `settings.garmin_token_store_enc` 按用户读取，避免串号；
- AC5：总耗时监控：10 用户串行同步 ≤ 5 分钟（含限频等待），超时告警。

### US-M6 AI 功能多用户化（V1）
> 作为用户，我希望用自己的 LLM Key 生成点评/复盘，且用量自己可见。

- AC1：`settings` 表每用户存 `llm_keys_json_enc`（Fernet 加密），含 DeepSeek/Kimi/MiniMax 三家 Key；
- AC2：AI 生成时从当前用户的 Key 池取默认模型，失败时按用户自己的备用模型切换；
- AC3：`llm_call` 表新增 `user_id`，月度汇总 API 按当前用户过滤；
- AC4：用户未配置任何 LLM Key 时，AI 功能入口隐藏，提示"请先配置 API Key"；
- AC5：管理员健康面板可查看每用户当月 token 用量（用于观察，不干预）。

### US-M7 圈子排行榜（V1）
> 作为用户，我希望看到圈子里大家的训练排名，互相激励。

- AC1：排行榜页提供四个可切换 tab：
  - **训练频率**：近 7/30 天有训练的天数排名；
  - **总容量**：近 7/30 天力量训练总重量（kg）排名；
  - **总热量**：近 7/30 天总热量消耗（kcal）排名；
  - **连续 streak**：当前连续训练天数排名。
- AC2：每用户可在设置中选择"不参与"某类排行榜，不参与则不出现在该榜；
- AC3：排行榜数据每日 23:30 预计算并缓存到 `leaderboard_cache` 表（避免每次请求实时聚合）；
- AC4：隐私边界：排行榜只显示用户名和指标数值，不展示具体训练内容/身体数据；
- AC5：圈子成员 ≤ 10 人，不做分页，全量展示。

### US-M8 管理员后台（V1）
> 作为管理员，我希望有集中面板管理用户和观察系统健康。

- AC1：用户管理页：列表 + 创建 + 停用/启用 + 重置密码 + 查看该用户数据（跳转只读视图）；
- AC2：健康状态面板：每用户显示——佳明 token 是否过期、最近同步是否成功、当月 LLM 成本、待确认匹配数；
- AC3：代用户修正数据：管理员可进入任意用户的训练详情页，执行合并/拆分/删除，操作记录写入 `audit_log` 表（操作人、目标用户、动作、时间、前后值摘要）；
- AC4：管理员自身功能与普通用户完全一致，不额外削减。

### US-M9 数据库全面 PostgreSQL 化（MVP）
> 作为系统，我希望开发和生产统一使用 PostgreSQL，消除 SQLite 并发瓶颈。

- AC1：docker-compose 已有 postgres 服务，开发环境通过 `DATABASE_URL` 指向本地 PG；
- AC2：`config.py` 移除 SQLite 分支的"相对路径锚定"逻辑（PG 无此问题），保留生产强制校验；
- AC3：提供 `scripts/migrate_sqlite_to_pg.py` 的增强版：支持迁移后数据抽样核对（表行数、关键字段 checksum）；
- AC4：CI 已有 PG 迁移重放，新增"多用户迁移"测试用例（从 SQLite  fixture 迁移后验证 user_id 正确）。

### US-M10 前端多用户适配（MVP）
> 作为用户，我希望界面自然区分"我的"和"圈子"的数据。

- AC1：登录页：用户名 + 密码输入，错误提示模糊化（"用户名或密码错误"）；
- AC2：所有页面数据自动按当前用户过滤，无"切换用户" UI（管理员代查看除外）；
- AC3：管理员代查看时，顶部显示醒目横幅"正在查看：用户名 [退出]"；
- AC4：设置页分节：我的绑定（佳明/训记）、我的 AI（LLM Key）、我的隐私（排行榜参与开关）、账号（修改密码）；
- AC5：排行榜页：tab 切换 + 当前用户高亮 + "我"的数值置顶。

## 4. 数据模型变更

```sql
-- 新增：用户表
users(id PK, username UNIQUE, password_hash, role,  -- admin / user
      is_active BOOLEAN DEFAULT TRUE, created_at, updated_at)

-- 新增：登录会话 token 表（V1.1：替代内存 token，重启不丢会话）
auth_token(id PK, token UNIQUE,        -- 不透明随机串（secrets.token_urlsafe）
           user_id FK NOT NULL, expires_at, created_at)
-- 停用/重置密码时删除该用户全部 token 行 → 立即失效；过期由 expires_at 惰性清理

-- 新增：审计日志
audit_log(id PK, actor_user_id FK, target_user_id FK, action,
          target_table, target_id, summary_json, created_at)

-- 新增：排行榜预计算缓存（V1.1 补录，M5-1 使用）
leaderboard_cache(id PK, metric,       -- frequency / volume / calories / streak
                  window,              -- 7d / 30d
                  payload_json,        -- 预计算排名结果
                  computed_at)         -- 每日 23:30 全量重建

-- 变更：settings 从单行表改为每用户一行
settings(id PK, user_id FK UNIQUE,
         garmin_token_store_enc, garmin_email_enc, garmin_password_enc,
         xunji_api_key_enc, xunji_body_api_key_enc,
         default_llm, llm_keys_json_enc,
         leaderboard_opt_out_json,  -- {"frequency": false, "volume": true, ...}
         created_at, updated_at)

-- 变更：以下表新增 user_id + 复合 UNIQUE
xunji_train:      UNIQUE(user_id, datestr, localid)
garmin_activity:  UNIQUE(user_id, activity_id)
garmin_daily:     UNIQUE(user_id, date)
body_metric:      UNIQUE(user_id, date, type)
workout:          无 UNIQUE 变更，但所有查询按 user_id 过滤
match_candidate:  新增 user_id
xunji_plan:       UNIQUE(user_id, plan_ref)
ai_report:        新增 user_id，type + period_start + period_end 复合索引
llm_call:         新增 user_id
job_run:          新增 user_id（NULL 表示系统级任务，如全量排行榜预计算）
report_chat_message: 新增 user_id
```

## 5. 非功能需求

### 5.1 安全
- 密码 bcrypt（cost=12），禁止可逆存储；
- 佳明/训记/LLM 凭据 Fernet 加密，密钥仍从环境变量 `FERNET_KEY` 读取；
- 佳明 token 统一存 `settings.garmin_token_store_enc`（数据库），**不使用文件缓存目录**，备份随 pg_dump；
- **【V1.1 强制项】多用户上线前必须启用加密传输**：用户名/密码/token 不得走 HTTP 明文。
  方案 A：域名 + ICP 备案 + Caddy 443（正式）；
  方案 B：Tailscale/WireGuard 加密组网（免备案，仅熟人小圈子可达）；
  HTTP 明文仅限当前单用户过渡期，多用户账号体系启用前必须二选一落地；
- 所有 API 查询强制 user_id 过滤，禁止"管理员看全部"的裸查询（必须走显式 `?user_id=` 参数 + 权限校验）。

### 5.2 性能
- 10 用户串行同步总耗时 ≤ 5 分钟；
- 排行榜预计算每日 23:30 执行，查询响应 < 200ms；
- 关键页面（日历/详情/趋势）按 user_id 过滤后数据量与单用户版一致，性能不退化。

### 5.3 运维
- 备份策略：沿用 compose pg_dump 容器，备份内容含全部用户数据（无分库分表）；
- 监控：管理员健康面板覆盖"每用户最近同步时间"，超过 48h 未同步高亮告警。

## 6. 技术方案概要

### 6.1 认证架构（V1.1 修订：不透明 token 落库）
```
登录 → 验证 users 表 → 生成不透明随机 token（secrets.token_urlsafe）
     → 落 auth_token 表（token / user_id / expires_at=now+7d）
     → 请求时 require_auth 查表解析 → 注入 current_user
     → 所有查询追加 user_id 过滤
停用/重置密码 → 删除该用户 auth_token 行 → 立即 401
服务重启 → token 不丢（持久化在 DB）
```
> 不用 JWT 的原因：需要"停用立即失效"与"重启不丢"，有状态 token 最直白；
> 单容器单 worker 场景无分布式会话问题。

### 6.2 同步调度改造
```
APScheduler 22:47 触发
  → 查询所有 is_active=True 且已绑定外部账号的用户
  → for user in users:
      → 从 settings 表读该用户佳明 token / 训记 Key（Fernet 解密）
      → 创建该用户的 GarminClient / XunjiClient（限频状态按 Key 隔离）
      → daily_sync(user_id=user.id)
      → 失败捕获，写 job_run，continue
```

### 6.3 前端路由
```
/login                    → 登录页
/admin/users              → 管理员用户管理
/admin/health             → 管理员健康面板
/leaderboard              → 圈子排行榜
/settings                 → 我的设置（分节）
/*                        → 现有页面，数据自动按当前用户过滤
```

## 7. 明确不做（防范围蔓延）

- 不做公开注册、邮箱验证、密码找回（管理员手动重置）；
- 不做用户间私信、评论、点赞等社交功能；
- 不做分库分表、SaaS 化计费、多租户隔离到数据库级别；
- 不做微信/QQ/手机号第三方登录；
- 不做用户数据导出/删除的自助服务（管理员代操作）。

## 8. 风险与开放问题

| # | 风险/问题 | 影响 | 缓解/待决策 |
|---|-----------|------|-------------|
| R1 | 佳明多账号共用服务器出口 IP，并发登录可能触发佳明 IP 级 429 | 同步失败率上升 | 串行同步 + 每用户独立 429 退避；必要时引入"每用户独立出口 IP"（成本过高，暂不考虑） |
| R2 | 用户自填 LLM Key 的质量参差不齐，部分用户可能填无效 Key | AI 功能对该用户不可用 | 绑定前真实 ping 验证；无效 Key 明确提示 |
| R3 | 排行榜"总容量"指标对纯有氧用户不公平 | 用户挫败感 | 允许用户退出某类榜；前端标注"力量向指标" |
| R4 | 管理员代用户修正数据的审计日志粒度 | 争议时无法追溯 | audit_log 记录前后值摘要，不记全量 diff（性能考虑） |
| R5（V1.1） | 多用户账号密码走 HTTP 明文会被中间人截获 | 凭据泄露 | **强制项**：多用户启用前落地 HTTPS/加密组网（§5.1），未完成不邀请任何用户 |
| R6（V1.1） | 改造中间态误部署：模型已加 user_id 但业务查询未过滤（M1-3～M2-4 期间），或 M1-4 回填前合并导致存量数据"不可见" | 数据混乱/线上事故 | **合并红线**：M2-5 完成前禁止部署与合并 main；M1-4 回填完成前禁止合并。写入开发计划通用前缀 |

## 9. 里程碑建议

| 阶段 | 内容 | 预估工作量 |
|------|------|-----------|
| M-M1 | 数据模型改造（users 表 + user_id 迁移 + PG 切换） | 2 天 |
| M-M2 | 认证系统（登录/密码哈希/token 落库/权限注入） | 2 天 |
| M-M3 | 外部账号绑定（佳明/训记/LLM Key 按用户隔离） | 2 天 |
| M-M4 | 同步调度多用户化 + 管理员后台 | 2 天 |
| M-M5 | 排行榜 + 前端多用户适配 | 2 天 |
| M-M6 | 联调、迁移演练、文档更新、**HTTPS/加密组网落地（M6-4，V1.1 新增）** | 1.5 天 |

**总计约 11.5 个工作日**，建议按 M-M1 → M-M2 → M-M3 → M-M4 → M-M5 → M-M6 顺序执行，每阶段完成后打 tag。

> **合并红线（V1.1）**：M2-5（数据访问层权限过滤）完成前，multiuser-v2 分支禁止部署到生产、禁止合并 main；M1-4（存量数据回填）完成前禁止合并 main。

---

*本 PRD V1.1 已于 2026-08-24 二次评审修订定稿。*
