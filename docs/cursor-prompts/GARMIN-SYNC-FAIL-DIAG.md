# GARMIN-SYNC-FAIL 诊断提示词：定位「Garmin 同步失败」的根因（服务器只读优先）

> 使用位置：生产服务器项目目录（`/home/ubuntu/fitness-app`），由 Cursor CLI 执行。
> 本提示词只做**诊断**，不做修复。修复动作一律先报告、等账号所有者批准后再执行。

## 0. 背景（必须理解，否则会误判）

用户在页面点击「确认同步」后，界面提示 **「Garmin 同步失败」**。UI 只显示这句泛化文案，
真实原因记录在 `garmin_plan_sync` 表的 `error_code` / `last_error` 字段与后端日志里。

**时间线重要线索**：在失败发生前，刚部署了一次映射变更（commit `aa9a30f`），其中把
「侧平举」从通用项改成了哑铃专用项：

| | 映射 | 说明 |
|---|---|---|
| 改前 | `LATERAL_RAISE` / `LATERAL_RAISE` | 通用项，P3 期间真机验证过能创建 |
| 改后 | `LATERAL_RAISE` / `DUMBBELL_LATERAL_RAISE` | 该值只在 garminconnect 的**静态目录**里存在，**从未真实创建过** |

`DUMBBELL_LATERAL_RAISE` 是首要怀疑对象：静态目录来自 Workout 编辑器导出，
不代表创建 API 一定接受。

## 1. 不可违反的红线

1. **禁止再次点击/触发同步**。每次同步尝试都可能创建远端对象或撞 429 限流；
   重复尝试会让现场失真。本提示词全程**只读**，除非第 5 节的条件成立且用户批准。
2. 禁止删除任何 Garmin 远端对象、数据库记录、卷、备份。
3. 禁止 `docker compose down -v`、禁止删除/重建卷。
4. 禁止读取或打印密码、token、Cookie、完整 `.env`、完整进程环境。
   查 `.env` 只允许 `grep -c` 或比对哈希，不得 `cat`。
5. 禁止修改 `.env`、代码、数据库（本阶段）；发现需要修改时写进报告等批准。
6. 禁止执行任何 git 写操作（commit / push / reset / checkout / stash）。
7. 遇 429 立即停止并报告，等冷却（≥30 分钟）后再由用户决定下一步。
8. 不得把远端返回的原始响应正文直接打印（可能含 token）；只打印状态码与错误类型。

## 2. 第一步：确认部署状态（只读）

```bash
cd /home/ubuntu/fitness-app
git log --oneline -3
git status --short          # 应只有 docker-compose.override.yml 等已知未跟踪项
docker compose ps
docker compose exec backend alembic current
docker compose exec backend alembic heads
```

要核对的事实：
- HEAD 是否包含 `aa9a30f`（侧平举映射变更）
- `alembic current == heads == e7f8a9b0c1d2`（映射数据迁移已执行）
- backend 是否 healthy

## 3. 第二步：取失败记录（核心证据）

```bash
docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" <<'SQL'
\pset pager off
SELECT id, plan_ref, training_date, status, phase, error_code, attempt_count,
       workout_id, workout_schedule_id, mapping_hash,
       left(coalesce(last_error,''), 600) AS last_error,
       created_at, updated_at, synced_at
FROM garmin_plan_sync
ORDER BY updated_at DESC NULLS LAST
LIMIT 8;
SQL
```

> 若 `$POSTGRES_USER` 为空，改用 `.env` 里的值（`grep -E '^POSTGRES_(USER|DB)=' .env`，只看键名不必打印值）。
> 若容器内 psql 不可用，退化为 `docker compose exec backend python -c "..."` 查 ORM。

**必须记录**：失败那条的 `training_date`、`status`、`phase`、`error_code`、`last_error` 全文、
`attempt_count`、是否已有 `workout_id`（若已有，说明是**更新**失败而非首次创建失败）。

## 4. 第三步：确认映射与计划内容

```bash
docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" <<'SQL'
\pset pager off
SELECT xunji_name, garmin_category, garmin_exercise_name, garmin_display_name,
       weight_strategy, status, verified_level, source, mapping_version, note
FROM exercise_mapping
WHERE xunji_name IN ('侧平举','哑铃上斜俯身侧平举','器械推胸')
ORDER BY xunji_name;
SQL
```

再确认**失败那个训练日的动作清单里到底有没有「侧平举」**：

```bash
docker compose exec backend python - <<'PY'
import json
from app.db import SessionLocal
from app.models import GarminPlanSync
from app.services import plans as plan_service
s = SessionLocal()
try:
    rec = (s.query(GarminPlanSync)
             .order_by(GarminPlanSync.updated_at.desc()).first())
    print('record:', rec.training_date, rec.plan_ref, rec.status, rec.error_code)
    payload = json.loads(rec.payload_json or '{}')
    def walk(o):
        out = []
        if isinstance(o, dict):
            if o.get('category'):
                out.append((o.get('category'), o.get('exerciseName')))
            for v in o.values(): out += walk(v)
        elif isinstance(o, list):
            for v in o: out += walk(v)
        return out
    for pair in walk(payload):
        print('  step:', pair)
finally:
    s.close()
PY
```

这一步能直接看出：失败那次 payload 里**是否包含 `DUMBBELL_LATERAL_RAISE`**。
如果包含，且 error_code 是创建类错误 → 基本可以定位。

## 5. 第四步：读日志关联错误

```bash
docker compose logs backend --since 6h --tail 400 2>&1 \
  | grep -iE 'garmin|PlanSync|GarminWorkout|Traceback|ERROR' | tail -60
```

重点找：
- `GarminWorkoutAdapterError` 的 `error_code` / `operation` / `status_code`
- 是否出现 `400` / `422`（创建被拒）而不是 `401` / `429`
- 是否有 `GARMIN_WORKOUT_READBACK_INVALID`（创建成功但回读不符）

也可看前端 nginx 侧是否有 5xx：

```bash
docker compose logs frontend --since 6h --tail 200 2>&1 | grep -E ' 5[0-9][0-9] ' | tail -20
```

## 6. 第五步：归因（按 error_code 判定，不要猜）

| error_code | 根因 | 结论 |
|---|---|---|
| `GARMIN_AUTH_REQUIRED` | token 失效 | 与映射无关；检查 `/root/.garminconnect` 是否还在、开关是否 1 |
| `GARMIN_RATE_LIMITED` | 429 | 与映射无关；**立即停止**，冷却 ≥30 分钟 |
| `GARMIN_REQUEST_FAILED` + `last_error` 含 400/422 | 创建被拒 | **高度怀疑 `DUMBBELL_LATERAL_RAISE`** |
| `GARMIN_WORKOUT_READBACK_INVALID` | 创建成功但回读结构不符 | 可能是 exerciseName 被 Garmin 改写；记录观测值 |
| `PLAN_CHANGED` | 预览后计划变了 | 与映射无关；重新预览再确认即可 |
| `GARMIN_MAPPING_UNSUPPORTED` | 有动作映射未激活 | 检查 `exercise_mapping.status` |

**关键判定规则**：
- 若 `last_error` / 日志里出现 `DUMBBELL_LATERAL_RAISE`，或失败 payload 含该值且错误是创建类
  → 结论为「新增映射值不被 Garmin 创建 API 接受」，建议**回滚该条映射**。
- 若错误与映射无关（401/429/PLAN_CHANGED）→ 按对应处置，**不要动映射**。

## 7. 第六步：受控验证（**仅在第五步无法定论、且用户明确批准时**）

**默认不做。** 只有同时满足以下条件才允许：
1. 第五步无法归因（例如错误被泛化成无状态码的 `GARMIN_REQUEST_FAILED`）
2. 账号所有者**明确同意**做一次会写 Garmin 的实验
3. 距离上次任何 Garmin 写操作 ≥ 10 分钟（避开 429）

做法（最小、自清理，**只允许一个动作一个组**）：

```bash
docker compose exec backend python - <<'PY'
from app.config import get_settings
from app.adapters.garmin_workout_adapter import GarminWorkoutAdapter
from app.services.exercise_catalog_probe import build_probe_payload, probe_one

s = get_settings()
assert s.garmin_plan_sync_enabled, '写入开关未开，禁止实验'
adapter = GarminWorkoutAdapter.from_settings(s)

# 只探测这一个组合；probe_one 会在回读后删除创建的对象
res = probe_one(adapter, 'LATERAL_RAISE', 'DUMBBELL_LATERAL_RAISE')
print('status   =', res.status)
print('observed =', res.observed_category, res.observed_exercise_name)
print('deleted  =', res.deleted)
print('note     =', res.note)
PY
```

判读：
- `status='verified'` 且 `deleted=True` → 该值**可以创建**，问题在别处（回到第五步）
- `status='failed'` 且 note 含 400/422 → 该值**不被接受**，建议回滚映射
- `deleted=False` → **必须立刻报告 workout_id**，让用户手动删除

## 8. 报告要求（无论结论如何都要给出）

1. **结论**：一句话根因（例：「`DUMBBELL_LATERAL_RAISE` 被 Garmin 创建 API 拒绝（422）」）。
2. **证据链**：
   - HEAD / alembic 状态
   - `garmin_plan_sync` 那一条的完整字段（`last_error` 可截断到 600 字）
   - payload 里出现的 `(category, exerciseName)` 列表
   - 日志中相关错误的原文片段（**过滤掉任何 token/密码**）
3. **是否与 `aa9a30f` 的映射变更相关**：是 / 否，并说明判据。
4. **建议动作**（三选一，写明执行方与风险）：
   - A. 回滚「侧平举」映射到通用 `LATERAL_RAISE`（推荐，若确认是该值被拒）
   - B. 与环境有关（token/限流），按对应处置，不动映射
   - C. 需要更多证据，列出还缺什么
5. **未执行项**：明确写「未做任何 Garmin 写操作 / 未改数据库 / 未改 .env / 未执行 git」，
   若做了第六步实验也如实写明并附结果。
6. **剩余风险**。

## 9. 禁止事项汇总

- 不重复触发同步、不反复重启 backend
- 不创建/删除/改期任何 Garmin 对象（第六步经批准的最小实验除外，且必须自清理）
- 不改数据库、不改 `.env`、不改代码、不做 git 写操作
- 不打印 secret；不 `cat .env`
- 不在 429 后继续尝试
