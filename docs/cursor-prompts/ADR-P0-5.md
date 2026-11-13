# ADR-P0-5 存量迁移：B 策略落地 + 迁移报告

> 你是本仓库的资深后端工程师（FastAPI + SQLAlchemy 2.x + pytest）。
> 本提示词是唯一任务来源：只按本提示词写代码，**不跑任何验收命令（pytest 一律不跑）**，**不执行任何 git 命令**。
> 红线：禁整文件重写（外科式最小修改）；所有写出的文件必须无 BOM、UTF-8；不得修改 `.env` / `.env.*`；不得删除任何既有文件；不得改动本提示词文件预算之外的任何文件。

## 需求背景

ADR §10 规定：旧规则下通过 `confidence='high'` 批量激活的存量映射，采用 **B：继承既有使用政策**：

- 回填 `relation` 后，`EXACT` 且目标有效的记录**保持 active**，保留原有来源与验证信息；
- `SIMILAR` 的存量 active **保持 active**，但记 `decision_source='human_policy'`
  （含义：继承"宁可名称不精确也保持可同步"的批量使用政策），**不得**展示成逐条人工确认；
- **已确认存在实际误配**、或 **Garmin 目标无效**的记录**不得**继续保持 active；
- 后续新增的 SIMILAR 提议不得援引 B 批量自动激活——**B 只适用于本次存量迁移**。

ADR §10.2 要求迁移后输出实际数量的报告，不预先写死估算值。

ADR-P0-1 已交付 `backfill_relations()`（只回填 `relation/match_basis/unmapped_reason`，幂等），
ADR-P0-4 已交付 `decision_source` 列。本片把 B 政策与报告接上。

## 已核实的关键事实（实读代码，可直接采信）

- `backend/app/services/exercise_mapping_relation.py`（ADR-P0-1）已有：
  - `RELATION_EXACT / RELATION_SIMILAR / RELATION_CATEGORY / RELATION_UNMAPPED`、`RELATIONS`
  - `classify_relation(row) -> (relation, match_basis, unmapped_reason)`
  - `backfill_relations(session) -> dict`，返回
    `{scanned, updated, skipped_not_applicable, by_relation, by_status, active_similar, changed_values}`，
    **只处理 `relation IS NULL` 的行**，不碰 `status/confidence/mapping_version/verified_level`
- `backend/app/services/exercise_mapping.py` 有
  `_catalog_pair_exists(category, exercise_name) -> bool`（目录里是否存在该组合）
  和 `_TARGET_VALID_LEVELS = frozenset({"catalog", "created", "displayed"})`（ADR-P0-4 新增）
- `backend/app/models.py` 的 `ExerciseMapping` 现有相关列：
  `status / confidence / relation / match_basis / unmapped_reason / decision_source /
   verified_level / verified_at / mapping_version / note / source`
- `decision_source` 取值约定：`rule / ai / human / human_policy`
- Alembic 当前单 head：**`c1d2e3f4a5b6`**（本片**不加迁移**）

## 文件预算（共 3 个，不得越界）

改 2：
1. `backend/app/services/exercise_mapping_relation.py`（新增迁移函数）
2. `backend/app/api/exercise_mappings.py`（新增端点）

新增 1：
3. `backend/tests/test_existing_active_migration.py`

**禁止修改**：`models.py`、任何迁移、`exercise_mapping.py`（只允许 import 其常量/函数）、
`exercise_mapping_candidates.py`、`exercise_mapping_batch.py`、`garmin_plan_sync.py`、
`garmin_workout_mapper.py`、任何前端、`.env`、任何既有测试文件。

## 开发内容

### 1. `exercise_mapping_relation.py` 新增常量与函数

```python
DECISION_RULE = "rule"
DECISION_HUMAN = "human"
DECISION_HUMAN_POLICY = "human_policy"

# ADR §10.1：B 策略只适用于本次存量迁移，后续新增的 SIMILAR 不得援引。
B_POLICY_NOTE = "继承旧规则的批量使用政策（human_policy），非逐条人工语义确认"
```

#### 1.1 `migrate_existing_active(session) -> dict`

```python
def migrate_existing_active(session: Session) -> dict:
    """ADR §10.1：把 B 策略应用到存量 active 记录，并返回迁移报告。

    步骤（严格按序）：
    1. 先确保 relation 已回填（复用 backfill_relations，幂等）。
    2. 遍历 status='active' 的行：
       a. relation == SIMILAR 且 decision_source 为空 → decision_source='human_policy'，
          保持 active，并在 note 末尾追加 B_POLICY_NOTE（若尚未包含）。
          **不得**修改 status / mapping_version / relation / verified_level。
       b. Garmin 目标无效（verified_level 不在 _TARGET_VALID_LEVELS，
          或 _catalog_pair_exists 为 False）→ status='draft'，mapping_version += 1，
          写审计 action='migrate_exit_active'，并在报告里登记明细。
       c. relation == EXACT / CATEGORY → 保持原样（保留原有来源与验证信息）。
    3. 提交并按 §10.2 返回报告。
    """
```

**幂等要求**：连续执行两次，第二次的 `updated` 与 `exited_active` 都必须为 0。

#### 1.2 报告结构（ADR §10.2）

```python
{
  "backfill": {...},                 # backfill_relations 的返回，原样透传
  "scanned_active": int,             # 本次扫描的 active 行数
  "updated": int,                    # 被标记 human_policy 的行数
  "exited_active": int,              # 因目标无效而退出 active 的行数
  "by_relation": {"EXACT": n, "SIMILAR": n, "CATEGORY": n, "UNMAPPED": n, "null": n},
  "by_status": {"draft": n, "active": n, "disabled": n, "not_applicable": n},
  "human_policy": int,               # 迁移后 decision_source='human_policy' 的总行数（全表口径）
  "exited_details": [                # 因目标无效退出的明细
      {"xunji_name": str, "garmin_exercise_name": str | None,
       "verified_level": str | None, "reason": "target_unverified" | "catalog_missing"},
      ... 最多 100 条
  ],
  "high_risk": [                     # ADR §10.2「仍需人工审核的高风险清单」
      {"xunji_name": str, "garmin_display_name": str | None,
       "relation": str, "note": str | None},
      ... 最多 100 条：active 且 relation='SIMILAR' 的行
  ],
}
```

> `by_relation` / `by_status` 是**全表口径**（不是本次扫描口径），便于对照 ADR §10.2
> 「EXACT / SIMILAR / CATEGORY / UNMAPPED 各多少」「active / draft / disabled / not_applicable 各多少」。

### 2. `api/exercise_mappings.py` 新增端点

**注册位置**：与其它固定路径一起，放在 `/{mapping_id}` **之前**。

```python
@router.post("/migrate-existing")
def post_migrate_existing(session: Session = Depends(get_session)) -> dict:
    """ADR §10：把 B 策略应用到存量 active 映射并输出迁移报告（幂等）。"""
    return relation_svc.migrate_existing_active(session)
```

无请求体。import 风格沿用该文件现有的 `as ..._svc` 写法。

### 3. `tests/test_existing_active_migration.py`（新，≥14 例）

用 `session` 夹具直接造行（不查真实库）：

**B 策略标记（4 例）**
1. `test_similar_active_becomes_human_policy` —— active + `relation='SIMILAR'` +
   `decision_source=None` → 迁移后 `decision_source == 'human_policy'`，**status 仍 active**
2. `test_similar_active_note_annotated` —— 同上，`note` 含 `B_POLICY_NOTE`
3. `test_similar_note_not_duplicated` —— 连跑两次，`note` 里 `B_POLICY_NOTE` 只出现一次
4. `test_exact_active_untouched` —— active + `relation='EXACT'` + verified 有效 →
   `decision_source` 保持 `None`，其余字段不变

**退出 active（3 例）**
5. `test_unverified_target_exits_active` —— active 但 `verified_level='none'` →
   `status == 'draft'`，报告 `exited_details` 含它，`reason == 'target_unverified'`
6. `test_catalog_missing_exits_active` —— active 但目录里没有该组合 →
   `status == 'draft'`，`reason == 'catalog_missing'`
7. `test_exit_writes_audit` —— 退出时写审计 `action='migrate_exit_active'`

**不误伤（3 例）**
8. `test_draft_rows_untouched` —— draft 行完全不变
9. `test_not_applicable_rows_untouched` —— not_applicable 行完全不变
10. `test_migration_does_not_change_relation_or_verified_level` —— 迁移前后
    `relation / verified_level / verified_at / confidence` 全部不变

**幂等（2 例）**
11. `test_second_run_is_noop` —— 连跑两次，第二次 `updated == 0 and exited_active == 0`
12. `test_second_run_does_not_add_audit` —— 第二次不新增审计行

**报告（3 例）**
13. `test_report_counts_are_full_table` —— `by_relation` 之和 == 表内总行数，
    `by_status` 之和 == 表内总行数
14. `test_report_lists_high_risk` —— `high_risk` 含所有 active+SIMILAR 行，最多 100 条
15. `test_report_exited_details_capped` —— 造 105 行无效目标，`exited_details` 长度为 100

## 自报告要求（交付时必须给出）

1. 改动文件清单（对照预算 3 个），每个文件改动行数与函数名。
2. **`migrate_existing_active` 的分支顺序说明**（backfill → SIMILAR 标记 → 无效目标退出 → 其余不动）。
3. **实测报告样例**：用「2 条 SIMILAR active + 1 条 EXACT active + 1 条无效目标 active + 若干 draft」
   造数据，贴出完整 JSON 报告。
4. 幂等实测：连跑两次，贴第二次的关键字段（`updated` / `exited_active` / `human_policy`）。
5. 设计取舍：
   - 为什么 B 策略不改 `status` 只改 `decision_source`
   - 为什么 `EXACT` 存量不动 `decision_source`（而不是统一写 `rule`）
   - 为什么 `by_relation/by_status` 用全表口径
   - 为什么无效目标要退出 active 而不是标 `verified_level='none'` 却保持 active
6. 确认清单：
   - 未跑 pytest
   - 未执行 git
   - 未改 `.env` 系列
   - 未改 `models.py` / 任何迁移 / `exercise_mapping.py` / `exercise_mapping_batch.py` /
     `exercise_mapping_candidates.py` / 同步链路 / 任何前端 / 任何既有测试文件
   - 文件无 BOM、UTF-8
7. 行为自检清单：
   - [ ] SIMILAR 存量 active 标记为 `human_policy` 且仍 active
   - [ ] 目标无效的 active 退出为 draft 并写审计
   - [ ] EXACT / draft / not_applicable 三类不被改动
   - [ ] 迁移不修改 `relation / verified_level / verified_at / confidence`
   - [ ] 连跑两次幂等（`updated` / `exited_active` 第二次为 0，审计不重复）
   - [ ] 报告 `by_relation` / `by_status` 为全表口径且自洽
   - [ ] `exited_details` / `high_risk` 各最多 100 条

## 明确不做

- 不做前端（管理页的 relation 列/筛选另做）
- 不做 CATEGORY 降级开关（ADR §6）
- 不改 `batch_activate`（ADR-P0-4 已定稿）
- 不改同步链路
- 不加数据库迁移（本片无 schema 变更）
