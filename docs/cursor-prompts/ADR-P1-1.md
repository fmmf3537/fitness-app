# ADR-P1-1 训记动作全集变更：解析后集合 diff + 改名继承 + 删除留痕

> 你是本仓库的资深后端工程师（FastAPI + SQLAlchemy 2.x + pytest）。
> 本提示词是唯一任务来源：只按本提示词写代码，**不跑任何验收命令（pytest 一律不跑）**，**不执行任何 git 命令**。
> 红线：禁整文件重写（外科式最小修改）；所有写出的文件必须无 BOM、UTF-8；不得修改 `.env` / `.env.*`；不得删除任何既有文件；不得改动本提示词文件预算之外的任何文件。

## 需求背景

ADR §8：训记动作全集来自仓库中的静态 JSON，**不建设运行时扫描**。文件变更时由部署/CI 检查执行：

1. 解析变更前后的 JSON，比较**动作名称集合**，不依赖文本行 diff（避免排序/缩进噪声）；
2. 输出新增、消失、未变化；
3. 对「消失 + 新增」生成**疑似改名候选**，可结合字面相似度与器械/动作词根，**但不得自动继承**；
4. 人工判定「改名 / 新动作 / 删除」：
   - 改名：保留内部 `exercise_mapping.id`，更新 `xunji_name`，旧名进审计；Garmin 目标未变时**不重置** `verified_level`
   - 新动作：创建 draft 行，进入正常匹配与审核
   - 删除：保留历史映射与审计，**不再作为当前动作参与同步**，不得物理删除
5. 检查必须产生**明确失败或必须确认的待办**，不能只生成无人处理的报告。

## 已核实的关键事实（实读代码，可直接采信）

- `backend/app/data/xunji_movements.json`：JSON **数组，元素是字符串动作名**，当前 1091 项
- `backend/app/services/exercise_mapping_batch.py` 有 `_load_movement_names()` 读取该文件；
  `generate_all(session, ...)` 以此为全集
- `backend/app/models.py` 的 `ExerciseMapping` 现有列（与本次相关的）：
  `id / xunji_name(唯一) / status / relation / match_basis / unmapped_reason /
   decision_source / verified_level / verified_at / mapping_version / note / source`
- 审计辅助：`backend/app/services/exercise_mapping.py` 的
  `_write_audit(session, row, action=..., before=..., after=..., reason=..., actor=...)`
  写 `exercise_mapping_audit` 表
- `ExerciseMapping.xunji_name` 有唯一约束——改名前必须先确保目标名不存在
- Alembic 当前单 head：**`c1d2e3f4a5b6`**（本片**不加迁移**）
- 现有固定路径端点（`/{mapping_id}` 之前注册）：
  `/coverage` `/generate` `/catalog` `/stale-syncs` `/batch-activate` `/batch-reset`
  `/backfill-relations` `/migrate-existing` `/llm-suggest` `/probe`

## 文件预算（共 4 个，不得越界）

改 1：
1. `backend/app/api/exercise_mappings.py`（新增 2 个固定路径端点）

新增 3：
2. `backend/app/services/exercise_mapping_catalog.py`（diff 与变更应用服务）
3. `backend/tests/test_mapping_catalog_diff.py`
4. `scripts/check_xunji_catalog.py`（CI/部署检查脚本，非 pytest）

**禁止修改**：`models.py`、任何迁移、`exercise_mapping.py`、`exercise_mapping_relation.py`、
`exercise_mapping_batch.py`、`exercise_mapping_candidates.py`、同步链路、任何前端、
`.env`、`app/data/xunji_movements.json`、任何既有测试文件。

## 开发内容

### 1. `exercise_mapping_catalog.py`（新服务）

#### 1.1 常量与辅助

```python
RENAME_CANDIDATE_THRESHOLD = 0.5   # 字面相似度（difflib.SequenceMatcher.ratio）低于此值不成对

# 用于「疑似改名」的辅助特征：动作词根 + 器械词根的交集
```

- 复用 `app.services.exercise_tokens` 的 `MOVEMENT_TOKENS` / `EQUIPMENT_TOKENS`
  与 `app.services.exercise_mapping_candidates._norm()`（只 import，不改它们）

#### 1.2 `catalog_diff(session, names: list[str] | None = None) -> dict`

```python
def catalog_diff(session: Session, names: list[str] | None = None) -> dict:
    """比较「当前 JSON 动作全集」与「数据库映射行」，返回结构化差异。

    names 为 None 时从 app/data/xunji_movements.json 读取（复用 batch 的读取函数或自行读取）。

    返回：
    {
      "current_total": int,          # JSON 中的动作数
      "db_total": int,               # 数据库映射行数
      "added": [str, ...],           # JSON 有、DB 无（升序）
      "removed": [str, ...],         # DB 有、JSON 无（升序）
      "unchanged": int,              # 集合交集大小
      "rename_candidates": [
        {"from": str, "to": str, "score": float, "reasons": [str, ...]},
        ...
      ],
      "needs_confirmation": bool,    # added 或 removed 非空即 True
    }
    """
```

**疑似改名配对规则**（不得自动继承，只产出候选）：

- 对每个 `removed` × `added` 组合计算 `score = difflib.SequenceMatcher(None, a, b).ratio()`
- 若两者共享动作词根（用 `MOVEMENT_TOKENS` 命中，中文键）→ `reasons` 加 `"same_movement_token"`
- 若两者共享器械词根（`EQUIPMENT_TOKENS` 命中）→ `reasons` 加 `"same_equipment_token"`
- 仅保留 `score >= RENAME_CANDIDATE_THRESHOLD` **或** `reasons` 非空 的组合
- 每个 `removed` 与每个 `added` **最多各出现一次**（取分值最高的一对，贪心即可）
- 按 `score` 降序排列

#### 1.3 `apply_catalog_change(session, *, action, old_name=None, new_name=None, actor="user") -> dict`

```python
def apply_catalog_change(
    session: Session,
    *,
    action: str,
    old_name: str | None = None,
    new_name: str | None = None,
    actor: str = "user",
) -> dict:
    """应用人工判定。action ∈ {"rename", "new", "delete"}。

    rename：old_name 的行保留 id，xunji_name 改为 new_name；
            Garmin 目标不变，因此**不重置** verified_level / verified_at；
            写审计 action="rename"，before/after 含旧名与新名，reason="catalog_change"。
            old_name 必须存在、new_name 必须不存在（唯一约束），否则抛 ValueError。
    new：   为 new_name 创建 draft 行（relation/match_basis/unmapped_reason/
            confidence/verified_level 全为 None，source="auto"，mapping_version=1），
            若已存在则抛 ValueError。
    delete：把 old_name 的行 status 置 "disabled"，并在 note 追加
            "训记已移除该动作（catalog_change）"，**不物理删除**；
            写审计 action="delete"，reason="catalog_change"。

    返回 {"action": ..., "xunji_name": ..., "mapping_id": int | None, "changed": bool}；
    幂等：重复应用同一判定时 changed=False 且不重复写审计。
    """
```

错误处理：非法 `action`、缺参数、目标名已存在等情况抛 `ValueError`，由 API 转 422。

### 2. `api/exercise_mappings.py` 新增两个固定路径端点

**注册位置**：放在 `/{mapping_id}` **之前**，与其它固定路径一起。

```python
class CatalogApplyBody(BaseModel):
    action: str                      # rename / new / delete
    old_name: str | None = None
    new_name: str | None = None


@router.get("/catalog-diff")
def get_catalog_diff(session: Session = Depends(get_session)) -> dict:
    """比较训记动作全集与映射表，返回新增/消失/疑似改名候选（只读）。"""
    return catalog_svc.catalog_diff(session)


@router.post("/catalog-apply")
def post_catalog_apply(
    body: CatalogApplyBody, session: Session = Depends(get_session)
) -> dict:
    """应用人工判定的改名 / 新动作 / 删除。"""
    try:
        return catalog_svc.apply_catalog_change(
            session,
            action=body.action,
            old_name=body.old_name,
            new_name=body.new_name,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_CATALOG_CHANGE", "message": str(exc)},
        ) from exc
```

### 3. `scripts/check_xunji_catalog.py`（CI/部署检查，非 pytest）

- 用 `argparse` 或直接 `main()`，**不依赖 pytest**
- 连数据库（复用 `app.db.get_session` / `SessionLocal` 的既有写法），调 `catalog_diff()`
- 输出人类可读摘要：新增 N / 消失 M / 疑似改名 K
- **有差异时 `sys.exit(1)`**（ADR §8 第 5 条：必须产生明确失败或必须确认的待办）
- 无差异时打印 OK 并 `sys.exit(0)`
- 支持 `--json` 输出原始报告
- 脚本顶部写清用途与用法注释（中文）

> 该脚本**不进 pytest 收集**（不在 tests/ 下）。确保它被 pytest 忽略即可。

### 4. `tests/test_mapping_catalog_diff.py`（新，≥14 例）

**diff（7 例）**
1. `test_no_diff_when_identical` —— 传与 DB 完全一致的 names →
   `added == [] and removed == [] and needs_confirmation is False`
2. `test_added_detected` —— 多一个名字 → `added == ["新动作"]`
3. `test_removed_detected` —— 少一个名字 → `removed == ["旧动作"]`
4. `test_unchanged_count` —— `unchanged == len(交集)`
5. `test_rename_candidate_by_movement_token` —— `哑铃卧推` → `哑铃平板卧推`
   （共享动作词根 卧推）→ 产生一条候选且 `reasons` 含 `same_movement_token`
6. `test_rename_candidate_by_similarity` —— 字面高相似但无共同词根 → 仍产生候选
   （`score >= 0.5`）
7. `test_unrelated_names_not_paired` —— 完全无关的消失/新增 → `rename_candidates == []`

**apply rename（3 例）**
8. `test_rename_keeps_id_and_updates_name` —— `mapping_id` 不变、`xunji_name` 更新
9. `test_rename_does_not_reset_verified_level` —— 改名前后
   `verified_level` / `verified_at` 不变（ADR §8：Garmin 目标未变）
10. `test_rename_writes_audit_with_old_name` —— 审计 `action='rename'` 且
    `before` 或 `after` 里能查到旧名

**apply new / delete（2 例）**
11. `test_new_creates_draft_row` —— `status='draft'`、`relation is None`、
    `confidence is None`、`mapping_version == 1`
12. `test_delete_disables_without_removing` —— `status == 'disabled'`、行仍在、
    `note` 含「训记已移除」、审计 `action='delete'`

**错误与幂等（3 例）**
13. `test_rename_rejects_missing_old` / `test_rename_rejects_existing_new` —— 抛 `ValueError`
14. `test_apply_is_idempotent` —— 同一判定重复应用，第二次 `changed is False`
15. `test_invalid_action_raises` —— `action='bogus'` 抛 `ValueError`

**API（2 例）**
16. `test_catalog_diff_endpoint` —— GET 200，含 `added/removed/rename_candidates`
17. `test_catalog_apply_endpoint_returns_422_on_bad_input` —— 非法 action →
    422 且 `detail["code"] == "INVALID_CATALOG_CHANGE"`

## 自报告要求（交付时必须给出）

1. 改动文件清单（对照预算 4 个），每个文件改动行数与函数名。
2. **疑似改名配对的实测**：在本地造一组「消失 3 + 新增 3」，贴出 `rename_candidates` 实际输出
   （含 score 与 reasons），并说明贪心配对的顺序。
3. **rename 的字段影响清单**：明确列出哪些字段被改（`xunji_name`、`mapping_version`）、
   哪些**没变**（`verified_level`、`verified_at`、`relation`、`confidence`、`status`）。
4. `scripts/check_xunji_catalog.py` 的 **两种退出码实测**：无差异 → 0；有差异 → 1。
5. 设计取舍：
   - 为什么比较解析后的名称集合而不是文本 diff
   - 为什么改名候选不自动继承
   - 为什么「删除」用 `status='disabled'` 而不是物理删除
   - 为什么 rename 要 bump `mapping_version` 但不重置 `verified_level`
6. 确认清单：
   - 未跑 pytest
   - 未执行 git
   - 未改 `.env` 系列
   - 未改 `models.py` / 任何迁移 / `exercise_mapping*.py`（除新增的 catalog 服务）/
     同步链路 / 任何前端 / `app/data/xunji_movements.json` / 任何既有测试文件
   - 文件无 BOM、UTF-8
7. 行为自检清单：
   - [ ] 集合比较，排序/缩进变化不产生误报
   - [ ] 疑似改名只产出候选，不自动应用
   - [ ] rename 保留 `id`、不改 `verified_level`/`verified_at`
   - [ ] new 创建完整 draft 行
   - [ ] delete 只置 disabled + note，不删行
   - [ ] 三个 action 幂等
   - [ ] 检查脚本有差异时退出码 1
   - [ ] 两个新端点注册在 `/{mapping_id}` 之前

## 明确不做

- 不改 `xunji_movements.json` 本身
- 不做运行时扫描或定时任务（ADR §8 明确不建设）
- 不做别名管理模块（ADR §8：第一期复用 id + 审计）
- 不改 `generate_all` 的全集来源
- 不改前端
