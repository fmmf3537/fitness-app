# ADR-P0-2 预览层：not_applicable 正常排除（excluded 通道，不改同步行为）

> 你是本仓库的资深后端工程师（FastAPI + SQLAlchemy 2.x + pytest）。
> 本提示词是唯一任务来源：只按本提示词写代码，**不跑任何验收命令（pytest 一律不跑）**，**不执行任何 git 命令**。
> 红线：禁整文件重写（外科式最小修改）；所有写出的文件必须无 BOM、UTF-8；不得修改 `.env` / `.env.*`；不得删除任何既有文件；不得改动本提示词文件预算之外的任何文件。

## 需求背景

`docs/ADR-EXERCISE-MAPPING.md` §4.2 规定：`not_applicable`（拉伸/有氧等按产品定义不写入力量 Workout 的动作）是**正常排除**，不计入同步缺口、不触发 `partial`。

现状（已实测）：`load_all_mappings()` 直接把 `status='not_applicable'` 的行过滤掉，mapper 于是把它们当成未知动作：

```python
map_plan_day({"movements":[{"name":"腿部拉伸",...}]}, mappings={})
→ issues: [('UNKNOWN_EXERCISE', '腿部拉伸')]
```

任何含拉伸动作的训练日都会 422、整天无法同步。

**本切片只做「预览层的 excluded 通道」，不改同步行为**：
`load_all_mappings()` 默认仍过滤 `not_applicable`（同步路径零变化），
新增 opt-in 参数让**预览端点**能看到它们并以 `excluded` 单独呈现。
同步路径的「跳过 + partial + 缺口记录」是下一片 ADR-P0-3。

这样切分的原因：一旦去掉过滤，同步会**静默丢掉**拉伸动作而不报警（ADR §7.2 明确禁止），
所以必须先有 excluded 数据通道，再在下一片同时打开「跳过」和「缺口报告」。

## 已核实的关键事实（实读代码，可直接采信）

- `backend/app/services/exercise_mapping.py`
  ```python
  def load_all_mappings(session) -> dict[str, dict[str, Any]]:
      # 空表回退 _whitelist_as_mappings()
      rows = session.scalars(
          select(ExerciseMapping).where(ExerciseMapping.status != "not_applicable")
      ).all()
      return {row.xunji_name: _row_to_mapping_dict(row) for row in rows}
  ```
  `_row_to_mapping_dict()` 返回 `{category, exerciseName, display_name, support_level, weight_strategy, status}`。
- `backend/app/services/garmin_workout_mapper.py`
  - `class WorkoutMappingError(ValueError)`，只有 `self.issues`，`__init__(self, issues)`
  - `map_plan_day(plan_day, *, mappings=None)` 逐动作处理，关键片段：
    ```python
    mapping = active_mappings.get(name)
    if mapping is None:
        issues.append({"code": "UNKNOWN_EXERCISE", ...}); continue
    status = mapping.get("status")
    if status not in (None, "active"):
        issues.append({"code": "MAPPING_NOT_APPROVED", ...}); continue
    ```
  - 结尾：`if issues: raise WorkoutMappingError(issues)`，否则返回 preview dict
- `backend/app/api/plans.py`
  - `GET /plans/{day}/garmin/preview`：
    ```python
    mappings = mapping_service.load_all_mappings(session)
    preview = map_plan_day(plan_day, mappings=_preview_mappings(mappings))
    # 捕获 WorkoutMappingError → HTTPException(422, detail={"code":"PLAN_MAPPING_UNSUPPORTED","issues":...})
    return {**preview, "remote_write_eligible": ..., "sync": ..., "pending_review": ...}
    ```
  - `_preview_mappings()` 把 `status=='draft'` 软化为 `active`（预览不阻断 draft）
  - `garmin_plan_sync.py:367` 也调 `map_plan_day(plan_day, mappings=mappings)`，用的是**默认** `load_all_mappings()` —— 本切片不得改变它的行为

**陷阱（ADR §4.2 已记录，实测复现）**：只把 `not_applicable` 行塞进 mappings 而不在 mapper 里先判定，
现有状态检查 `status not in (None, "active")` 会把它判成 `MAPPING_NOT_APPROVED`
（属映射缺口），从而触发 partial。必须在状态检查**之前**显式跳过。

## 文件预算（共 5 个，不得越界）

改 3：
1. `backend/app/services/exercise_mapping.py`
2. `backend/app/services/garmin_workout_mapper.py`
3. `backend/app/api/plans.py`

新增 2：
4. `backend/tests/test_mapper_excluded.py`
5. `backend/tests/test_plan_preview_excluded.py`

**禁止修改**：`garmin_plan_sync.py`、`garmin_reschedule.py`、`exercise_mapping_relation.py`、
`exercise_mapping_batch.py`、任何前端、任何迁移、`.env`、任何既有测试文件。

## 开发内容

### 1. `exercise_mapping.py`：`load_all_mappings` 加 opt-in 参数

```python
def load_all_mappings(
    session: Session, *, include_excluded: bool = False
) -> dict[str, dict[str, Any]]:
    """返回映射字典，形状同 load_active_mappings。

    参数：
    - include_excluded=False（默认，同步路径用）：不返回 status='not_applicable' 的行。
      同步路径在 ADR-P0-3 之前仍以「未知动作」处理它们，避免静默丢动作。
    - include_excluded=True（预览路径用）：**包含** not_applicable 行，
      由 mapper 显式判定为「正常排除」并进入 excluded 列表（ADR §4.2）。

    空表时回退 EXERCISE_WHITELIST 等价字典（两种模式相同）。
    """
```

实现：查询条件按参数分支（`include_excluded` 时不加 `status != 'not_applicable'` 的 where）。
文档字符串按上面重写（保留原有的「draft 行会产出 MAPPING_NOT_APPROVED」说明）。

### 2. `garmin_workout_mapper.py`：excluded 通道

#### 2.1 `WorkoutMappingError` 增加可选 `excluded`

```python
def __init__(self, issues: list[dict[str, Any]], excluded: list[dict[str, Any]] | None = None):
    self.issues = issues
    self.excluded = excluded or []
    ...
```

保持向后兼容：只传 `issues` 时 `excluded == []`。

#### 2.2 `map_plan_day` 内新增 excluded 收集

在逐动作循环开始前：

```python
excluded_movements: list[dict[str, Any]] = []
```

在 `mapping is None`（UNKNOWN_EXERCISE）判断**之前**插入：

```python
if mapping is not None and mapping.get("status") == "not_applicable":
    # ADR §4.2：拉伸/有氧等按产品定义不写入力量 Workout，属正常排除。
    # 必须在这里显式跳过，不能落到下面的 status 检查（那会产出
    # MAPPING_NOT_APPROVED 并触发 partial）。
    excluded_movements.append(
        {"name": name, "reason": "not_applicable"}
    )
    continue
```

**要求**：该动作**不产生任何 issue**，也不计入 `mapped_movements`、不参与步数/组数统计。

#### 2.3 返回与抛出

- 结尾 `if issues: raise WorkoutMappingError(issues, excluded=excluded_movements)`
- 成功返回的 preview dict 里新增 `"excluded": excluded_movements`

### 3. `api/plans.py`：预览端点使用包含模式

`GET /plans/{day}/garmin/preview` 里：

```python
mappings = mapping_service.load_all_mappings(session, include_excluded=True)
```

422 分支把 excluded 一并返回（便于前端在报错时也能说清"哪些被正常排除了"）：

```python
except WorkoutMappingError as exc:
    raise HTTPException(
        status_code=422,
        detail={
            "code": "PLAN_MAPPING_UNSUPPORTED",
            "issues": exc.issues,
            "excluded": exc.excluded,
        },
    ) from exc
```

**注意**：`_preview_mappings()` 只软化 `draft`，`not_applicable` 必须原样透传——
检查该函数不会把 `not_applicable` 改成 `active`（按现有实现它只匹配 `"draft"`，
但你仍要读一遍确认，不要改它）。

`garmin_plan_sync.py` **一行不动**（它不传 `include_excluded`，走默认 False）。

### 4. `tests/test_mapper_excluded.py`（新，≥10 例）

用 `map_plan_day` 直接测，mappings 手写：

1. `test_not_applicable_goes_to_excluded` —— 一个力量动作 + 一个 `status='not_applicable'` 的动作
   → 无异常，`preview["excluded"] == [{"name": "腿部拉伸", "reason": "not_applicable"}]`
2. `test_not_applicable_produces_no_issue` —— 同上，断言返回成功（没抛 `WorkoutMappingError`）
3. `test_not_applicable_not_in_steps` —— 断言 preview 的 steps/动作里**不含**该动作名
4. `test_not_applicable_not_counted_in_totals` —— 断言总组数等于力量动作的组数
5. `test_only_not_applicable_still_raises_empty_workout` —— 只有拉伸动作时，
   现有 `EMPTY_WORKOUT` 或空 payload 行为保持不变
   （**先读代码确认现状再断言**：若力量动作为 0 会抛 `EMPTY_WORKOUT` 或产生空组，
   按实际行为断言，并在报告里说明）
6. `test_excluded_carried_on_error` —— 构造一个既含拉伸又含未知动作的计划，
   断言抛出的 `WorkoutMappingError.excluded` 含拉伸、`issues` 含 `UNKNOWN_EXERCISE`
7. `test_draft_still_mapping_not_approved` —— `status='draft'` 仍产出 `MAPPING_NOT_APPROVED`
   （回归保护：不得把 draft 也当成正常排除）
8. `test_disabled_still_mapping_not_approved` —— 同上，`status='disabled'`
9. `test_workout_mapping_error_backward_compatible` —— `WorkoutMappingError([...])` 的
   `excluded == []`
10. `test_multiple_not_applicable_all_listed` —— 两个拉伸动作，`excluded` 含两条且顺序与输入一致

### 5. `tests/test_plan_preview_excluded.py`（新，≥5 例，走 TestClient）

沿用既有 API 测试的 fixture 风格（`session` / client / 造计划数据的 helper；
**不要改既有 conftest**，按现有测试文件的写法从 `app.main` 取 app）：

1. `test_preview_returns_excluded` —— 计划日含力量动作 + 拉伸动作（mapper 能看到
   `not_applicable` 行）→ 200，响应含 `excluded` 且列出拉伸动作
2. `test_preview_still_422_on_unmapped` —— 计划日含一个 DB 里完全没有的动作 → 422，
   `detail` 里同时有 `issues` 与 `excluded`
3. `test_preview_draft_softened_not_excluded` —— draft 动作在预览里仍按 active 处理
   （`_preview_mappings` 行为不变）
4. `test_load_all_mappings_default_excludes_not_applicable` ——
   `load_all_mappings(session)` 不含 not_applicable 行（**同步路径契约不变**）
5. `test_load_all_mappings_include_excluded` ——
   `load_all_mappings(session, include_excluded=True)` 含该行且 `status == 'not_applicable'`

## 自报告要求（交付时必须给出）

1. 改动文件清单（对照预算 5 个），每个文件改动行数与函数名。
2. **`map_plan_day` 跳过逻辑的插入位置**：贴出 `mapping is None` / not_applicable / status 三者
   的先后顺序代码（证明 not_applicable 判定在 status 检查之前）。
3. **实测三组输入输出**：
   - 力量 + 拉伸 → 状态码/`excluded`/步数
   - 只有拉伸 → 行为
   - 力量 + 未知动作 + 拉伸 → 状态码/`issues`/`excluded`
4. 确认 `garmin_plan_sync.py` 未被修改（`git diff --stat` 自检输出）。
5. 设计取舍：
   - 为什么用 opt-in 参数而不是直接去掉过滤
   - 为什么 excluded 不放进 issues
   - 为什么 `WorkoutMappingError` 用可选参数而不是新增必填参数
6. 确认清单：
   - 未跑 pytest
   - 未执行 git
   - 未改 `.env` 系列
   - 未改 `garmin_plan_sync.py` / `garmin_reschedule.py` / 前端 / 迁移 / 既有测试文件
   - 文件无 BOM、UTF-8
7. 行为自检清单：
   - [ ] not_applicable 不产生任何 issue
   - [ ] not_applicable 不进 steps、不计入组数
   - [ ] draft / disabled 仍产 `MAPPING_NOT_APPROVED`（未被误当成正常排除）
   - [ ] `load_all_mappings()` 默认行为与改动前完全一致
   - [ ] 同步路径（`garmin_plan_sync.py`）零改动

## 明确不做

- 不改同步路径的「跳过 + partial + 缺口记录」（下一片 ADR-P0-3）
- 不改 `sync_result_json` / `garmin_plan_sync` 表结构
- 不改前端（excluded 先只出现在 API 响应里）
- 不改 `_preview_mappings()` 的软化逻辑
- 不改 `not_applicable` 的判定口径（仍由 `classify_applicability` 决定）
