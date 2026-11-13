# ADR-P0-1 数据模型：relation / match_basis / unmapped_reason + 存量回填

> 你是本仓库的资深后端工程师（FastAPI + SQLAlchemy 2.x + Alembic + pytest）。
> 本提示词是唯一任务来源：只按本提示词写代码，**不跑任何验收命令（pytest 一律不跑）**，**不执行任何 git 命令**。
> 红线：禁整文件重写（外科式最小修改）；所有写出的文件必须无 BOM、UTF-8；不得修改 `.env` / `.env.*`；不得删除任何既有文件；不得改动本提示词文件预算之外的任何文件。

## 需求背景

`docs/ADR-EXERCISE-MAPPING.md` 已 Accepted。它把"映射成什么"与"这个决定有多可靠"拆成独立维度，
本切片是 P0 的第一片：**只做数据模型与存量回填**，不改同步链路、不改启用策略。

当前 `exercise_mapping` 只有 `confidence`（high/medium/low）承担双重职责——既表示算法把握，
又当批量启用的闸门。ADR §4.1 要求新增三个维度：

- `relation`：Garmin 能在多大程度上表达训记动作 → `EXACT / SIMILAR / CATEGORY / UNMAPPED`
- `match_basis`：凭什么认为它们对应 → `same_name / alias / translation / semantic_review / rule_features / other`
- `unmapped_reason`：为什么无法映射 → `no_equivalent / no_safe_category / ambiguous / other`

**`ALIAS` 不是 `relation` 的取值**（ADR §4.1 补充约束第 1 条，这是本项目已明确踩过的定义错误）。

## 已核实的关键事实（实读代码，可直接采信）

- `backend/app/models.py` 的 `ExerciseMapping` 现有列：
  `id / xunji_name / garmin_category / garmin_exercise_name / garmin_display_name /
   weight_strategy / status / not_applicable_reason / confidence / source /
   verified_level / verified_at / mapping_version / note / created_at / updated_at`
- `status` 取值：`draft / active / disabled / not_applicable`
- `source` 取值：`seed / auto / llm / manual`
- Alembic 当前单 head：**`f8a9b0c1d2e3`**
  （`backend/alembic/versions/f8a9b0c1d2e3_lateral_raise_verified.py`）
- `backend/app/services/exercise_mapping_candidates.py` 已有可直接复用的判据函数：
  - `extract_tokens(name)` → `{"part", "equipment", "postures", "movements"}`
  - `_norm(text)` → 去非字母数字后小写
  - `equipment_mismatch_note(xunji_name, display_name)` → 器械不符时返回文案，否则 `None`
    （**内部自行归一化，传原始 `garmin_display_name`**）
  - `_qualifier_penalty(xunji_name, name_norm)` → 0 或负数
    （**第二个参数必须是 `_norm(display_name)`，传原始显示名会因大小写/连字符导致全部漏判**）
- `backend/app/services/exercise_mapping.py` 的 `SEED_NOTES` 记录了 16 条 seed 里两条的特殊性：
  - `器械推胸`：`Garmin 无坐姿推胸机条目，用通用 Bench Press 表达` → 这是**大类映射**
  - `侧平举`：已改为哑铃专用项 → 精确映射
- `POST /api/exercise-mappings/generate` 生成的 draft 行里，无候选行的
  `garmin_exercise_name` 为 `None`，`confidence` 为 `None`
- 当前线上分布（供理解，不要写死）：active 317、draft 610、not_applicable 164、
  confidence NULL 97（16 seed + 81 无候选）

## 文件预算（共 6 个，不得越界）

改 2：
1. `backend/app/models.py`（`ExerciseMapping` 加 3 列）
2. `backend/app/api/exercise_mappings.py`（加 1 个固定路径端点）

新增 4：
3. `backend/alembic/versions/a9b0c1d2e3f4_exercise_mapping_relation.py`（迁移，`down_revision = "f8a9b0c1d2e3"`）
4. `backend/app/services/exercise_mapping_relation.py`（分类与回填服务）
5. `backend/tests/test_exercise_mapping_relation.py`
6. `backend/tests/test_alembic_relation_migration.py`

**禁止修改**：`exercise_mapping_candidates.py`、`exercise_mapping.py`、`exercise_mapping_batch.py`、
`garmin_plan_sync.py`、`garmin_workout_mapper.py`、任何前端、`.env`、任何既有测试文件。

## 开发内容

### 1. `models.py`：`ExerciseMapping` 加三列

在 `note` 之后、`created_at` 之前插入（保持现有风格，中英混注释）：

```python
    # ADR-EXERCISE-MAPPING §4.1：把「映射成什么」与「这个决定有多可靠」拆开。
    # relation 表示 Garmin 能在多大程度上表达训记动作；ALIAS 属于 match_basis，不是 relation 取值。
    relation: Mapped[str | None] = mapped_column(String(16))
    match_basis: Mapped[str | None] = mapped_column(String(32))
    unmapped_reason: Mapped[str | None] = mapped_column(String(32))
```

三列均 **nullable**（存量行先留空，由回填补齐）。

### 2. 迁移 `a9b0c1d2e3f4_exercise_mapping_relation.py`

- `down_revision = "f8a9b0c1d2e3"`、`revision = "a9b0c1d2e3f4"`
- `upgrade()`：`op.add_column` 三列（`sa.String(16/32/32)`，`nullable=True`）
- `downgrade()`：`op.drop_column` 三列
- **纯 schema 迁移，不在迁移里跑回填逻辑**（回填是幂等的应用侧操作，可重复执行）
- 文件头写标准 revision 注释，风格照抄 `f8a9b0c1d2e3_lateral_raise_verified.py`

### 3. `exercise_mapping_relation.py`（新服务）

模块常量（值域必须与 ADR §4.1 一致）：

```python
RELATION_EXACT = "EXACT"
RELATION_SIMILAR = "SIMILAR"
RELATION_CATEGORY = "CATEGORY"
RELATION_UNMAPPED = "UNMAPPED"
RELATIONS = (RELATION_EXACT, RELATION_SIMILAR, RELATION_CATEGORY, RELATION_UNMAPPED)

MATCH_BASIS_VALUES = ("same_name", "alias", "translation", "semantic_review", "rule_features", "other")

UNMAPPED_REASON_VALUES = ("no_equivalent", "no_safe_category", "ambiguous", "other")

# 人工确认过、但目标只是大类通用条目的 seed（ADR §4.1：手工结论优先于机械判据）
SEED_GENERIC_TARGETS: dict[str, str] = {
    "器械推胸": "Garmin 无坐姿推胸机条目，用通用 Bench Press 表达（大类映射）",
}
```

#### 3.1 纯函数 `classify_relation(row) -> tuple[str | None, str | None, str | None]`

签名按「只依赖传入对象的属性」设计，便于测试：

```python
def classify_relation(row: Any) -> tuple[str | None, str | None, str | None]:
    """返回 (relation, match_basis, unmapped_reason)。

    判定顺序（严格按此实现，不要自行调整）：

    1. status == "not_applicable"
       → (None, None, None)
       这些是产品定义上不写入力量 Workout 的动作（拉伸/有氧），**不是 UNMAPPED**，
       不参与 relation 分类（ADR §4.2）。

    2. garmin_exercise_name 为空
       → (UNMAPPED, None, "no_equivalent")

    3. source == "seed"（16 条人工确认）
       → name in SEED_GENERIC_TARGETS 时 (CATEGORY, "semantic_review", None)
       → 否则 (EXACT, "semantic_review", None)

    4. garmin_exercise_name == garmin_category（目标就是大类通用条目）
       → (CATEGORY, <按 6 的规则>, None)

    5. source 或人工来源（source == "manual"）
       → (EXACT, "semantic_review", None)

    6. 其余（auto/llm 生成的自动映射）按 ADR §10.1 判据：
       tokens = extract_tokens(name)
       postures = [p for p in tokens["postures"] if p]
       display_norm = _norm(garmin_display_name or "")
       posture_mismatch = bool(postures) and any(
           _norm(p) not in display_norm for p in postures
       )
       is_similar = (
           equipment_mismatch_note(name, garmin_display_name) is not None
           or _qualifier_penalty(name, display_norm) < 0
           or posture_mismatch
       )
       → (SIMILAR if is_similar else EXACT, "rule_features", None)
    """
```

**两个必须避开的实现陷阱（ADR §10.1 已记录，均已实测）**：

1. `_qualifier_penalty()` 第二个参数是 `name_norm`，必须传 `_norm(garmin_display_name)`。
   传原始显示名时，因大小写与连字符差异，全部限定词漏判（同一行传原文得 `0`、传 `_norm()` 得 `-20`）。
2. **不能用「`_posture_bonus()` 是否触发 +40」反推姿态不符**。该函数在 `postures` 为空时返回 `0`
   且不触发 +40，而「哑铃卧推」「深蹲」本来就没有姿态词，按此反推会把它们全部误判 `SIMILAR`。
   必须先用 `bool(postures)` 作前提。

#### 3.2 `backfill_relations(session) -> dict`

```python
def backfill_relations(session: Session) -> dict:
    """为 relation 为空的行回填分类。幂等，只处理 relation IS NULL 的行。

    不覆盖人工已设置的值（ADR §10.1 补充约定）。
    返回结构化报告（见下），供迁移与验收核对。
    """
```

报告字段：

```python
{
  "scanned": int,          # 本次扫描的 relation IS NULL 的行数
  "updated": int,          # 实际写入的行数
  "skipped_not_applicable": int,   # 正常排除，不分类
  "by_relation": {"EXACT": n, "SIMILAR": n, "CATEGORY": n, "UNMAPPED": n},
  "by_status": {"active": n, "draft": n, "disabled": n},
  "active_similar": [ {"xunji_name": str, "garmin_display_name": str|None,
                       "has_equipment_note": bool},
                      ... 最多 100 条 ],
  "changed_values": [...],   # 若再跑一次，updated 必须为 0
}
```

**幂等要求**：`relation` 已有值的行一律跳过；连续执行两次，第二次 `updated == 0`。

**不得**在回填时修改 `status / confidence / mapping_version / verified_level`。

### 4. `api/exercise_mappings.py` 加端点

**注册位置**：与其它固定路径一起，放在 `/{mapping_id}` **之前**（文件顶部注释已写明这个约定）。

```python
@router.post("/backfill-relations")
def post_backfill_relations(session: Session = Depends(get_session)) -> dict:
    """按 ADR §10.1 回填 relation/match_basis/unmapped_reason（幂等，只处理空值）。"""
    return relation_svc.backfill_relations(session)
```

无请求体。import 风格沿用该文件现有的 `from app.services import ... as ..._svc` 写法。

### 5. `tests/test_exercise_mapping_relation.py`（新，≥16 例）

用 `SimpleNamespace` 造 row，**不查库**，纯测 `classify_relation`：

**正常排除（2 例）**
1. `test_not_applicable_yields_none` —— `status='not_applicable'` → `(None, None, None)`
2. `test_not_applicable_never_unmapped` —— 即便 `garmin_exercise_name` 为空也不得返回 `UNMAPPED`

**UNMAPPED（2 例）**
3. `test_empty_target_is_unmapped` —— `status='draft'` 且 `garmin_exercise_name=None`
   → `(UNMAPPED, None, 'no_equivalent')`
4. `test_unmapped_reason_in_allowed_values`

**seed 与人工（3 例）**
5. `test_seed_is_exact` —— `source='seed'`、具体目标 → `(EXACT, 'semantic_review', None)`
6. `test_seed_generic_target_is_category` —— `source='seed'`、`xunji_name='器械推胸'`
   → `relation == CATEGORY`
7. `test_manual_source_is_exact` —— `source='manual'` → `(EXACT, 'semantic_review', None)`

**大类目标（1 例）**
8. `test_generic_target_is_category` —— `garmin_exercise_name == garmin_category`（如 `CURL/CURL`）
   → `relation == CATEGORY`

**自动映射的 SIMILAR 判据（6 例，逐条对应 ADR §10.1 与两个陷阱）**
9. `test_equipment_mismatch_is_similar` —— `下斜杠铃卧推` → `Decline Dumbbell Bench Press`
   → `SIMILAR`
10. `test_qualifier_mismatch_is_similar` —— `器械耸肩` → `Behind-the-Back Smith Machine Shrug`
    → `SIMILAR`
11. `test_posture_mismatch_is_similar` —— `上斜哑铃卧推` → `Dumbbell Bench Press` → `SIMILAR`
12. **`test_no_posture_words_is_not_similar`** —— `哑铃卧推` → `Dumbbell Bench Press`
    → **`EXACT`**（这条守的是 ADR 记录的第一个陷阱：无姿态词不得误判）
13. `test_clean_match_is_exact` —— `绳索夹胸` → `Cable Crossover` → `EXACT`
14. `test_alias_never_appears_in_relation` —— 遍历全部常量断言 `"ALIAS" not in RELATIONS`

**回填幂等（3 例，走 session 夹具）**
15. `test_backfill_is_idempotent` —— 连跑两次，第二次 `updated == 0`
16. `test_backfill_does_not_touch_existing_relation` —— 预先给某行写 `relation='SIMILAR'`，
    回填后仍为 `SIMILAR`
17. `test_backfill_does_not_change_status_or_confidence` —— 回填前后
    `status / confidence / mapping_version / verified_level` 全部不变

**报告字段（2 例）**
18. `test_report_counts_consistent` —— `updated == by_relation 各项之和`
19. `test_report_lists_active_similar` —— 造一条 active+SIMILAR，报告 `active_similar` 含它

### 6. `tests/test_alembic_relation_migration.py`（新，≥3 例）

1. `test_single_head` —— `ScriptDirectory.get_heads()` 长度为 1 且等于 `a9b0c1d2e3f4`
2. `test_down_revision_chain` —— 该 revision 的 `down_revision == 'f8a9b0c1d2e3'`
3. `test_upgrade_adds_three_nullable_columns` —— 用 `Base.metadata` 断言三列存在且 `nullable=True`
   （不跑真实 DB 迁移，只断言模型与 revision 定义一致）

## 自报告要求（交付时必须给出）

1. 改动文件清单（对照预算 6 个），每个文件改动行数与函数名。
2. **`classify_relation` 的分支表**：逐条列出判定顺序与返回三元组。
3. **9 个样例的实测分类结果**（用真实数据跑，给出 `xunji_name → garmin_display_name → relation/match_basis`）：
   `哑铃卧推 / 下斜杠铃卧推 / 器械耸肩 / 上斜哑铃卧推 / 绳索夹胸 / 吊环弯举 / 器械推胸 / 腿部拉伸 / TRX-后束飞鸟`
4. **全量回填的预测分布**：在本地把 1091 行按 `classify_relation` 跑一遍，
   给 `by_relation / by_status / active_similar 条数`（**不要写死，按实跑结果填**）。
5. 设计取舍：
   - 为什么 `not_applicable` 不归入 `UNMAPPED`（ADR §4.2）
   - 为什么迁移里不跑回填逻辑
   - 为什么 `SEED_GENERIC_TARGETS` 要人工列而不是靠 `exercise_name == category` 自动判断
   - 三个陷阱分别对应哪条测试
6. 确认清单：
   - 未跑 pytest
   - 未执行 git
   - 未改 `.env` 系列
   - 未改 `exercise_mapping_candidates.py` / `exercise_mapping.py` / `exercise_mapping_batch.py` /
     `garmin_plan_sync.py` / `garmin_workout_mapper.py` / 任何前端 / 任何既有测试文件
   - 文件无 BOM、UTF-8
7. 行为自检清单：
   - [ ] `RELATIONS` 里没有 `ALIAS`
   - [ ] `not_applicable` → 三元组全为 None，且不落 `UNMAPPED`
   - [ ] 无姿态词的动作（哑铃卧推）判为 `EXACT` 而非 `SIMILAR`
   - [ ] `_qualifier_penalty` 收到的是 `_norm()` 后的串
   - [ ] 回填幂等，且不动 `status/confidence/mapping_version/verified_level`
   - [ ] 迁移单 head，`down_revision` 正确
   - [ ] 新端点注册在 `/{mapping_id}` 之前

## 明确不做

- 不改 `confidence` 的语义、不改 `batch_activate` 的筛选条件（下一片 ADR-P0-5 做）
- 不改 `load_all_mappings`、不改 mapper、不改同步链路（下一片 ADR-P0-2 / P0-3）
- 不在迁移里写数据回填 SQL（回填走应用侧幂等端点）
- 不动前端、不动 LLM 兜底、不动 L2 探针
