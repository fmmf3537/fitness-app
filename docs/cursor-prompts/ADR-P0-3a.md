# ADR-P0-3a mapper 层：allow_partial（skipped 收集 + 缺口标记）

> 你是本仓库的资深后端工程师（FastAPI + SQLAlchemy 2.x + pytest）。
> 本提示词是唯一任务来源：只按本提示词写代码，**不跑任何验收命令（pytest 一律不跑）**，**不执行任何 git 命令**。
> 红线：禁整文件重写（外科式最小修改）；所有写出的文件必须无 BOM、UTF-8；不得修改 `.env` / `.env.*`；不得删除任何既有文件；不得改动本提示词文件预算之外的任何文件。

## 需求背景

ADR §7 要求「单个动作缺口不再阻塞整天」：默认跳过无法写入的动作、其余正常写入、并明确报告缺口。
本切片只是 **mapper 层**的能力，**不改同步链路**（同步层接线是下一片 ADR-P0-3b），
所以这一片完全不改变任何线上行为，只增加一个 opt-in 模式与配套测试。

现状：`map_plan_day()` 只要有一个动作没有可用映射就抛 `WorkoutMappingError`，
调用方（预览与同步）一律 422/失败。

## 已核实的关键事实（实读代码，可直接采信）

- `backend/app/services/garmin_workout_mapper.py`
  - `class WorkoutMappingError(ValueError)`：已有 `self.issues`、`self.excluded`（ADR-P0-2 新增）
  - `map_plan_day(plan_day, *, mappings=None)` 逐动作处理，相关片段现状：
    ```python
    if mapping is not None and mapping.get("status") == "not_applicable":
        excluded_movements.append({"name": name, "reason": "not_applicable"}); continue   # ADR-P0-2
    mapping = active_mappings.get(name)
    if mapping is None:
        issues.append({"code": "UNKNOWN_EXERCISE", ...}); continue
    status = mapping.get("status")
    if status not in (None, "active"):
        issues.append({"code": "MAPPING_NOT_APPROVED", ...}); continue
    ```
  - 结尾：`if issues: raise WorkoutMappingError(issues, excluded=excluded_movements)`
  - 返回 dict（约第 200 行起）：
    ```python
    return {
        <若干字段>,
        "source_hash": hash_value,
        "workout": payload,
        "movements": preview_movements,
        "excluded": excluded_movements,
        "totals": {...},
    }
    ```
  - `workoutName` 由 `_workout_name(title, day)` 生成，写在 payload 里（约第 479 行）
- `not_applicable` 判定（ADR-P0-2）已在 `mapping is None` 与 status 检查**之前**，本片不要动它的位置

## 文件预算（共 2 个，不得越界）

改 1：
1. `backend/app/services/garmin_workout_mapper.py`

新增 1：
2. `backend/tests/test_mapper_partial.py`

**禁止修改**：`exercise_mapping.py`、`garmin_plan_sync.py`、`garmin_reschedule.py`、`api/plans.py`、
`models.py`、任何迁移、任何前端、`.env`、任何既有测试文件。

## 开发内容

### 1. 新增常量

```python
# ADR §7.1：只有「可定位到具体动作的映射缺口」允许进入部分同步。
# 其余问题（鉴权/网络/非法字段/组次不可表达等）必须继续整日失败，不得降级。
PARTIAL_ELIGIBLE_CODES: frozenset[str] = frozenset(
    {"UNKNOWN_EXERCISE", "MAPPING_NOT_APPROVED"}
)
```

### 2. `map_plan_day` 增加 opt-in 参数

签名改为：

```python
def map_plan_day(
    plan_day: dict[str, Any],
    *,
    mappings: dict[str, dict[str, Any]] | None = None,
    allow_partial: bool = False,
) -> dict[str, Any]:
```

**`allow_partial=False` 时行为必须与改动前逐字节一致**（默认路径零变化）。

### 3. `allow_partial=True` 时的行为

#### 3.1 缺口动作进入 skipped 而不是 issues

循环前初始化：

```python
skipped_movements: list[dict[str, Any]] = []
```

把这两处 `issues.append(...); continue` 改为「按 allow_partial 分流」：

```python
# UNKNOWN_EXERCISE 分支
if mapping is None:
    if allow_partial:
        skipped_movements.append(
            {"name": name, "reason": "UNKNOWN_EXERCISE", "detail": "未找到映射行"}
        )
        continue
    issues.append({...原样...})
    continue

# MAPPING_NOT_APPROVED 分支
if status not in (None, "active"):
    if allow_partial:
        skipped_movements.append(
            {
                "name": name,
                "reason": "MAPPING_NOT_APPROVED",
                "detail": f"当前状态 {status}",
            }
        )
        continue
    issues.append({...原样...})
    continue
```

**其余所有 issue 保持原样**（`EMPTY_MOVEMENT`、`SINGLE_SIDE_UNSUPPORTED`、`AMRAP_UNSUPPORTED`、
`SET_TYPE_UNSUPPORTED`、`REPS_REQUIRED`、`UNIT_UNSUPPORTED`、`EMPTY_WORKOUT` 等），
即使 `allow_partial=True` 也必须继续产出 issue 并最终抛错。

#### 3.2 全不可写时抛错（不创建空 Workout）

在构造 payload **之前**（即 `if issues:` 判断之后、`hash_value = ...` 之前）增加：

```python
if allow_partial and not mapped_movements and skipped_movements:
    raise WorkoutMappingError(
        [
            {
                "code": "NO_WRITABLE_MOVEMENTS",
                "message": "没有可写入 Garmin 的动作，已跳过全部 "
                f"{len(skipped_movements)} 个动作",
            }
        ],
        excluded=excluded_movements,
        skipped=skipped_movements,
    )
```

> `NO_WRITABLE_MOVEMENTS` **不属于** `PARTIAL_ELIGIBLE_CODES`：它表示"这天写不了"，
> 是失败而不是部分成功（ADR §7.2 边界行为第 2 条）。

#### 3.3 Workout 名称缺口标记

`allow_partial=True` 且 `skipped_movements` 非空时，在 payload 的 `workoutName` 末尾追加
缺口标记（只在生成的本地 payload 上追加，不改 `_workout_name()` 的实现）：

```python
# ADR §7.2：远端辅助提示，便于日后在 Garmin 历史里发现"那天的记录不完整"。
# 本地结构化记录才是事实来源；补齐后 mapper 重新生成，标记自然消失。
marker = f"（缺 {len(skipped_movements)} 个动作）"
```

追加位置：构造完 payload 之后、`return` 之前，例如
`payload["workoutName"] = payload["workoutName"] + marker`（仅当 payload 里有 `workoutName`）。

#### 3.4 `WorkoutMappingError` 增加可选 `skipped`

```python
def __init__(
    self,
    issues: list[dict[str, Any]],
    excluded: list[dict[str, Any]] | None = None,
    skipped: list[dict[str, Any]] | None = None,
):
    self.issues = issues
    self.excluded = excluded or []
    self.skipped = skipped or []
```

**向后兼容**：`WorkoutMappingError([...])`、`WorkoutMappingError(issues, excluded=[...])`
都必须继续可用（新增参数只能放在末尾且有默认值）。

#### 3.5 返回 dict 增加 `skipped`

在成功返回的 preview dict 里加 `"skipped": skipped_movements`
（`allow_partial=False` 时它是 `[]`，保持字段恒在，避免调用方做 `if "skipped" in preview`）。

### 4. `tests/test_mapper_partial.py`（新，≥14 例）

用 `map_plan_day` 直接测（mappings 手写，不查库）。构造计划日时每组要有
`{"weight": 20, "reps": 10, "unit": "kg", "done": True}`，否则会先撞 `UNIT_UNSUPPORTED`。

**默认路径零变化（4 例）**
1. `test_default_still_raises_on_unknown` —— `allow_partial=False` 时未知动作仍抛
   `UNKNOWN_EXERCISE`
2. `test_default_still_raises_on_draft` —— draft 仍抛 `MAPPING_NOT_APPROVED`
3. `test_default_preview_has_empty_skipped` —— 全部可写时 `preview["skipped"] == []`
4. `test_default_excluded_unchanged` —— `not_applicable` 仍进 `excluded`（ADR-P0-2 未被破坏）

**partial 主路径（5 例）**
5. `test_partial_skips_unknown` —— 力量 + 未知 + `allow_partial=True`
   → 成功，`skipped` 含 `{"reason": "UNKNOWN_EXERCISE"}`，`movements` 只含力量动作
6. `test_partial_skips_draft` —— draft 进 `skipped`，`reason == "MAPPING_NOT_APPROVED"`，
   `detail` 含 `draft`
7. `test_partial_skips_disabled` —— disabled 同理，`detail` 含 `disabled`
8. `test_partial_keeps_excluded_separate` —— 拉伸在 `excluded`、未知在 `skipped`，两者不混
9. `test_partial_written_movements_correct` —— 写入的动作数与组数与输入一致

**不可降级的错误（4 例）**
10. `test_partial_still_raises_on_unit_unsupported` —— 缺 `unit` 的组 → 仍抛
    `UNIT_UNSUPPORTED`（**不得**进 skipped）
11. `test_partial_still_raises_on_single_side` —— `single_side=True` → 仍抛
    `SINGLE_SIDE_UNSUPPORTED`
12. `test_partial_still_raises_on_amrap` —— `amrap=True` → 仍抛 `AMRAP_UNSUPPORTED`
13. `test_partial_still_raises_on_empty_movement` —— 组次为空 → 仍抛 `EMPTY_MOVEMENT`

**全不可写与名称标记（3 例）**
14. `test_all_unwritable_raises_no_writable` —— 全部动作都是未知 →
    `allow_partial=True` 时抛 `NO_WRITABLE_MOVEMENTS`，且 `exc.skipped` 含全部动作
15. `test_all_unwritable_is_not_partial_eligible` —— 断言
    `"NO_WRITABLE_MOVEMENTS" not in PARTIAL_ELIGIBLE_CODES`
16. `test_workout_name_has_gap_marker` —— 有 1 个跳过时 `preview["workout"]["workoutName"]`
    以 `（缺 1 个动作）` 结尾；全可写时**不含**该标记
17. `test_marker_absent_when_only_excluded` —— 只有 `not_applicable`（excluded）时
    名称**不得**加标记（标记只统计 skipped）

**错误对象兼容（1 例）**
18. `test_error_skipped_defaults_empty` —— `WorkoutMappingError([...])` 的
    `skipped == []` 且 `excluded == []`

## 自报告要求（交付时必须给出）

1. 改动文件清单（对照预算 2 个），每个文件改动行数与函数名。
2. **`map_plan_day` 内四条分支的先后顺序代码片段**（not_applicable → UNKNOWN → status → 其它 issue）。
3. **实测对照表**（6 组输入 × 结果）：

   | 输入 | allow_partial | 结果 |
   |---|---|---|
   | 力量 | False | 成功，skipped=[] |
   | 力量+未知 | False | 抛 UNKNOWN_EXERCISE |
   | 力量+未知 | True | 成功，skipped=[未知] |
   | 力量+拉伸 | True | 成功，excluded=[拉伸]，skipped=[] |
   | 未知+未知 | True | 抛 NO_WRITABLE_MOVEMENTS |
   | 力量(缺unit) | True | 抛 UNIT_UNSUPPORTED |

   每行给出实际的 `workoutName` 与 `skipped`/`excluded` 内容。
4. 设计取舍：
   - 为什么用 opt-in 参数而不是改默认
   - 为什么 `SKIPPED` 用 `reason` 存 code 而不是自由文本
   - 为什么 `NO_WRITABLE_MOVEMENTS` 不算 partial
   - 为什么名称标记只统计 skipped 不统计 excluded
5. 确认清单：
   - 未跑 pytest
   - 未执行 git
   - 未改 `.env` 系列
   - 未改 `exercise_mapping.py` / `garmin_plan_sync.py` / `api/plans.py` / `models.py` /
     任何迁移 / 任何前端 / 任何既有测试文件
   - `allow_partial=False` 的行为与改动前完全一致
   - 文件无 BOM、UTF-8
6. 行为自检清单：
   - [ ] 默认路径（allow_partial 不传）行为零变化
   - [ ] 只有 `UNKNOWN_EXERCISE` / `MAPPING_NOT_APPROVED` 可降级为 skipped
   - [ ] 其余 issue 在 allow_partial=True 时仍整日失败
   - [ ] skipped 与 excluded 严格分列
   - [ ] 全不可写抛 `NO_WRITABLE_MOVEMENTS` 且不生成 payload
   - [ ] 名称标记只按 skipped 计数
   - [ ] `WorkoutMappingError` 三个参数向后兼容

## 明确不做

- 不改同步链路（`garmin_plan_sync.py` 下一片接）
- 不加数据库字段（`sync_result_json` 下一片）
- 不改 status 三态（`synced/partial/failed` 下一片）
- 不改预览端点（`api/plans.py` 下一片）
- 不改前端
