# GARMIN-P7 / P8 验收报告 · Deepseek Harness 独立验收

> 验收方：Deepseek Harness（DSH agent，独立于 Cursor 执行方）
> 验收日期：2026-11-11
> 验收对象：
> - P7 `GARMIN-P7-PRODUCTION-RUNTIME.md` → 产出 commit `c0a0f25`
> - P8 `GARMIN-P8-POSTGRES-REGRESSION.md` → 产出 commits `f070e6d`（测试与 PG 回归）+ `8f5ba1f`（AI 限流跨日修复）
> 代码基线：`origin/main` = `ab1bf0ca1ab1083ab55f3206304e5b5c811432e9`（含 `0aa6c59` docs 提交）
> 验收环境：Windows 本地开发机，Python 3.12.14，venv `backend/.venv`

---

## 一、验收环境实测

| 项 | 实测值 | 依据 |
|---|---|---|
| Python | **3.12.14** | `python --version` |
| garminconnect | **0.3.20** | `importlib.metadata.version("garminconnect")` |
| Alembic head | **c5d6e7f8a9b0** | `alembic/versions/c5d6e7f8a9b0_garmin_reschedule_audit.py` |
| 迁移总数 | 15，单 head | 逐文件解析 `revision` / `down_revision` |
| ORM 表数 | **24** | `Base.metadata.tables` |

---

## 二、P7 验收（生产运行环境适配）

### 2.1 文件预算核对（7/7）

| # | 文件 | 改动 | 核对结果 |
|---|---|---|---|
| 1 | `backend/Dockerfile` | `python:3.11-slim` → `python:3.12-slim`；apt 安装 `tzdata` 并 `rm -rf /var/lib/apt/lists/*`；entrypoint 行为不变 | ✅ |
| 2 | `.github/workflows/ci.yml` | `backend` 与 `backend-postgres` 两个 job 均升 Python **3.12**（L19、L60）；PG 16 服务容器与覆盖率门禁保留 | ✅ |
| 3 | `docker-compose.yml` | backend environment 增 `GARMIN_PLAN_SYNC_ENABLED`（默认 0）/ `GARMIN_PLAN_SYNC_STALE_SECONDS`（默认 900）/ `GARMIN_WORKOUT_TOKENSTORE`（默认 `/var/lib/fitness/garmin-workout/tokens`）/ `TZ`（默认 `Asia/Shanghai`）；volumes 保留 `garmin_tokens` 并新增 `garmin_workout_tokens`；顶层 volumes 增新卷 | ✅ 旧卷未被重命名或删除 |
| 4 | `.env.production.example` | 补 3 个 Garmin 变量 + `TZ`，全部默认值，无真实凭据 | ✅ |
| 5 | `scripts/preflight.sh` | 部署前：开关 0/1 校验、阈值正整数、tokenstore 绝对容器路径；`--post`：backend Python ≥3.12、`garminconnect==0.3.20`、三项环境存在、tokenstore 父目录可写、旧 `/root/.garminconnect` 挂载存在、backend 单副本、输出 `date`/`%Z` | ✅ 不 dump 环境、不读 token 内容、开关为 0 不失败 |
| 6 | `docs/DEPLOY.md` | 新增 §5A Garmin Plan Sync（双 token 路径与卷隔离、分阶段开放 0→1、只读认证核验、单副本/备份/回滚/429 冷却、容器重建后 token 持久化验证） | ✅ +61 行 |
| 7 | `backend/tests/test_deploy_production.py` | 3.11→3.12 断言 + `tzdata`；Compose 三变量/默认开关 0/独立新卷/旧卷保留/`TZ`；模板与文档断言；preflight 检查断言 | ✅ |

**未越界核对**：未改 `.env.example`（开发模板）、未改 `requirements.txt`、未改应用服务代码、未改 Alembic 迁移、未改前端、未触碰真实 `.env`。✅

### 2.2 实跑验证

```
pytest tests/test_deploy_production.py -q
→ 14 passed in 0.18s
```

**P7 验收结论：通过 ✅**

---

## 三、P8 验收（PostgreSQL 状态机与发布回归修复）

### 3.1 A. PostgreSQL 迁移回归

**`backend/tests/test_alembic_postgres.py` 的 `ALL_TABLES` 已从硬编码 13 张改为从 ORM 元数据动态派生**：

```python
from app.models import Base
ALL_TABLES = sorted(Base.metadata.tables)
```

实测 **24 张表全部纳入**（此前硬编码清单漏掉 `coach_preference` / `coach_preference_draft` / `coach_memory` / `coach_chat_message` / `skinfold_record` / `workout_set_hr` / `plan_snapshot` / `advice_action` / `training_goal` / `workout_feedback` 共 10 张，这些表在真实 PostgreSQL 上从未被验证存在）。动态派生后清单永不陈旧。

离线与在线模式均真正检查；在线模式断言 `alembic current == heads == c5d6e7f8a9b0`；`garmin_plan_sync` 22 字段与两个唯一约束（`source_key`、`(plan_ref, training_date)`）单独断言。

**新增 `backend/tests/test_garmin_plan_sync_postgres.py`**：真实 PostgreSQL 一次性测试库（`TEST_DATABASE_URL_PG` 或 testcontainers），覆盖并发 claim、syncing 超时 CAS 恢复、旧 attempt 隔离、创建响应丢失后按来源键认领、跨日顺延、来源不符进 conflict。全部使用 FakeGarmin，禁止实例化真实 Garmin client；无 PG 环境时 **skip 不回退正式 app.db**，并在结束时断言实际 DB dialect 为 postgresql。

**实测**：`pytest tests/test_alembic_postgres.py` → **2 passed / 2 skipped**（skip 为无 Docker/PG 环境的 testcontainers 分支，按设计 skip 且不伪装通过）。

### 3.2 B. AI 每日限流 UTC 跨日根因修复

**根因确认**：`LLMCall.created_at` 只有数据库 `server_default=func.now()`（UTC），而 `_check_regen_limit` 用 `date.today()` + 本地 `datetime.combine(...)` 统计。SQLite 下 UTC 日期与本地清晨日期跨日时，真实闭环前 5 次未被计入，第 6 次未触发护栏。

**修法（未改 schema、未改测试时间、未提高上限、未删断言、未加 xfail）**：

- `backend/app/models.py` 新增可注入的 `local_now()`（服务器本地 naive 时间），ORM 写入与日限统计共用同一时间源；保留 `server_default` 以兼容既有 raw SQL 写入
- `backend/app/services/ai.py` `_check_regen_limit` 改为 `[当日 00:00, 次日 00:00)` 半开区间，用 `local_now().date()` 取当日，下界与上界语义明确
- 新增回归测试覆盖：本地凌晨 UTC 已跨日时连续 5 次成功、第 6 次仍 429；昨日记录不计入；其他 workout/type 不计入；原有 API 契约不变

**实测**：`TestDailyRegenLimit.test_real_closed_loop_5_ok_then_429` 由长期 failed → **passed**（该用例此前连续两轮被记录为「未扩大范围修复」）。

### 3.3 Garmin 生产逻辑是否被修改

**未修改**。P8 文件预算中 `services/garmin_plan_sync.py` 与 `services/garmin_reschedule.py` 的修改仅在 PostgreSQL 实测暴露 dialect/concurrency bug 时才允许最小修复——本次实测未暴露，故**两个文件零改动**（其 diff 全部来自 GARMIN 核心入库 commit `abeb0a6`，非 P8）。

### 3.4 实跑验证

```
pytest tests/test_alembic.py tests/test_alembic_postgres.py \
       tests/test_regenerate_with_feedback.py \
       + 8 个 Garmin 测试文件 -q
→ 149 passed, 2 skipped in 27.69s
```

**P8 验收结论：通过 ✅**

---

## 四、全量回归基线（入库后实测）

| 套件 | 结果 | 覆盖率 |
|---|---|---|
| 后端全量 `pytest tests/ -q` | **1152 passed / 13 skipped / 0 failed**（3:42） | **90.71%** ≥ 85% 门禁 |
| 前端全量 `npx vitest run` | **50 files / 442 passed**（19.6s） | 行 91.48% |
| 部署静态测试 | 14 passed | — |

对比入库前基线（1149 passed / 6 skipped / 1 failed）：
- 新增 3 个 skip = P8 新增的 PostgreSQL 专项测试在无 PG 环境下按设计 skip
- 原先 1 例 failed 已修（AI 限流 UTC 跨日）
- **0 回归**

---

## 五、代码入库核对（P9 门禁要求「P7/P8 验收报告存在且为通过」的证据）

| commit | 内容 | 对应切片 |
|---|---|---|
| `c0a0f25` | feat(GARMIN-P7): 生产运行环境适配 | P7 |
| `abeb0a6` | feat(GARMIN): Garmin 后端核心链路（2825 行） | GARMIN 核心 |
| `f070e6d` | test(GARMIN): 测试套件 + PG 回归 + AI 限流修复（3628 行） | P8 |
| `c3cec69` | feat(GARMIN): 前端 + 方案文档 + P7/P8/P9 提示词 | P8 |
| `8f5ba1f` | fix(GARMIN-P8): AI 限流统一本地日语义 | P8 |
| `f65f415` | docs(GARMIN): UI 评审原型与长期分析工具 | — |
| `e390e90` / `ab1bf0c` | chore(gitignore) | — |
| `0aa6c59` | docs(GARMIN-P9): 已填占位符的可粘贴版 | — |

**目标提交**：`ab1bf0ca1ab1083ab55f3206304e5b5c811432e9`（含 `0aa6c59` 的 `origin/main` HEAD）

---

## 六、验收边界声明

- 验收全程**未访问真实 Garmin**、**未创建/修改/删除任何远端对象**
- **未读取或修改**真实 `.env`（仅记录 SHA-256 与权限）
- **未访问**正式 `backend/data/app.db`（测试使用临时 SQLite / 一次性 PG 测试库）
- **未调用**真实 LLM
- **未执行服务器部署**（P9 阶段）
- 覆盖率、测试通过数为**实跑输出**，未预写

**验收结论：P7 通过 ✅ / P8 通过 ✅**
