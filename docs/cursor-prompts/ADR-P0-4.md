# ADR-P0-4 启用策略：按 relation 而非 confidence 批量自动确认

> 你是本仓库的资深后端工程师（FastAPI + SQLAlchemy 2.x + Alembic + pytest）。
> 本提示词是唯一任务来源：只按本提示词写代码，**不跑任何验收命令（pytest 一律不跑）**，**不执行任何 git 命令**。
> 红线：禁整文件重写（外科式最小修改）；所有写出的文件必须无 BOM、UTF-8；不得修改 `.env` / `.env.*`；不得删除任何既有文件；不得改动本提示词文件预算之外的任何文件。

## 需求背景

ADR §5.1 规定批量自动确认的条件**不再以 `confidence` 为主闸门**：

> `relation = EXACT` **且** `confidence = high` **且** 目标有效（`verified_level` 至少 `catalog`）
> **且** 没有器械不符标记 **且** 不属于需要人工判断的黑名单

ADR §5.2 还规定：`SIMILAR` **不得仅凭 high 自动确认**；经人工或明确使用政策接受后可保持 active；
`CATEGORY` 必须大类归属可靠并人工/政策接受。

现状（已实测）：`batch_activate()` 只看 `status='draft' AND confidence='high' AND garmin_category IS NOT NULL`，
`only_confirmed_catalog=True` 时再检查目录里是否存在该组合。**完全不看 `relation`**。

后果：`relation` 落地后，若不同步改筛选条件，`SIMILAR` / `CATEGORY` 会被继续当成"精确匹配"批量启用
——这正是 ADR §5 要修的语义问题。

## 已核实的关键事实（实读代码，可直接采信）

- `backend/app/models.py` 的 `ExerciseMapping` 已有（ADR-P0-1 加的）：
  `relation(16) / match_basis(32) / unmapped_reason(32)`，均 nullable
- `backend/app/services/exercise_mapping.py`
  - `_catalog_pair_exists(category, exercise_name) -> bool`（第 311 行）：目录里是否存在该组合
  - `activate_mapping(session, mapping_id, *, reason=None, actor="user")`（第 538 行）：
    要求 `garmin_category` 非空，置 `status='active'`、`mapping_version += 1`、写审计 `action="activate"`
  - `batch_activate(session, *, confidence="high", only_confirmed_catalog=True, actor="user")`
    （第 686 行）：现状筛选见上
  - `_write_audit(session, row, action=..., before=..., after=..., reason=..., actor=...)`
- `backend/app/services/exercise_mapping_relation.py`（ADR-P0-1）：
  `RELATION_EXACT / RELATION_SIMILAR / RELATION_CATEGORY / RELATION_UNMAPPED`、`RELATIONS`
- `backend/app/services/exercise_mapping_candidates.py`：
  `equipment_mismatch_note(xunji_name, display_name)` —— 器械不符时返回文案，否则 `None`
- Alembic 当前单 head：**`b0c1d2e3f4a5`**
- 线上现状：`confidence='high'` 的 draft 约 292 条，其中器械不符 47 条（会被本次改为不自动确认）

## 文件预算（共 6 个，不得越界）

改 3：
1. `backend/app/models.py`（`ExerciseMapping` 加 `decision_source`）
2. `backend/app/services/exercise_mapping.py`（`batch_activate` 重写筛选 + `activate_mapping` 记来源）
3. `backend/app/api/exercise_mappings.py`（批量端点参数与响应对齐）

新增 3：
4. `backend/alembic/versions/c1d2e3f4a5b6_exercise_mapping_decision_source.py`
   （`down_revision = "b0c1d2e3f4a5"`）
5. `backend/tests/test_batch_activate_relation.py`
6. `backend/tests/test_alembic_decision_source_migration.py`

**禁止修改**：`exercise_mapping_relation.py`、`exercise_mapping_candidates.py`、
`exercise_mapping_batch.py`、`garmin_plan_sync.py`、`garmin_workout_mapper.py`、
任何前端、`.env`、任何既有测试文件。

## 开发内容

### 1. `models.py`：加 `decision_source`

在 `relation / match_basis / unmapped_reason` 之后插入：

```python
    # ADR §4.1：谁提出/接受了这个决策（rule / ai / human / human_policy）。
    # 与 source（谁生成的候选：seed/auto/llm/manual）是两件事，不可混用。
    decision_source: Mapped[str | None] = mapped_column(String(16))
```

### 2. 迁移 `c1d2e3f4a5b6_...py`

- `revision = "c1d2e3f4a5b6"`、`down_revision = "b0c1d2e3f4a5"`
- `upgrade()`：`op.add_column("exercise_mapping", sa.Column("decision_source", sa.String(16), nullable=True))`
- `downgrade()`：`op.drop_column("exercise_mapping", "decision_source")`
- 风格照抄 `a9b0c1d2e3f4_exercise_mapping_relation.py`

### 3. `exercise_mapping.py`

#### 3.1 新常量

```python
# ADR §5.1：批量自动确认只接受语义精确的关系。
AUTO_CONFIRM_RELATIONS: frozenset[str] = frozenset({"EXACT"})
# ADR §5.1：目标有效性检查——verified_level 至少到达 catalog
_TARGET_VALID_LEVELS: frozenset[str] = frozenset({"catalog", "created", "displayed"})
NOTE_EQUIPMENT_MISMATCH_PREFIX = "器械不符"
```

#### 3.2 `batch_activate` 重写筛选

签名改为（保留旧参数以便调用方兼容，但语义按 ADR）：

```python
def batch_activate(
    session: Session,
    *,
    confidence: str = "high",
    only_confirmed_catalog: bool = True,
    actor: str = "user",
) -> dict:
```

筛选条件（全部满足才启用）：

1. `status == "draft"`
2. `confidence == confidence`
3. `garmin_category IS NOT NULL` 且 `garmin_exercise_name` 非空
4. `relation in AUTO_CONFIRM_RELATIONS`（即只 `EXACT`）
5. `verified_level in _TARGET_VALID_LEVELS`（`NULL` 不算通过——ADR §5.1「至少 catalog」）
6. `note` 不以 `NOTE_EQUIPMENT_MISMATCH_PREFIX` 开头
7. `only_confirmed_catalog=True` 时额外要求 `_catalog_pair_exists(category, exercise_name)`

对每一条未通过的行，**分类计入 skipped 原因**（不要只加一个总数）：

```python
skipped_reasons = {
    "relation_not_exact": n,
    "relation_missing": n,        # relation IS NULL（尚未回填）
    "target_unverified": n,       # verified_level 为 NULL 或不在有效集合
    "equipment_mismatch": n,
    "catalog_missing": n,
}
```

返回值：

```python
{
  "activated": int,
  "skipped": int,                      # 保留旧字段：skipped_reasons 之和
  "skipped_reasons": {...},
  "relation_breakdown": {"EXACT": n, "SIMILAR": n, ...},   # 本次扫描到的 draft+confidence 行的 relation 分布
}
```

启用时：`row.status = "active"`、`row.mapping_version += 1`、`row.decision_source = "rule"`、
写审计 `action="activate"`、`reason="batch_activate"`。
**不得**修改 `relation / match_basis / confidence / verified_level`。

#### 3.3 `activate_mapping`（单行、人工）记录来源

在现有逻辑里加一行 `row.decision_source = "human"`（其余不变）。
这样 §5.2「人工确认的 SIMILAR 可保持 active」在数据上可追溯。

#### 3.4 保护现有行为

`_is_protected` 相关逻辑（在 `exercise_mapping_batch.py`，**不在预算内，不要动**）不受影响。

### 4. `api/exercise_mappings.py`

`POST /batch-activate` 的请求体保持 `{"confidence", "only_confirmed_catalog"}` 不变，
响应直接透传 service 的新结构（含 `skipped_reasons` / `relation_breakdown`）。

若该端点此前有自己拼装响应的代码，改为直接 `return mapping_svc.batch_activate(...)`。

### 5. `tests/test_batch_activate_relation.py`（新，≥14 例）

用 `session` 夹具造行（`ExerciseMapping` 直接 add），逐条验证筛选：

**应自动确认（2 例）**
1. `test_activates_exact_high_verified` —— `relation='EXACT'`、`confidence='high'`、
   `verified_level='catalog'`、`note=None`、目录组合存在 → 被激活，`decision_source == "rule"`
2. `test_activates_exact_displayed_level` —— `verified_level='displayed'` 同样通过

**不应自动确认（6 例，逐一对应条件）**
3. `test_skips_similar` —— `relation='SIMILAR'` + high → 不激活，
   `skipped_reasons["relation_not_exact"] >= 1`
4. `test_skips_category` —— `relation='CATEGORY'` → 不激活
5. `test_skips_missing_relation` —— `relation=None` → 不激活，计入 `relation_missing`
6. `test_skips_unverified_target` —— `verified_level=None` → 不激活，计入 `target_unverified`
7. `test_skips_equipment_mismatch_note` —— `note` 以「器械不符」开头 → 不激活
8. `test_skips_when_catalog_pair_missing` —— 目录里不存在的组合 →
   `only_confirmed_catalog=True` 时不激活，计入 `catalog_missing`；
   `only_confirmed_catalog=False` 时**仍因 relation/verified 条件决定**（单独断言这一开关只影响目录检查）

**不得误伤（3 例）**
9. `test_does_not_touch_active_rows` —— 已 active 的行不被扫描
10. `test_does_not_touch_not_applicable_rows` —— `status='not_applicable'` 不被扫描
11. `test_does_not_change_relation_or_confidence` —— 激活前后
    `relation / match_basis / confidence / verified_level / verified_at` 全部不变

**报告与审计（3 例）**
12. `test_skipped_equals_sum_of_reasons` —— `skipped == sum(skipped_reasons.values())`
13. `test_relation_breakdown_counts_scanned_rows` —— `relation_breakdown` 之和等于
    本次扫描（`draft` + 指定 confidence）的行数
14. `test_audit_written_for_each_activation` —— 每个被激活行都有一条
    `action='activate'`、`reason='batch_activate'` 的审计

**单行人工激活（2 例）**
15. `test_manual_activate_sets_human_source` —— `activate_mapping()` 后
    `decision_source == "human"`
16. `test_manual_activate_allows_similar` —— `relation='SIMILAR'` 的行可被单行激活
    （ADR §5.2：人工接受后 SIMILAR 可 active）

### 6. `tests/test_alembic_decision_source_migration.py`（新，≥3 例）

1. `test_single_head` —— 单 head 且 `c1d2e3f4a5b6` 在链上（**不要写死 head 等于它**，
   照抄 `tests/test_alembic_relation_migration.py::test_single_head` 的不变式写法）
2. `test_down_revision` —— `down_revision == "b0c1d2e3f4a5"`
3. `test_column_exists_in_model` —— `ExerciseMapping.__table__.columns` 含 `decision_source`，
   `nullable is True`

## 自报告要求（交付时必须给出）

1. 改动文件清单（对照预算 6 个），每个文件改动行数与函数名。
2. **筛选条件表**：7 个条件 → 对应代码行 → 对应测试用例编号。
3. **实测 6 组结果**（真实库，造 6 类行）：

   | 场景 | relation | verified_level | note | 期望 | 实测 activated |
   |---|---|---|---|---|---|
   | 正常 | EXACT | catalog | None | 激活 | ? |
   | 类似 | SIMILAR | catalog | None | 跳过 | ? |
   | 大类 | CATEGORY | catalog | None | 跳过 | ? |
   | 未验证 | EXACT | None | None | 跳过 | ? |
   | 器械不符 | EXACT | catalog | 器械不符… | 跳过 | ? |
   | 未回填 | None | catalog | None | 跳过 | ? |

4. 设计取舍：
   - 为什么 `verified_level IS NULL` 不算通过（ADR §5.1「至少 catalog」）
   - 为什么 `decision_source` 要独立列，而不是复用 `source`
   - 为什么 `skipped` 保留旧字段同时新增 `skipped_reasons`
   - 为什么单行 `activate_mapping` 允许 SIMILAR 而批量不允许
5. 确认清单：
   - 未跑 pytest
   - 未执行 git
   - 未改 `.env` 系列
   - 未改 `exercise_mapping_relation.py` / `exercise_mapping_candidates.py` /
     `exercise_mapping_batch.py` / `garmin_plan_sync.py` / `garmin_workout_mapper.py` /
     任何前端 / 任何既有测试文件
   - 文件无 BOM、UTF-8
6. 行为自检清单：
   - [ ] 只有 `relation='EXACT'` 能批量自动确认
   - [ ] `verified_level` 为 NULL 或不在有效集合时不确认
   - [ ] `note` 以「器械不符」开头时不确认
   - [ ] 激活后 `decision_source='rule'`，单行人工激活为 `'human'`
   - [ ] 激活不改 `relation/match_basis/confidence/verified_level/verified_at`
   - [ ] `skipped == sum(skipped_reasons.values())`
   - [ ] 迁移单 head 且 `down_revision` 正确

## 明确不做

- 不做存量 292 条的 relation 回填（P0-1 的端点已具备，部署侧执行）
- 不改 `exercise_mapping_batch.generate_all`（刷新与保护逻辑不动）
- 不改前端（管理页的 relation 列与筛选留到前端切片）
- 不做 CATEGORY 降级开关（ADR §6）
