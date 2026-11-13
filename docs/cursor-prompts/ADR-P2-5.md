# ADR-P2-5 审核端点加筛选参数（status / xunji_name / offset）

> 你是本仓库的资深后端工程师（FastAPI + SQLAlchemy 2.x + pytest）。
> 本提示词是唯一任务来源：只按本提示词写代码，**不跑任何验收命令（pytest 一律不跑）**，**不执行任何 git 命令**。
> 红线：禁整文件重写（外科式最小修改）；所有写出的文件必须无 BOM、UTF-8；不得修改 `.env` / `.env.*`；不得删除任何既有文件；不得改动本提示词文件预算之外的任何文件。

## 需求背景

AI 只读审核（ADR-P2-2）已验证可用：政策 prompt 校准后，40 条里 4 条非 `current_ok` 全部有依据、`rejected_suggestions=0`（无幻觉）。

但**操作上不可用**。`_select_targets` 现状：

```python
stmt = select(ExerciseMapping).order_by(ExerciseMapping.id)
if only_active:
    stmt = stmt.where(ExerciseMapping.status == "active")
if limit > 0:
    stmt = stmt.limit(limit)
```

两个后果：

1. **不是抽样，是"永远审前 N 条"**：`limit=40` 每次都取最小 id 的 40 条，
   反复跑覆盖不到新行，也无法跳过已审过的行；
2. **无法指定动作**：某动作同步报 `MAPPING_NOT_APPROVED` 时，
   最需要 AI 判断"该选哪个 Garmin 条目"，但现在只能从头审 40 条才轮到它。

本片只加三个查询参数把它们打开，**不改审核逻辑、不改 prompt、不改落库结构**。

## 已核实的关键事实（实读代码，可直接采信）

- `backend/app/services/exercise_mapping_review.py`
  - `_select_targets(session, *, limit, only_active) -> list[ExerciseMapping]`（上面那段就是全文）
  - `review_mappings(session, *, limit=200, max_batches=10, chat_fn=None, only_active=True) -> dict`
    内部调 `_select_targets(session, limit=limit, only_active=only_active)`
  - 目标为空时**直接返回零值统计，不调用 LLM**（现有行为，必须保持）
  - 返回统计含 `requested / processed / batches / by_verdict / rejected_suggestions /
    prompt_tokens / completion_tokens / batch_id`
- `backend/app/api/exercise_mappings.py` 的 `POST /review`：
  ```python
  @router.post("/review")
  def post_review(
      limit: int = Query(default=200, ge=1, le=400),
      max_batches: int = Query(default=10, ge=1, le=30),
      session: Session = Depends(get_session),
  ) -> dict:
      return review_svc.review_mappings(session, limit=limit, max_batches=max_batches)
  ```
- `ExerciseMapping.status` 取值：`draft / active / disabled / not_applicable`
- Alembic 当前单 head：`d2e3f4a5b6c7`（本片**不加迁移**）

## 文件预算（共 3 个，不得越界）

改 2：
1. `backend/app/services/exercise_mapping_review.py`
2. `backend/app/api/exercise_mappings.py`

新增 1：
3. `backend/tests/test_review_filters.py`

**禁止修改**：`exercise_mapping*.py`（candidates / batch / relation / llm / catalog）、
`garmin_*`、`models.py`、任何迁移、任何前端、`.env`、任何既有测试文件。

## 开发内容

### 1. `_select_targets` 加筛选

签名改为：

```python
def _select_targets(
    session: Session,
    *,
    limit: int,
    only_active: bool,
    status: str | None = None,
    xunji_name: str | None = None,
    offset: int = 0,
) -> list[ExerciseMapping]:
```

筛选顺序（保持 `order_by(id)`）：

```python
stmt = select(ExerciseMapping).order_by(ExerciseMapping.id)
if status is not None:
    # status 优先于 only_active（显式指定时以它为准）
    stmt = stmt.where(ExerciseMapping.status == status)
elif only_active:
    stmt = stmt.where(ExerciseMapping.status == "active")
if xunji_name is not None:
    stmt = stmt.where(ExerciseMapping.xunji_name == xunji_name)
if offset > 0:
    stmt = stmt.offset(offset)
if limit > 0:
    stmt = stmt.limit(limit)
return list(session.scalars(stmt).all())
```

要点：
- `status` 与 `only_active` 的优先级必须写进 docstring（避免以后有人以为两者叠加）
- `xunji_name` 是**精确匹配**（不是模糊），与 `exercise_mapping.xunji_name` 的唯一约束一致
- `offset` 在 `limit` 之前应用
- 三者都为默认值（None/None/0）时，行为必须与改动前**完全一致**

### 2. `review_mappings` 透传

签名追加同样三个参数（保持 `only_active=True` 默认，向后兼容）：

```python
def review_mappings(
    session: Session,
    *,
    limit: int = 200,
    max_batches: int = REVIEW_MAX_BATCHES,
    chat_fn: Callable[[list[dict]], dict] | None = None,
    only_active: bool = True,
    status: str | None = None,
    xunji_name: str | None = None,
    offset: int = 0,
) -> dict:
```

并在 docstring 里补一段"三种典型用法"：

```python
    典型用法：
    - 指定动作：xunji_name="哑铃臂屈伸"（对应「这个动作到底该映射到哪」）
    - 审一批 draft：status="draft", limit=30（批量采纳前先过一遍）
    - 分批推进：offset=40, limit=40（避免重复审已处理过的行）
```

目标为空时仍**不调用 LLM**，返回零值统计（现有行为不得变）。

### 3. `api/exercise_mappings.py` 的 `POST /review`

```python
@router.post("/review")
def post_review(
    limit: int = Query(default=200, ge=1, le=400),
    max_batches: int = Query(default=10, ge=1, le=30),
    status: str | None = Query(
        default=None, pattern="^(draft|active|disabled|not_applicable)$"
    ),
    xunji_name: str | None = Query(default=None, max_length=200),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> dict:
    """ADR §11：对既有映射做 AI 只读审核（绝不修改映射）。

    支持按状态 / 动作名 / 偏移筛选，便于定点核查与分批推进。
    """
    return review_svc.review_mappings(
        session,
        limit=limit,
        max_batches=max_batches,
        status=status,
        xunji_name=xunji_name,
        offset=offset,
    )
```

`status` 用 `pattern` 做白名单校验，非法值由 FastAPI 自动返回 422。

### 4. `tests/test_review_filters.py`（新，≥12 例）

沿用既有 `tests/test_mapping_review.py` 的写法（`session` 夹具 + 注入 fake `chat_fn`；
**先读那个文件**，照抄它的造行 helper 与 fake chat，不要自创另一套）。

**服务层（8 例）**
1. `test_default_still_active_only` —— 不传新参数时只选中 active 行（向后兼容）
2. `test_status_overrides_only_active` —— `status="draft"` 且 `only_active=True` →
   选中的全是 draft（证明 status 优先）
3. `test_status_disabled` —— `status="disabled"` 只选中 disabled 行
4. `test_xunji_name_selects_single_row` —— 指定名字时 `requested == 1`
5. `test_xunji_name_not_found_zero_targets` —— 不存在的名字 → 零值统计，
   且**不调用 chat_fn**（用会抛 AssertionError 的桩证明）
6. `test_offset_skips_rows` —— 造 5 行，`offset=2, limit=2` 选中的 id 与
   `offset=0, limit=2` **不重叠**
7. `test_offset_beyond_end_returns_empty` —— `offset` 超出总数 → 零值统计
8. `test_filters_combine` —— `status="draft"` + `offset=1` + `limit=1` 组合生效

**API（4 例）**
9. `test_review_endpoint_accepts_status_filter` —— `?status=draft` → 200
10. `test_review_endpoint_rejects_invalid_status` —— `?status=bogus` → 422
11. `test_review_endpoint_accepts_xunji_name` —— `?xunji_name=xxx` → 200
12. `test_review_endpoint_rejects_negative_offset` —— `?offset=-1` → 422

## 自报告要求（交付时必须给出）

1. 改动文件清单（对照预算 3 个），每个文件改动行数与函数名。
2. **`_select_targets` 的最终实现全文**（贴出来，便于审核筛选顺序）。
3. **实测对照表**（造 6 行：3 active / 2 draft / 1 disabled）：

   | 参数 | 选中行数 | 选中 id 列表 |
   |---|---|---|
   | 默认 | ? | ? |
   | `status="draft"` | ? | ? |
   | `xunji_name="<某行>"` | ? | ? |
   | `offset=2, limit=2` | ? | ? |
   | `status="draft", offset=1` | ? | ? |
   | `xunji_name="不存在"` | ? | ? |

4. 确认「目标为空时不调 LLM」：贴出那条测试的断言方式。
5. 设计取舍：
   - 为什么 `status` 用优先级覆盖 `only_active` 而不是两者 AND
   - 为什么 `xunji_name` 用精确匹配而不是模糊
   - 为什么不加 `order_by` 之外的随机排序（说明为什么 offset 分批已够用）
6. 确认清单：
   - 未跑 pytest
   - 未执行 git
   - 未改 `.env` 系列
   - 未改其它 `exercise_mapping*.py` / `garmin_*` / `models.py` / 迁移 / 前端 /
     任何既有测试文件
   - 文件无 BOM、UTF-8
7. 行为自检清单：
   - [ ] 不传新参数时行为与改动前完全一致（仍只审 active）
   - [ ] `status` 优先于 `only_active`
   - [ ] `xunji_name` 精确匹配
   - [ ] `offset` 在 `limit` 之前应用
   - [ ] 目标为空时不调用 LLM
   - [ ] 非法 `status` / 负 `offset` 由 FastAPI 返回 422
   - [ ] 未改动审核 prompt、未改动落库结构

## 明确不做

- 不改 `build_prompt` / 审核逻辑 / verdict 判定
- 不改 `exercise_mapping_review` 表结构
- 不加随机抽样（`offset` 分批已覆盖需求）
- 不改前端
