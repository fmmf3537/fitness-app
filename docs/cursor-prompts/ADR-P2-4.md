# ADR-P2-4 审核 prompt 加政策约束 + 补「侧躺腿外展」词条

> 你是本仓库的资深后端工程师（FastAPI + SQLAlchemy 2.x + pytest）。
> 本提示词是唯一任务来源：只按本提示词写代码，**不跑任何验收命令（pytest 一律不跑）**，**不执行任何 git 命令**。
> 红线：禁整文件重写（外科式最小修改）；所有写出的文件必须无 BOM、UTF-8；不得修改 `.env` / `.env.*`；不得删除任何既有文件；不得改动本提示词文件预算之外的任何文件。

## 需求背景

线上首跑 AI 只读审核（40 条）后，人审发现两个问题：

### ① AI 把我们**既定的产品策略**当成"错误"来纠正

5 条 `better_candidate` 里有 2 条属于这类：

| 动作 | 当前（我们的选择） | AI 建议 | AI 理由 |
|---|---|---|---|
| 下斜史密斯机卧推 | `DECLINE_DUMBBELL_BENCH_PRESS`（保姿态） | `SMITH_MACHINE_BENCH_PRESS`（保器械） | 「应优先史密斯器械一致，下斜角度无对应项可舍弃」 |
| 单手绳索臂屈伸 | `SINGLE_ARM_DUMBBELL_OVERHEAD_TRICEPS_EXTENSION`（保单侧） | `CABLE_OVERHEAD_TRICEPS_EXTENSION`（保器械） | 「原映射为哑铃，器械不符」 |

**本系统的既定策略是「姿态优先于器械」**（V6-9f 定稿：姿态匹配 +20/个、缺失 −20/个、全命中再 +40；
器械不符已经由 `relation=SIMILAR` + `note='器械不符…'` 显式标注）。
AI 不知道这个策略，于是把我们的刻意取舍标成"更优"，产生噪音。

### ② AI 找出了我们词表的**真缺口**（这条要修）

| 动作 | 当前 | AI 建议 | 结论 |
|---|---|---|---|
| 弹力带侧躺腿外展 | `BANDED_EXERCISES/LEG_ABDUCTION` | `HIP_STABILITY/BAND_SIDE_LYING_LEG_RAISE`（Band Side-lying Leg Raise） | **真改进** |

根因不是打分不够高，是**结构上永远找不到**：

```
tokens: equipment=[banded]  postures=[side lying]  movements=[abduction]  part=腿
候选池含 HIP_STABILITY ✓
"Band Side-lying Leg Raise" 含 "band" ✓ 含 "side lying" ✓
但名字里**没有 "abduction"** ✗ → 运动词根不匹配 → 从来不是候选
```

Garmin 把这类侧躺抬腿动作叫 `Leg Raise` 而不是 `Abduction`。
`外展 → abduction` 这个映射对它不成立，需要一个**复合词条**覆盖。

## 已核实的关键事实（实读代码，可直接采信）

- `backend/app/services/exercise_tokens.py`
  - `MOVEMENT_TOKENS` 里 `"外展": "abduction"`、`"抬腿": "leg raise"`
  - `MOVEMENT_KEYS_BY_LENGTH = sorted(MOVEMENT_TOKENS, key=len, reverse=True)`（**长键优先**）
  - `PART_TO_GARMIN_CATEGORIES["腿"]` 已包含 `HIP_STABILITY` 与 `LEG_RAISE`
- `backend/app/services/exercise_mapping_candidates.py`
  - `extract_tokens("弹力带侧躺腿外展")` →
    `{'equipment': ['banded'], 'postures': ['side lying'], 'movements': ['abduction'], 'part': '腿'}`
  - `_norm("Band Side-lying Leg Raise")` = `"bandsidelyinglegraise"`（含 `legraise` 与 `sidelying`）
  - 打分：20 + 器械 40 + 姿态(命中 +20 / 缺失 −20 / 全命中再 +40) + 限定词扣分 + 完全相等 20
- `backend/app/services/exercise_mapping_review.py` 的 `build_prompt(items)` 构造 system + user messages；
  首跑 40 条统计：`current_ok 35 / better_candidate 5 / suspected_error 0 / likely_unmapped 0 / needs_human 0`
- `backend/tests/test_golden_mapping_regressions.py` 已有多条 golden 断言，
  其中 `test_leg_abduction_not_shoulder_rotation` 断言 `"弹力带-腿外展"` rank-1 含 `LEG` 或 `HIP`
  且不含 `EXTERNAL_ROTATION` —— **这条不得回退**
- Alembic 当前单 head：`d2e3f4a5b6c7`（本片**不加迁移**）

## 文件预算（共 4 个，不得越界）

改 3：
1. `backend/app/services/exercise_mapping_review.py`（system 段加政策约束）
2. `backend/app/services/exercise_tokens.py`（补复合词条）
3. `backend/tests/test_golden_mapping_regressions.py`（补 2 条 golden）

新增 1：
4. `backend/tests/test_review_policy_prompt.py`

**禁止修改**：`exercise_mapping_candidates.py`、`exercise_mapping.py`、`exercise_mapping_batch.py`、
`exercise_mapping_relation.py`、任何迁移、任何前端、`.env`、其它既有测试文件。

## 开发内容

### 1. `exercise_mapping_review.py`：system 段加政策约束

在 `build_prompt` 的 system 文本中追加一段（措辞照抄，位置放在"你是审核员"之后、
输出格式要求之前）：

```text
【本系统的既定策略，请勿试图纠正】
1. 姿态优先于器械：当 Garmin 没有「同器械 + 同姿态」的条目时，本系统**有意保留姿态**
   （上斜/下斜/侧躺/坐姿/俯身/支撑/单侧等）而舍弃器械，而不是反过来。
   器械不符已经由 relation=SIMILAR 与 note='器械不符…' 显式标注，
   **不要仅因为「器械不一致」就判为 better_candidate**。
2. 只有当建议项比当前项**同时匹配更多维度**（器械 + 姿态 + 握法 + 单双侧）时，
   才判为 better_candidate；若只是「换一个维度对、丢掉另一个维度」，属于等价取舍，
   应判 current_ok。
3. 判 better_candidate 时，reason 必须明确写出**当前项丢了什么维度、建议项丢了什么维度**，
   让人类判断这个取舍是否值得。
4. 允许并鼓励判 likely_unmapped 与 needs_human —— 「不知道」比「猜一个」更有价值。
```

同时在 user 段每条 ahead 增加当前项的 `relation` 与 `note`（若已有则确认字段存在；
**没有就加**），让 AI 能看到"这是已知的有损映射"。

### 2. `exercise_tokens.py`：补复合词条

在 `MOVEMENT_TOKENS` 中追加（长键优先，会自动覆盖 `外展 → abduction` 的组合场景）：

```python
    # Garmin 把「侧躺/侧卧抬腿」类动作登记为 Leg Raise 而不是 Abduction，
    # 只靠「外展 → abduction」永远命中不到 Band Side-lying Leg Raise（2026-11-13
    # AI 审核发现：弹力带侧躺腿外展 被映射成 Banded Leg Abduction，丢了"侧躺"）。
    "侧躺腿外展": "leg raise",
    "侧卧腿外展": "leg raise",
    "侧躺抬腿": "leg raise",
    "侧卧抬腿": "leg raise",
```

**约束**：加了之后必须验证
- `弹力带侧躺腿外展` 的候选里出现 `BAND_SIDE_LYING_LEG_RAISE`（新能力）
- `弹力带-腿外展`（无"侧躺"）**仍然** rank-1 是 `LEG_ABDUCTION` 系列，golden 断言不回退
- 若有任何既有测试因此失败，**不要改那些测试**，而是把词条收窄（例如只保留
  `侧躺腿外展` / `侧卧腿外展`，去掉 `抬腿` 两条），并在报告里说明原因

### 3. `test_golden_mapping_regressions.py`：补 2 条

1. `test_case6_side_lying_leg_abduction_uses_leg_raise` ——
   `"弹力带侧躺腿外展"` 的候选里**必须**出现 `BAND_SIDE_LYING_LEG_RAISE`
   （断言"存在该候选"而非"rank-1 是它"，避免被同名条目排序影响）
2. `test_case6_regression_plain_leg_abduction_unchanged` ——
   `"弹力带-腿外展"` rank-1 仍含 `LEG`，且**不含** `SIDE_LYING`
   （证明复合词条没有污染无姿态的同类动作）

并在文件头注释的"五类"列表后补一行说明第 6 条来自 AI 审核的发现。

### 4. `test_review_policy_prompt.py`（新，≥5 例）

1. `test_system_prompt_contains_policy` —— `build_prompt([...])` 的第一条 message
   的 content 含「姿态优先于器械」与「不要仅因为「器械不一致」」
2. `test_system_prompt_requires_tradeoff_reason` —— 含「当前项丢了什么维度」
3. `test_system_prompt_encourages_unknown` —— 含「允许并鼓励判 likely_unmapped」
4. `test_user_prompt_includes_relation_and_note` —— 构造一条带
   `relation='SIMILAR'`、`note='器械不符：…'` 的 item，断言 user 段文本包含
   这两项内容
5. `test_prompt_lists_only_catalog_candidates` —— 断言 user 段里出现的
   `exerciseName` 都能在 `garminconnect.exercises.EXERCISES` 里找到
   （防止把不存在的组合喂给模型）

## 自报告要求（交付时必须给出）

1. 改动文件清单（对照预算 4 个），每个文件改动行数与函数名。
2. **`build_prompt` 的 system 段全文**（贴出来，便于审核措辞）。
3. **词条影响的实测对照**：

   | 动作 | 改前 rank-1 | 改后 rank-1 | 改后候选里是否含 BAND_SIDE_LYING_LEG_RAISE |
   |---|---|---|---|
   | 弹力带侧躺腿外展 | ? | ? | ? |
   | 弹力带-腿外展 | ? | ? | ? |
   | 弹力带侧躺抬腿（若存在该动作名） | ? | ? | ? |

4. **既有 golden 是否全部未回退**（列出 `test_golden_mapping_regressions.py` 的通过数）。
5. 设计取舍：
   - 为什么用复合词条而不是把 `外展` 改成 `leg raise`（后者会破坏所有 abduction 映射）
   - 为什么 golden 断言「候选里存在」而不是「rank-1 是它」
   - 为什么政策要写进 system 而不是 user（每条 item 重复会浪费 token）
   - 如果加了 `抬腿` 词条导致既有测试失败，说明收窄依据
6. 确认清单：
   - 未跑 pytest
   - 未执行 git
   - 未改 `.env` 系列
   - 未改 `exercise_mapping_candidates.py` / `exercise_mapping.py` / batch / relation /
     迁移 / 前端 / 其它既有测试文件
   - 文件无 BOM、UTF-8
7. 行为自检清单：
   - [ ] system 段含「姿态优先于器械」政策
   - [ ] user 段含当前项的 `relation` 与 `note`
   - [ ] user 段的候选全部来自真实目录
   - [ ] `弹力带侧躺腿外展` 能找到 `BAND_SIDE_LYING_LEG_RAISE`
   - [ ] `弹力带-腿外展` 行为不变（golden 不回退）
   - [ ] 未改动任何映射状态或打分逻辑

## 明确不做

- 不改候选生成/打分逻辑（只补词条，不动 `_posture_bonus` / `_qualifier_penalty` / 阈值）
- 不自动采纳任何 AI 建议（ADR §11：AI 只读）
- 不跑全量审核（成本与质量待人工评估后再决定）
- 不改前端
