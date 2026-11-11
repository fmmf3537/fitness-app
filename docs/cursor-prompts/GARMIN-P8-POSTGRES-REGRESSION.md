# GARMIN-P8 Cursor 开发提示词：PostgreSQL 状态机与发布回归修复

> 你是本仓库的资深后端工程师（SQLAlchemy 2 + Alembic + PostgreSQL + pytest）。只完成 P8 代码与测试，**不部署、不执行 Git、不访问 Garmin/LLM、不运行全量验收**。Deepseek Harness 将独立运行 PostgreSQL 和全量测试。
>
> 红线：禁止真实 `.env`、正式 `backend/data/app.db`、生产 PostgreSQL、真实 Garmin 和真实 LLM；禁止跳过/删除失败测试、降低覆盖率、放宽每日 5 次限流或 Garmin 冲突门禁；禁止为通过测试而增加自动重试创建 POST。

## 1. 目标

A. 让 PostgreSQL 迁移测试显式覆盖 Garmin 同步表及关键状态机语义。

B. 修复既有 `TestDailyRegenLimit.test_real_closed_loop_5_ok_then_429` 的 UTC/本地日期跨日根因，使全量发布测试可以恢复全绿。

已核实上下文：

- 最新 Alembic head：`c5d6e7f8a9b0`。
- `garmin_plan_sync` 当前 22 个字段；唯一约束为 `source_key` 和 `(plan_ref, training_date)`。
- `backend/tests/test_alembic_postgres.py` 的 `ALL_TABLES` 尚未列出 `garmin_plan_sync`。
- Garmin 本地/FakeGarmin 已有完整实现和测试，P6 真实进程恢复已通过；本阶段不重写业务逻辑。
- `LLMCall.created_at` 只有数据库 `server_default=func.now()`；`_check_regen_limit` 使用 `date.today()` 和本地 `datetime.combine(...)` 统计。SQLite `func.now()` 的 UTC 日期与本地清晨日期可能跨日，导致真实闭环前 5 次未被计入。
- 不得简单改测试时间、提高上限、删除第 6 次 429 断言或标记 xfail/skip。

开始前实读：三个 Garmin 迁移、`backend/app/models.py`、`backend/app/services/garmin_plan_sync.py`、`garmin_reschedule.py`、`backend/app/services/ai.py` 的 `_check_regen_limit`、`backend/tests/test_regenerate_with_feedback.py`、`test_alembic_postgres.py`、`test_garmin_plan_sync_write.py`、`test_garmin_reschedule_write.py` 和 `tests/conftest.py`。

## 2. 文件预算

允许修改/新增：

1. 改 `backend/tests/test_alembic_postgres.py`
2. 新 `backend/tests/test_garmin_plan_sync_postgres.py`
3. 改 `backend/tests/test_regenerate_with_feedback.py`
4. 改 `backend/app/models.py`（仅限 LLMCall 时间语义根因所需的最小改动）
5. 改 `backend/app/services/ai.py`（仅确为统一日期限流语义所需；可不改）
6. 改 `backend/app/services/garmin_plan_sync.py`（仅 PostgreSQL 实测暴露 dialect/concurrency bug 时最小修复）
7. 改 `backend/app/services/garmin_reschedule.py`（同上）

不得修改迁移版本、前端、部署制品、其他业务模块或真实数据。若需新增迁移，说明为什么现有表不兼容并停止，不得自行添加。

## 3. PostgreSQL 迁移与状态机测试

### 3.1 迁移断言

在 `test_alembic_postgres.py`：

- 将 `garmin_plan_sync` 纳入 `ALL_TABLES`，离线和在线测试都必须真正检查。
- 在线升级后断言 22 个字段完整，两个唯一约束存在且列组合正确，`alembic current == heads == c5d6e7f8a9b0`。
- 保留已有其他表检查，不通过缩减清单规避历史问题。

### 3.2 独立 PostgreSQL Garmin 测试

新文件必须使用 `TEST_DATABASE_URL_PG` 或 testcontainers 的**一次性测试库**；无法取得安全测试库时 skip 并说明，绝不能回退到正式 app.db。CI 服务容器与本地 testcontainers 都要支持。

测试前校验 URL 明确属于测试环境；只清理本测试创建的 Garmin 数据。每个测试独立提交/关闭 Session 和 engine，避免跨测试脏状态。

使用 FakeGarmin/FakeAdapter，禁止导入或实例化真实 Garmin client。至少覆盖：

1. 两个独立 Session 并发/交错 claim，只有一个获得 runner；数据库只有 1 条来源记录。
2. `syncing` 超时 CAS 从 attempt 1 转 failed，重新 claim 为 attempt 2；`recovery=stale_syncing` JobRun 正确。
3. 旧 attempt 的完成写入不能覆盖新 attempt。
4. 创建响应丢失后按来源键认领同一 Workout；日程响应丢失后按 Workout+日期认领同一日程，创建次数不增加。
5. 已同步记录跨日顺延，原 Workout ID 和日程 ID 保持，目标日期、来源键、审计字段正确。
6. 来源不符、多候选或目标冲突进入 conflict，不盲发创建/更新。

可复用现有 FakeAdapter 和计划构造函数，但不得让共享 `session` 夹具把 PG 测试偷偷切回 SQLite。测试结束输出实际 DB dialect 断言为 postgresql。

## 4. AI 每日限流跨日修复

先根据源码确认根因，再选择最小、统一的时间语义：

- 推荐方向：ORM 新写入的 `LLMCall.created_at` 使用与 `_check_regen_limit` 一致的本地 naive 时间，同时保留数据库 server_default 兼容既有/raw SQL 写入；不需要 schema 迁移。
- 若选择 UTC 方案，必须同时修改读取口径和所有相关调用，不能只在测试环境有效；不得破坏现有历史数据统计。
- 查询应有明确的当日开始和下界/上界语义，不能只针对某个日期 hardcode。

新增回归测试必须证明：

1. 真实 ORM 默认写入时间与限流读取处于同一“服务器本地日”。
2. 本地凌晨与 UTC 已跨日时，连续 5 次成功、第 6 次仍 429。
3. 昨日记录不计入，其他 workout/type 不计入，原有限流 API 契约不变。
4. 测试时钟可注入时优先注入，禁止 sleep 等待真实跨日。

## 5. 限制与交付

- P7 的 Docker/Compose/CI 不在本阶段修改。
- 不运行真实 Garmin/LLM，不创建任何远端对象。
- 不把 PostgreSQL 不可用伪报为通过；测试设计必须让 Harness 能区分 pass 和 skip。
- 开发阶段只允许做语法/静态自检，不跑全量 pytest。

最终报告：

1. 实际改动文件、根因和最小修复说明。
2. 新增 PostgreSQL/AI 测试名称和各自证明的行为。
3. 是否修改 Garmin 生产逻辑；若修改，给出失败证据和兼容性分析。
4. 明确未访问真实服务、正式数据库和 Git，未降低测试要求。
5. 列出 Harness 必须实际运行的 PG、后端全量、前端全量、lint/build 检查，不得预写通过数字。
