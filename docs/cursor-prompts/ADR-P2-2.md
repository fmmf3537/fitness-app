# ADR-P2-2 AI 只读审核员（不改映射，只产出待确认清单）

> 你是本仓库的资深后端工程师（FastAPI + SQLAlchemy 2.x + Alembic + pytest）。
> 本提示词是唯一任务来源：只按本提示词写代码，**不跑任何验收命令（pytest 一律不跑）**，**不执行任何 git 命令**。
> 红线：禁整文件重写（外科式最小修改）；所有写出的文件必须无 BOM、UTF-8；不得修改 `.env` / `.env.*`；不得删除任何既有文件；不得改动本提示词文件预算之外的任何文件。

## 需求背景

ADR §11：**AI 只作为只读审核员或候选提议者，不直接改变 active 映射**。

与既有 `exercise_mapping_llm.suggest_candidates_with_llm()`（V6-3，生成候选）的区别：
那是"从零选一个"（开放生成，难度高、实测 accepted=0）；本片是"**判断既有映射对不对**"
（封闭判断，难度低得多）。这是评审后确认的正确用法。

AI 输出必须支持五种判定：

| verdict | 含义 |
|---|---|
| `current_ok` | 当前映射合理 |
| `better_candidate` | 存在更贴切的候选（需给出 category + exerciseName） |
| `suspected_error` | 当前映射疑似错误 |
| `likely_unmapped` | 可能没有 Garmin 对应 |
| `needs_human` | 信息不足，需要人工判断 |

约束（ADR §11 原文）：
- 所有候选必须来自真实 Garmin 目录并经过结构校验；
- AI 结果保存理由与版本信息；
- 人工或规则确认后才进入正式映射。

## 已核实的关键事实（实读代码，可直接采信）

- `backend/app/adapters/llm.py` 提供 `chat(messages, *, session=None, purpose=...)` 与
  `strip_think()`；`exercise_mapping_llm.py` 里的调用方式：
  ```python
  chat_fn = lambda msgs: llm.chat(msgs, session=session, purpose="exercise_mapping")
  ```
  测试里通过注入 `chat_fn` 完全避免真实外呼（**本片必须沿用这个注入点**）
- `backend/app/services/exercise_mapping_llm.py` 已有可复用件：
  `_load_movement_names()`、`_catalog_by_category()`、`_lookup_display_name()`、
  `parse_response(content)`、`validate_candidate(...)`、`strip_think`
- `backend/app/models.py` 现有映射相关表：
  - `ExerciseMapping`：`id / xunji_name / garmin_category / garmin_exercise_name /
    garmin_display_name / status / relation / match_basis / unmapped_reason /
    decision_source / confidence / verified_level / verified_at / note / ...`
  - `ExerciseMappingCandidate`（存候选，rank/status 等）
  - `ExerciseMappingAudit`
  本片**新增**一张审核结果表（见下），不改既有三张表
- Alembic 当前单 head：**`c1d2e3f4a5b6`**
- 现有固定路径端点（`/{mapping_id}` 之前）：`/coverage` `/generate` `/catalog` `/stale-syncs`
  `/batch-activate` `/batch-reset` `/backfill-relations` `/migrate-existing` `/llm-suggest` `/probe`
  `/catalog-diff` `/catalog-apply`

## 文件预算（共 6 个，不得越界）

改 2：
1. `backend/app/models.py`（新增 `ExerciseMappingReview` 表）
2. `backend/app/api/exercise_mappings.py`（新增 2 个固定路径端点）

新增 4：
3. `backend/alembic/versions/d2e3f4a5b6c7_exercise_mapping_review.py`（`down_revision = "c1d2e3f4a5b6"`）
4. `backend/app/services/exercise_mapping_review.py`
5. `backend/tests/test_mapping_review.py`
6. `backend/tests/test_alembic_review_migration.py`

**禁止修改**：`exercise_mapping_llm.py`、`exercise_mapping.py`、`exercise_mapping_relation.py`、
`exercise_mapping_batch.py`、`exercise_mapping_candidates.py`、同步链路、任何前端、
`.env`、任何既有测试文件。

## 开发内容

### 1. `models.py`：新增 `ExerciseMappingReview`

写在 `ExerciseMappingAudit` 之后，风格照抄该文件既有模型：

```python
class ExerciseMappingReview(Base):
    """ADR §11：AI 只读审核结果。绝不直接改变映射，只产出待确认清单。"""

    __tablename__ = "exercise_mapping_review"

    id: Mapped[int] = mapped_column(primary_key=True)
    mapping_id: Mapped[int | None] = mapped_column(Integer, index=True)
    xunji_name: Mapped[str] = mapped_column(String(200), index=True)
    # current_ok / better_candidate / suspected_error / likely_unmapped / needs_human
    verdict: Mapped[str] = mapped_column(String(32))
    suggested_category: Mapped[str | None] = mapped_column(String(64))
    suggested_exercise_name: Mapped[str | None] = mapped_column(String(128))
    suggested_display_name: Mapped[str | None] = mapped_column(String(200))
    reason: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String(64))
    batch_id: Mapped[str | None] = mapped_column(String(64), index=True)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: local_now(), server_default=func.now()
    )
```

> `resolved` 用 `Boolean` + `server_default`；SQLite 与 PG 都要能建表，写法参照文件里既有布尔列
> （若文件里没有布尔列，用 `Boolean, default=False`，`server_default` 换成
> `sa.text("0")` 兼容写法；**先看现有模型再决定**）。

### 2. 迁移 `d2e3f4a5b6c7_...py`

- `revision = "d2e3f4a5b6c7"`、`down_revision = "c1d2e3f4a5b6"`
- `upgrade()` 建表（字段与模型一致，含 3 个索引：`mapping_id`、`xunji_name`、`batch_id`）
- `downgrade()` drop 表
- 风格照抄 `a9b0c1d2e3f4_exercise_mapping_relation.py`

### 3. `exercise_mapping_review.py`（新服务）

#### 3.1 常量

```python
VERDICT_CURRENT_OK = "current_ok"
VERDICT_BETTER = "better_candidate"
VERDICT_SUSPECTED_ERROR = "suspected_error"
VERDICT_LIKELY_UNMAPPED = "likely_unmapped"
VERDICT_NEEDS_HUMAN = "needs_human"
VERDICTS = (VERDICT_CURRENT_OK, VERDICT_BETTER, VERDICT_SUSPECTED_ERROR,
            VERDICT_LIKELY_UNMAPPED, VERDICT_NEEDS_HUMAN)

REVIEW_BATCH_SIZE = 20
REVIEW_MAX_BATCHES = 10
```

#### 3.2 `build_prompt(items: list[dict]) -> list[dict]`

构造 messages。要求：

- system 段说明：你是**审核员**，判断给定的「训记动作 → 当前 Garmin 映射」是否合理；
  **只在给定候选列表里选择**，不得发明目录外的值；拿不准就返回 `needs_human`；
  明确允许返回 `likely_unmapped`（这是合法结论，不是失败）。
- user 段逐条给出：`xunji_name`、当前 `category/exerciseName/display_name`、
  `relation`、`note`、以及该动作所属部位的**真实候选列表**（用
  `_catalog_by_category()` 取，每类最多 40 条，超出截断并注明）。
- **输出格式要求 JSON 数组**，每项：
  `{"name": str, "verdict": str, "suggested": {"category": str, "exerciseName": str} | null, "reason": str}`
- 明确要求 `reason` 用中文、不超过 80 字。

#### 3.3 `parse_review_response(content: str) -> list[dict]`

解析模型输出：先 `strip_think`，再提取首个 `[` 到末个 `]`，`json.loads`；
失败返回 `[]`。逐项校验：`name` 是非空 str、`verdict in VERDICTS`，
否则丢弃该项（不抛错）。

#### 3.4 `validate_suggestion(category, exercise_name) -> bool`

复用 `exercise_mapping_llm.validate_candidate`（**只 import，不改它**）或
`exercise_mapping._catalog_pair_exists`。要求：category 在
`garmin_exercises.CATEGORIES` 内，且 `(category, exercise_name)` 在目录里存在
（`exercise_name` 为空串时按 `_validate_exercise_pair` 的口径视为合法，但
**审核建议不得给空串**——空串建议直接判为无效）。

#### 3.5 `review_mappings(session, *, limit=200, max_batches=10, chat_fn=None, only_active=True) -> dict`

```python
def review_mappings(
    session: Session,
    *,
    limit: int = 200,
    max_batches: int = REVIEW_MAX_BATCHES,
    chat_fn: Callable[[list[dict]], dict] | None = None,
    only_active: bool = True,
) -> dict:
    """ADR §11：对既有映射做只读审核，结果写入 exercise_mapping_review。

    - **绝不修改** ExerciseMapping 的任何字段（status/relation/verified_level 全不动）
    - 每个 verdict 都落库，同一 xunji_name 以最新一条为准（旧记录保留）
    - suggested 未通过 validate_suggestion 时降级为 needs_human，并把原因写进 reason
    """
```

返回统计：

```python
{
  "requested": int, "processed": int, "batches": int,
  "by_verdict": {"current_ok": n, "better_candidate": n, "suspected_error": n,
                 "likely_unmapped": n, "needs_human": n},
  "rejected_suggestions": int,   # 建议未通过目录校验被降级的条数
  "prompt_tokens": int, "completion_tokens": int,
  "batch_id": str,               # uuid4 hex，便于把本次结果捞出来
}
```

要点：
- `chat_fn is None` 时才调 `llm.chat`；测试注入 fake 后**不得**触网
- 批次间保持与 `exercise_mapping_llm` 一致的容错：单批失败不中断整体（记录后继续），
  但连续失败达到 `max_batches` 内阈值时提前停止（可参考既有实现的写法，不必照抄）
- `batch_id` 用 `uuid.uuid4().hex`

#### 3.6 `list_reviews(session, *, batch_id=None, verdict=None, limit=200) -> list[dict]`

返回审核结果列表（新的在前），字段：`id / xunji_name / verdict /
suggested_category / suggested_exercise_name / reason / model / batch_id/
resolved / created_at`（`created_at` 用 `isoformat()`）。

### 4. `api/exercise_mappings.py` 新增两个固定路径端点

放在 `/{mapping_id}` **之前**。

```python
@router.post("/review")
def post_review(
    limit: int = Query(default=200, ge=1, le=400),
    max_batches: int = Query(default=10, ge=1, le=30),
    session: Session = Depends(get_session),
) -> dict:
    """ADR §11：对既有映射做 AI 只读审核（绝不修改映射）。"""
    return review_svc.review_mappings(session, limit=limit, max_batches=max_batches)


@router.get("/reviews")
def get_reviews(
    batch_id: str | None = Query(default=None),
    verdict: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
    session: Session = Depends(get_session),
) -> dict:
    """查询 AI 审核结果（只读）。"""
    return {"items": review_svc.list_reviews(session, batch_id=batch_id,
                                             verdict=verdict, limit=limit)}
```

### 5. `tests/test_mapping_review.py`（新，≥16 例）

**解析与校验（6 例）**
1. `test_parse_valid_array` —— 合法 JSON 数组 → 解析出全部条目
2. `test_parse_strips_think_block` —— 含 ` thinking...</think>` 时仍能解析
3. `test_parse_invalid_json_returns_empty` —— 非法 JSON → `[]`
4. `test_parse_drops_unknown_verdict` —— 含非法 verdict 的项被丢弃，其余保留
5. `test_validate_suggestion_rejects_unknown_pair` —— 目录外组合 → False
6. `test_validate_suggestion_rejects_empty_exercise` —— 空串建议 → False

**审核主流程（6 例）**
7. `test_review_writes_rows` —— 注入 fake `chat_fn` 返回 2 条 → 落库 2 行 `ExerciseMappingReview`
8. `test_review_never_modifies_mapping` —— 审核前后 `ExerciseMapping` 的
   `status / relation / verified_level / mapping_version / note` 全部不变
9. `test_review_counts_by_verdict` —— 5 种 verdict 各 1 条 → `by_verdict` 计数正确
10. `test_invalid_suggestion_downgraded` —— 建议目录外组合 →
    `verdict` 降级为 `needs_human`，`rejected_suggestions == 1`
11. `test_review_does_not_call_network_when_injected` —— 注入 `chat_fn` 时断言
    `llm.chat` 未被调用（用 monkeypatch 把 `llm.chat` 换成会抛 AssertionError 的桩）
12. `test_batch_id_is_unique_per_run` —— 两次运行 `batch_id` 不同，且能按 `batch_id` 过滤

**容错（2 例）**
13. `test_chat_failure_does_not_crash` —— `chat_fn` 抛异常 → 不崩溃，返回统计中 `processed` 合理
14. `test_empty_targets_returns_zero_stats` —— 表为空时不调用 LLM，返回零值统计

**列表查询（2 例）**
15. `test_list_reviews_orders_desc` —— 新的在前
16. `test_list_reviews_filters_verdict` —— 按 verdict 过滤生效

**API（2 例）**
17. `test_review_endpoint_requires_auth` —— 401/403
18. `test_reviews_endpoint_returns_items` —— 200 且含 `items`

### 6. `tests/test_alembic_review_migration.py`（新，≥3 例）

1. `test_single_head` —— 单 head 且本 revision 在链上（**不要写死 head 等于它**，
   照抄 `tests/test_alembic_relation_migration.py::test_single_head` 的不变式写法）
2. `test_down_revision` —— `down_revision == "c1d2e3f4a5b6"`
3. `test_model_table_matches` —— `ExerciseMappingReview.__tablename__ == "exercise_mapping_review"`
   且必要列存在

## 自报告要求（交付时必须给出）

1. 改动文件清单（对照预算 6 个），每个文件改动行数与函数名。
2. **`build_prompt` 的完整 system 指令原文**（贴出来，便于审核措辞是否诱导幻觉）。
3. **实测**：注入一个返回 5 种 verdict 的 fake `chat_fn`，贴出
   `review_mappings` 返回的完整统计 + `list_reviews` 的首条记录。
4. **「不改映射」的证据**：贴出审核前后某条 `ExerciseMapping` 的字段快照对比。
5. 设计取舍：
   - 为什么审核员只给候选列表、不允许自由生成
   - 为什么 `likely_unmapped` 与 `needs_human` 必须分开
   - 为什么建议未通过目录校验要降级为 `needs_human` 而不是直接丢弃
   - 为什么结果单独建表而不是塞进审计表
6. 确认清单：
   - 未跑 pytest
   - 未执行 git
   - 未改 `.env` 系列
   - 未改 `exercise_mapping_llm.py` / `exercise_mapping.py` / `exercise_mapping_relation.py` /
     `exercise_mapping_batch.py` / `exercise_mapping_candidates.py` / 同步链路 /
     任何前端 / 任何既有测试文件
   - 注入 `chat_fn` 后**零网络调用**
   - 文件无 BOM、UTF-8
7. 行为自检清单：
   - [ ] 五种 verdict 全部支持
   - [ ] 审核**绝不修改** ExerciseMapping
   - [ ] 建议必须来自真实目录，否则降级 `needs_human`
   - [ ] 注入 `chat_fn` 时不触网
   - [ ] 单批失败不中断整体
   - [ ] `batch_id` 每次运行唯一且可过滤
   - [ ] 迁移单 head 且 `down_revision` 正确
   - [ ] 两个端点注册在 `/{mapping_id}` 之前

## 明确不做

- 不改映射状态、不自动采纳 AI 建议（人工/规则确认是后续 or 人工操作）
- 不改既有 `suggest_candidates_with_llm`（V6-3 的生成器保持原样）
- 不改前端
- 不做自动调度（手动触发端点）
