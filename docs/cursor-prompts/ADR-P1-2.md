# ADR-P1-2 Garmin 目标变化后重置 verified_level

> 你是本仓库的资深后端工程师（FastAPI + SQLAlchemy 2.x + pytest）。
> 本提示词是唯一任务来源：只按本提示词写代码，**不跑任何验收命令（pytest 一律不跑）**，**不执行任何 git 命令**。
> 红线：禁整文件重写（外科式最小修改）；所有写出的文件必须无 BOM、UTF-8；不得修改 `.env` / `.env.*`；不得删除任何既有文件；不得改动本提示词文件预算之外的任何文件。

## 需求背景

ADR §9：修改 `garmin_category` 或 `garmin_exercise_name` 时，**旧目标的验证等级不得直接继承**。

现状（ADR §2 已记录为现存缺陷，实测确认）：`update_mapping()` 只递增 `mapping_version`，
**完全不动 `verified_level` / `verified_at`**。于是「哑铃卧推」原本在真机目视确认过
（`verified_level='displayed'`），把它改成另一个 exercise 后，它仍然是 `displayed`
——旧目标的验证历史被错误继承给新目标。

ADR §9 六条要求：
1. `mapping_version` 递增并记录审计；
2. 旧 `verified_level` 与 `verified_at` 不得直接继承；
3. 新目标通过目录校验后设为 `catalog`，未通过时设为 `none`，且**不得保持 active**；
4. 后续真实创建/目视验证完成后再分别升级为 `created` / `displayed`；
5. 只修改训记名称且 Garmin 目标不变时，**不重置**；
6. 已有同步是否重发仍沿用 `mapping_hash/stale` 与用户显式确认，不自动覆盖历史 Garmin 对象。

## 已核实的关键事实（实读代码，可直接采信）

- `backend/app/services/exercise_mapping.py`
  - `update_mapping(session, mapping_id, *, garmin_category=_UNSET, garmin_exercise_name=_UNSET,
    garmin_display_name=_UNSET, weight_strategy=_UNSET, status=_UNSET, reason=None, actor="user")`
  - 它先构造 `updates` dict（哨兵 `_UNSET` 区分「传 None」与「不传」），若 `updates` 为空则直接返回；
    否则 `before = {k: getattr(row, k) for k in updates}` → `setattr` 循环 →
    `row.mapping_version += 1` → `_write_audit(action="update", ...)` → commit
  - `_catalog_pair_exists(category, exercise_name) -> bool`（第 311 行）：目录里是否存在该组合
  - `_TARGET_VALID_LEVELS = frozenset({"catalog", "created", "displayed"})`（ADR-P0-4 新增）
  - `_validate_category()` / `_validate_exercise_pair()`：写入前的合法性校验（保持不动）
  - `_mapping_item_dict(row, candidate_count=...)`：返回给 API 的行视图
- 合法 `verified_level` 取值：`none / catalog / created / displayed`
- Alembic 当前单 head：**`c1d2e3f4a5b6`**（本片**不加迁移**）

## 文件预算（共 2 个，不得越界）

改 1：
1. `backend/app/services/exercise_mapping.py`

新增 1：
2. `backend/tests/test_verified_level_reset.py`

**禁止修改**：`models.py`、任何迁移、`api/exercise_mappings.py`、其它 `exercise_mapping*.py`、
同步链路、任何前端、`.env`、任何既有测试文件。

## 开发内容

### 1. 在 `update_mapping` 里加入目标变化检测与验证等级重置

在 `before = {key: getattr(row, key) for key in updates}` **之前**插入：

```python
    # ADR §9：Garmin 目标变化后不得继承旧目标的验证等级。
    target_changed = (
        ("garmin_category" in updates
         and updates["garmin_category"] != row.garmin_category)
        or ("garmin_exercise_name" in updates
            and updates["garmin_exercise_name"] != row.garmin_exercise_name)
    )
```

在 `setattr` 循环与 `mapping_version += 1` **之后**、`_write_audit` **之前**插入：

```python
    if target_changed:
        previous_level = row.verified_level
        previous_at = row.verified_at
        # 目标有效性依据**新的** category/exercise 判断
        target_valid = bool(row.garmin_category) and _catalog_pair_exists(
            row.garmin_category, row.garmin_exercise_name or ""
        )
        row.verified_level = "catalog" if target_valid else "none"
        row.verified_at = None
        # ADR §9 第 3 条：目标无效时不得保持 active
        if not target_valid and row.status == "active":
            row.status = "draft"
        audit_extra = {
            "previous_verified_level": previous_level,
            "previous_verified_at": (
                previous_at.isoformat() if previous_at else None
            ),
            "target_valid": target_valid,
        }
    else:
        audit_extra = {}
```

要点：

- **必须重新计算 `before`**：`before` 原本只含 `updates` 里的键。目标变化引起 `verified_level` /
  `verified_at` / `status` 的连带修改，也要进审计。把 `audit_extra` 涉及的三个字段
  （`verified_level`、`verified_at`、`status`）在目标变化时一并纳入 `before`/`after` 快照。
  **实现建议**：先算出 `target_changed`，再在构造 `before` 时把
  `{"verified_level", "verified_at"}` 并入键集合；`status` 若在 `updates` 里已包含则不重复。
- `_write_audit(after=...)` 里追加 `audit_extra` 的键（若该函数的 `after` 参数是普通 dict，
  直接 `after.update(audit_extra)` 即可；若它是固定签名，则把额外信息放进 `reason`
  或已有的 detail 字段——**先读 `_write_audit` 的实现再决定，不要臆测**）。
- **只改 `garmin_display_name` / `weight_strategy` / `status` / `note` 时不重置**
  （这些不是目标身份变化）。
- `garmin_category` 或 `garmin_exercise_name` 传了但与现値相同 → 视为未变化，不重置。

### 2. `tests/test_verified_level_reset.py`（新，≥12 例）

用 `session` 夹具直接造行并调 `update_mapping`：

**目标变化 → 重置（5 例）**
1. `test_exercise_change_resets_to_catalog` —— `verified_level='displayed'` 的行把
   `garmin_exercise_name` 改为另一个目录内存在的组合 →
   `verified_level == 'catalog'` 且 `verified_at is None`
2. `test_category_change_resets` —— 改 `garmin_category`（配对的 exercise 同时在目录内）→ 同上
3. `test_invalid_target_becomes_none` —— 改为目录里不存在的组合（用合法 category +
   不存在但格式合法的 exercise 名，或直接构造）→ `verified_level == 'none'`
4. `test_invalid_target_exits_active` —— 原 `status='active'` 且目标变为无效 →
   `status == 'draft'`
5. `test_valid_target_keeps_active` —— 原 active 且新目标有效 → `status` 仍 `active`

**不重置（4 例）**
6. `test_display_name_change_does_not_reset` —— 只改 `garmin_display_name` →
   `verified_level` / `verified_at` 不变
7. `test_weight_strategy_change_does_not_reset` —— 只改 `weight_strategy` → 不变
8. `test_status_change_does_not_reset` —— 只改 `status` → 不变
9. `test_same_target_resubmitted_does_not_reset` —— 传与现值相同的
   `garmin_exercise_name` → 不重置

**审计与版本（2 例）**
10. `test_target_change_audit_contains_previous_level` —— 审计里能查到
    旧 `verified_level`（`before` 或 `after` 或 reason/detail 中，按实际实现断言）
11. `test_mapping_version_bumped_once` —— `mapping_version` 恰好 +1（不是 +2）

**不误伤（2 例）**
12. `test_no_updates_returns_without_reset` —— 不传任何字段（`updates` 为空）→
    不重置、不 bump、不写审计
13. `test_reset_does_not_touch_relation_or_decision_source` —— 重置前后
    `relation / match_basis / decision_source / confidence` 不变

## 自报告要求（交付时必须给出）

1. 改动文件清单（对照预算 2 个），每个文件改动行数与函数名。
2. **`_write_audit` 的实际签名**（贴出来），以及额外信息最终落在哪里。
3. **实测对照表**（6 组）：

   | 变更 | 原 verified_level | 结果 verified_level | status | mapping_version |
   |---|---|---|---|---|
   | exercise 改为有效目标 | displayed | ? | ? | ? |
   | exercise 改为无效目标 | displayed | ? | ? | ? |
   | 只改 display_name | displayed | ? | ? | ? |
   | 只改 weight_strategy | displayed | ? | ? | ? |
   | 传相同 exercise | displayed | ? | ? | ? |
   | 不传任何字段 | displayed | ? | ? | ? |

4. 设计取舍：
   - 为什么「目标有效」用 `_catalog_pair_exists` 而不是 `_validate_*`（后者的职责是拒绝非法输入）
   - 为什么无效目标要连带退出 active（ADR §9 第 3 条）
   - 为什么 `verified_at` 置 None 而不是保留时间戳
   - 为什么 audit 要带 `previous_verified_level`
5. 确认清单：
   - 未跑 pytest
   - 未执行 git
   - 未改 `.env` 系列
   - 未改 `models.py` / 任何迁移 / `api/*` / 其它 `exercise_mapping*.py` / 同步链路 /
     任何前端 / 任何既有测试文件
   - 文件无 BOM、UTF-8
6. 行为自检清单：
   - [ ] 改 category 或 exercise 且值确实变化 → 重置
   - [ ] 新目标有效 → `catalog`；无效 → `none` 并退出 active
   - [ ] 只改 display_name / weight_strategy / status → 不重置
   - [ ] 传与现值相同的目标 → 不重置
   - [ ] `mapping_version` 只 +1
   - [ ] 审计包含旧验证等级
   - [ ] `relation / match_basis / decision_source / confidence` 不受影响
   - [ ] `updates` 为空时零副作用

## 明确不做

- 不改前端（管理页展示留到前端切片）
- 不改 `activate_mapping` / `batch_activate`（ADR-P0-4 已定稿）
- 不改 L2 探针（`exercise_catalog_probe`）——真实创建验证的升级路径不变
- 不加数据库迁移
