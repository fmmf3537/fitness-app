# ADR-P0-3b 同步层：partial 状态 + 缺口记录 + 名称标记落地

> 你是本仓库的资深后端工程师（FastAPI + SQLAlchemy 2.x + Alembic + pytest）。
> 本提示词是唯一任务来源：只按本提示词写代码，**不跑任何验收命令（pytest 一律不跑）**，**不执行任何 git 命令**。
> 红线：禁整文件重写（外科式最小修改）；所有写出的文件必须无 BOM、UTF-8；不得修改 `.env` / `.env.*`；不得删除任何既有文件；不得改动本提示词文件预算之外的任何文件。

## 需求背景

前两片已就绪：
- **ADR-P0-2**：`load_all_mappings(session, include_excluded=True)` 可返回 `not_applicable` 行；
  `map_plan_day` 把它们放进 `excluded`，不产 issue。
- **ADR-P0-3a**：`map_plan_day(..., allow_partial=True)` 把 `UNKNOWN_EXERCISE` /
  `MAPPING_NOT_APPROVED` 降级进 `skipped`，其余 issue 继续抛错；全不可写抛
  `NO_WRITABLE_MOVEMENTS`；skipped 非空时在 `workoutName` 追加「（缺 N 个动作）」。

本片把两者接到**同步链路**上（ADR §7.2 / §7.3）：同步不再因为单个映射缺口整天失败，
而是写入可写动作、状态记为 `partial`、结构化记录缺口。**这是本阶段唯一改变线上同步行为的一片。**

## 已核实的关键事实（实读代码，可直接采信）

- `backend/app/models.py` 的 `GarminPlanSync` 关键列：
  `plan_ref / training_date / source_key / source_hash / content_hash / synced_hash /
   payload_json / mapping_hash / status / phase / attempt_count / workout_id /
   workout_schedule_id / error_code / last_error / synced_at / created_at / updated_at`
  `status` 是 `String(20)`，**无枚举约束**；现有取值 `pending / syncing / synced / failed / conflict`，
  另 `reschedule_pending` 用于顺延。
- `backend/app/services/garmin_plan_sync.py`
  - `_claim_plan_sync(...)` 里约第 366 行：
    ```python
    mappings = mapping_service.load_all_mappings(session)
    preview = map_plan_day(plan_day, mappings=mappings)
    ```
    之后把 `preview["workout"]` 存进 `payload_json`
  - `run_plan_sync(session, record_id, *, adapter=None)`：从 `record.payload_json` 反序列化 desired，
    走 create/认领 → update → 回读 → `_finish(..., status="synced")`
  - `_finish(session, record, *, started_at, expected_attempt, status, error_code=None, message=None)`：
    ```python
    values = {status, error_code, last_error, updated_at}
    if status == "synced":
        values.update({phase: "verify", synced_hash: record.source_hash, synced_at: finished_at})
    ```
  - `sync_status_view(record, *, source_key, source_hash)`：
    在 `record.synced_hash == source_hash and workout_id and workout_schedule_id` 时直接返回
    `status = "synced"` —— **partial 记录会因此被误报成 synced，必须处理**
  - `sync_status_view` 返回 dict 里已有 `status / phase / source_hash / synced_hash /
    workout_id / workout_schedule_id / error_code / last_error / attempt_count` 等字段
- `backend/app/api/plans.py`
  - `_current_sync_status()` 直接转发 `sync_status_view()` 的结果
  - `GET /plans/{day}/garmin/preview` 已在 ADR-P0-2 中改用 `include_excluded=True`
  - 同步端点把 `WorkoutMappingError` / `PlanSyncError` 转成 422/409
- Alembic 当前单 head：**`a9b0c1d2e3f4`**
  （`backend/alembic/versions/a9b0c1d2e3f4_exercise_mapping_relation.py`）

## 文件预算（共 6 个，不得越界）

改 3：
1. `backend/app/models.py`（`GarminPlanSync` 加 `sync_result_json`）
2. `backend/app/services/garmin_plan_sync.py`
3. `backend/app/api/plans.py`

新增 3：
4. `backend/alembic/versions/b0c1d2e3f4a5_garmin_plan_sync_result.py`（`down_revision = "a9b0c1d2e3f4"`）
5. `backend/tests/test_plan_sync_partial.py`
6. `backend/tests/test_alembic_sync_result_migration.py`

**禁止修改**：`garmin_workout_mapper.py`、`exercise_mapping*.py`、`garmin_reschedule.py`、
任何前端、`.env`、任何既有测试文件。

## 开发内容

### 1. `models.py`：`GarminPlanSync` 加 `sync_result_json`

在 `payload_json` 之后插入：

```python
    # ADR §7.2：同步结果的结构化记录（written / skipped / excluded 三类分开）。
    # 必须与 payload_json 分开：后者是「期望 Workout payload」，被回读比对与
    # stale 判定消费，混入结果会破坏 _extract_xunji_names_from_payload()。
    sync_result_json: Mapped[str | None] = mapped_column(Text)
```

### 2. 迁移 `b0c1d2e3f4a5_garmin_plan_sync_result.py`

- `revision = "b0c1d2e3f4a5"`、`down_revision = "a9b0c1d2e3f4"`
- `upgrade()`：`op.add_column("garmin_plan_sync", sa.Column("sync_result_json", sa.Text(), nullable=True))`
- `downgrade()`：`op.drop_column("garmin_plan_sync", "sync_result_json")`
- 风格照抄 `a9b0c1d2e3f4_exercise_mapping_relation.py`

### 3. `garmin_plan_sync.py`

#### 3.1 claim 阶段：改用 partial 模式并落库缺口

`_claim_plan_sync` 中：

```python
mappings = mapping_service.load_all_mappings(session, include_excluded=True)
preview = map_plan_day(plan_day, mappings=mappings, allow_partial=True)
```

构造记录时（`GarminPlanSync(...)` 与 `_claim_existing(...)` 的 update 字典**两处都要**）写入：

```python
sync_result_json=json.dumps(_sync_result(preview), ensure_ascii=False)
```

新增模块内私有函数：

```python
def _sync_result(preview: dict[str, Any]) -> dict[str, Any]:
    """ADR §7.2：三类动作不得混成一个警告列表。"""
    return {
        "written_movements": [
            m.get("name") for m in (preview.get("movements") or []) if m.get("name")
        ],
        "skipped_movements": list(preview.get("skipped") or []),
        "excluded_movements": list(preview.get("excluded") or []),
    }
```

> `NO_WRITABLE_MOVEMENTS` 由 mapper 抛出，走现有 `WorkoutMappingError` 路径
> （不落记录、不产生远端对象），无需在此特殊处理。

#### 3.2 完成阶段：partial 也算成功写入

`run_plan_sync` 结尾调用 `_finish` 处，把 status 按缺口决定：

```python
finite_status = "partial" if _has_skipped(record) else "synced"
_finish(session, record, started_at=started_at, expected_attempt=expected_attempt, status=finite_status)
```

新增：

```python
def _has_skipped(record: GarminPlanSync) -> bool:
    """读取 claim 阶段落库的缺口记录（解析失败按无缺口处理，不阻断同步）。"""
```

实现要求：`json.loads(record.sync_result_json or "{}")`，取 `skipped_movements`，非空即 True；
任何 `TypeError/ValueError/json.JSONDecodeError` 或非 dict 结构一律返回 False。

`_finish` 里：

```python
if status in ("synced", "partial"):
    values.update({phase: "verify", synced_hash: record.source_hash, synced_at: finished_at})
```

（partial 与 synced 一样记录 `synced_hash`：内容已按当前计划写入，只是有缺口。）

#### 3.3 状态视图：partial 不得被 hashes 命中覆盖成 synced

`sync_status_view` 里，在现有 `synced_hash == source_hash` 判定**之前**插入：

```python
if record.status == "partial":
    status = "partial"
elif (...原有 synced 判定...):
```

即：只要记录是 partial，就报告 partial，即使 hash 相同。

返回 dict 增加两个字段（放在 `last_error` 之后）：

```python
"sync_result": _sync_result_for_view(record),
```

`_sync_result_for_view(record)`：解析 `sync_result_json`，返回
`{"written": n, "skipped": n, "excluded": n, "skipped_movements": [...]}`；
解析失败或无记录时返回 `{"written": 0, "skipped": 0, "excluded": 0, "skipped_movements": []}`。
**不要**把完整 written 列表放进状态视图（会很长），只放计数 + skipped 明细。

#### 3.4 恢复/顺延路径不要被破坏

`recover_stale_syncing` 里写 `JobRun(job_name=...)` 的分支、`_raise_record_busy_or_conflict`、
`ACTIVE_RESCHEDULE_STATUSES` 等一律不动。`status="partial"` 不得被当成"活动状态"参与
抢占判断（只有 `syncing` 才是）。

### 4. `api/plans.py`

`_current_sync_status()` 无需改逻辑（它转发 `sync_status_view`），
但**确认**它不额外过滤 status 取值。若同步端点里存在「仅 `synced` 才算成功」的判断，改为
`in ("synced", "partial")`。

422 分支（`PLAN_MAPPING_UNSUPPORTED`）在 detail 里补 `excluded` 与 `skipped`
（取 `exc.excluded` / `exc.skipped`，两者都已有默认空列表）。

### 5. `tests/test_plan_sync_partial.py`（新，≥14 例）

用现有测试的假 adapter 风格（参考既有 `test_garmin_plan_sync*.py` 的 fake adapter；
**不要改既有测试文件**，可复制其 fixture 写法）。至少覆盖：

**claim 阶段（4 例）**
1. `test_claim_uses_include_excluded` —— 计划含拉伸动作时 claim 成功（不抛 UNKNOWN_EXERCISE）
2. `test_claim_stores_skipped_in_sync_result` —— 计划含未知动作时 `record.sync_result_json`
   的 `skipped_movements` 含该动作
3. `test_claim_stores_written_and_excluded` —— 三类都出现时 JSON 里三类分开且内容正确
4. `test_claim_payload_name_has_marker` —— 有 skipped 时 `payload_json` 的 `workoutName`
   含「（缺 1 个动作）」

**完成阶段（4 例）**
5. `test_run_sets_partial_when_skipped` —— 有 skipped 且远端写入成功 → `record.status == "partial"`
6. `test_run_sets_synced_when_no_skipped` —— 无 skipped → `"synced"`
7. `test_partial_still_sets_synced_hash_and_at` —— partial 也必须写 `synced_hash` 与 `synced_at`、
   `phase == "verify"`
8. `test_all_unwritable_does_not_call_adapter` —— 全不可写时抛 `WorkoutMappingError`
   且 fake adapter 的 `create_workout` **零调用**（ADR §7.2：不得先建空 Workout）

**状态视图（3 例）**
9. `test_status_view_reports_partial` —— partial 记录即使 hash 相同也返回 `status == "partial"`
10. `test_status_view_sync_result_counts` —— `sync_result` 里 written/skipped/excluded 计数正确
11. `test_status_view_sync_result_broken_json_is_safe` —— `sync_result_json` 是非法 JSON 时
    返回零值而不抛错

**不可降级（2 例）**
12. `test_unit_error_still_fails_whole_day` —— 动作缺 `unit` → 同步整体失败（status `failed`），
    不得记成 partial
13. `test_adapter_failure_still_failed` —— fake adapter 抛网络错误 → `status == "failed"`，
    且 `sync_result` 受理不受影响

**补全路径（1 例，契约级）**
14. `test_resync_after_fix_clears_partial` —— 首次 partial → 把该动作映射补齐后再次 claim+run
    → `status == "synced"`、`payload_json` 的 `workoutName` **不含**缺口标记、
    `workout_id` 与首次相同（不新建）

### 6. `tests/test_alembic_sync_result_migration.py`（新，≥3 例）

1. `test_single_head` —— 单 head 且等于 `b0c1d2e3f4a5`
2. `test_down_revision` —— `down_revision == "a9b0c1d2e3f4"`
3. `test_column_exists_in_model` —— `GarminPlanSync.__table__.columns` 含 `sync_result_json`
   且 `nullable is True`

## 自报告要求（交付时必须给出）

1. 改动文件清单（对照预算 6 个），每个文件改动行数与函数名。
2. **`sync_status_view` 里 partial 判定的插入位置**代码片段（必须在 hashes 判定之前）。
3. **实测 6 组同步结果表**：

   | 计划内容 | 期望 status | 期望 sync_result | workoutName |
   |---|---|---|---|
   | 全部可写 | synced | written=N, skipped=0 | 无标记 |
   | 力量+未知 | partial | written=1, skipped=1 | 缺 1 个动作 |
   | 力量+拉伸 | synced | written=1, excluded=1 | 无标记 |
   | 全未知 | 失败（无远端调用） | — | — |
   | 缺 unit | failed | — | — |
   | 补齐后再同步 | synced | skipped=0 | 无标记，workout_id 不变 |

4. 设计取舍：
   - 为什么 `sync_result_json` 不能复用 `payload_json`（引用 ADR §7.2 修订 R1）
   - 为什么 partial 也写 `synced_hash`
   - 为什么状态视图的 `sync_result` 只放计数 + skipped 明细，不放完整 written 列表
   - 为什么 `NO_WRITABLE_MOVEMENTS` 走 `WorkoutMappingError` 而不落记录
5. 确认清单：
   - 未跑 pytest
   - 未执行 git
   - 未改 `.env` 系列
   - 未改 `garmin_workout_mapper.py` / `exercise_mapping*.py` / `garmin_reschedule.py` /
     任何前端 / 任何既有测试文件
   - 文件无 BOM、UTF-8
6. 行为自检清单：
   - [ ] claim 用 `include_excluded=True` + `allow_partial=True`
   - [ ] 新建与 `_claim_existing` 两条路径都写 `sync_result_json`
   - [ ] `_finish` 对 partial 也写 `synced_hash/synced_at/phase`
   - [ ] 状态视图对 partial 优先返回 partial
   - [ ] 非法 `sync_result_json` 不抛错
   - [ ] 全不可写时 adapter 零调用
   - [ ] 缺 unit / 网络错误仍是 failed，不被记成 partial
   - [ ] 迁移单 head 且 `down_revision` 正确

## 明确不做

- 不改 mapper（P0-2 / P0-3a 已完成）
- 不改前端（预览/状态的三态展示留到前端切片）
- 不改 `garmin_reschedule.py`
- 不做 CATEGORY 降级开关（ADR §6，后续片）
- 不改启用策略 `batch_activate`（P0-4）
