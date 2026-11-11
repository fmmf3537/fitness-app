# 训记 ↔ Garmin 动作匹配方案

> 状态：**设计稿，未实施**
> 日期：2026-11-11
> 适用范围：训记训练计划 → Garmin Connect Workout 写入链路
> 前置阅读：`docs/GARMIN-PLAN-SYNC-MIGRATION.md` §8.1（动作白名单）、§8.2（组次转换）

## 1. 结论摘要

当前 `EXERCISE_WHITELIST` 只有 **16 个**动作，而训记标准动作表有 **1091 个**、Garmin 目录有
**1527 个**。计划一旦换动作就触发 `PLAN_MAPPING_UNSUPPORTED`（422）整日禁止同步。

方案：**不追求全量映射**，改为「按需采集 → 自动候选 → 人工复核 → 落库生效 → 分级验证」。
核心是把硬编码字典换成 **DB 驱动的映射表 + 复核 UI**，让新动作无需改代码即可开通。

关键结论（已实测/已确认）：

- **重量语义已对齐，不需要换算**：`total`（杠铃/器械）与 `per_hand`（哑铃）两个口径，
  训记与 Garmin **都按原值一致**。P3 远端 `BARBELL_BACK_SQUAT weightValue=67.5`、
  P2 远端 `DUMBBELL_BENCH_PRESS weightValue=15.0/17.5/20.0/22.5` 均为训记原值，
  且用户已目视确认 Connect 与 FR955 显示正确。
- **`bodyweight` 已正确**：`weightValue: null`，不伪造 0。
- **`assisted`（`exetype=help`）未支持**：mapper 完全不读 `exetype`。这是唯一遗留语义缺口，
  当前 16 个白名单动作里没有辅助类动作，故不影响现状，但新增时必须显式拦截。

## 2. 现状实测

| 项 | 数量 | 位置 |
|---|---|---|
| 训记标准动作表 | **1091** | `backend/app/data/xunji_movements.json` |
| Garmin 动作目录 | **1527 / 47 category** | `garminconnect/exercises.py`（**离线静态表**，`EXERCISES` / `BY_NAME` / `CATEGORIES` / `resolve()` / `find()`） |
| 代码内映射 | **16**（p0:1 / p2:8 / p3:7） | `garmin_workout_mapper.EXERCISE_WHITELIST` |
| 覆盖的 Garmin category | **9 / 47** | 同上 |
| 当前计划实际动作 | 15（全部已覆盖） | `outputs/garmin_p0/movement_coverage.md` |
| 部位分类器 | 7 类 | `stats.classify_part` |
| 已有分析脚本 | 2 个（只读 SQLite） | `scripts/analyze_garmin_movement_coverage.py` / `analyze_garmin_exercise_mappings.py` |

映射条目当前结构（**无 `weight_strategy`**）：

```python
{"display_name": "Dumbbell Bench Press", "category": "BENCH_PRESS",
 "exerciseName": "DUMBBELL_BENCH_PRESS", "support_level": "p2_verified"}
```

## 3. "找不到 / 找错了" 拆成三个独立问题

| # | 问题 | 表现 | 现状 | 优先级 |
|---|---|---|---|---|
| **P1** | 找不到（未映射） | 422 + 未支持清单，整日禁止同步 | ✅ 有严格白名单，但只覆盖 16 个 | **高** |
| **P2** | 找错了（映射错动作） | 同步成功但 Garmin/FR955 显示别的动作 | ⚠️ 仅靠人工 P2/P3 目视，无结构化校验 | **高** |
| **P3** | 重量语义错 | 动作对但重量显示错 | ✅ 已确认双边一致（total / per_hand 均原值） | **已解决** |
| **P4** | 辅助动作语义反 | `exetype=help` 的辅助重量被当成负荷 | ❌ `exetype` 未被 mapper 读取 | 中（当前无此类动作） |

## 4. 总体架构

```
① 需求采集   从计划缓存提取"计划里实际出现的动作"（不追求 1091 全覆盖）
      ↓
② 候选生成   4 级窄化：部位 → 器械 → 动作模式 → Garmin 目录模糊匹配
             覆盖不到的交给 LLM（DeepSeek）从该部位的 category 子集里选
      ↓
③ 人工复核   网页 UI：候选 + 置信度 + 重量语义 → 采纳 / 换一个 / 忽略
             （复用 V5-5 教练须知的 draft 复核模式）
      ↓
④ 落库生效   mapper 改为从 DB 读映射（保留硬编码作为 seed 与兜底）
             → 新动作开通无需改代码、无需发版
      ↓
⑤ 分级验证   L1 目录校验（全量、离线、免费）
             L2 真实创建抽样（**按 category 抽，不按动作抽**）
             L3 FR955 目视（只验实际在用的）
```

**为什么 L2 按 category 抽样**：Garmin 的写入行为主要由 `category + exerciseName` 决定，
同 category 走同一创建路径。47 个 category 各验 1-2 个代表动作即可，把验证量从
"上千次写入"降到 "60-90 次"。

## 5. 数据模型

### 5.1 `exercise_mapping`（正式映射）

```sql
exercise_mapping(
    id                PK,
    xunji_name        TEXT NOT NULL,          -- 训记标准中文名（对齐 xunji_movements.json）
    garmin_category   VARCHAR(64) NOT NULL,   -- 47 个之一（exercises.CATEGORIES）
    garmin_exercise_name VARCHAR(128),        -- 允许空串（Garmin 只显示 category 名）
    garmin_display_name  VARCHAR(200),        -- 预览展示用
    weight_strategy   VARCHAR(32) NOT NULL,   -- total / per_hand / bodyweight / assisted
    status            VARCHAR(20) DEFAULT 'pending',   -- pending / active / disabled
    confidence        VARCHAR(10),            -- high / medium / low
    source            VARCHAR(20),            -- seed / auto / llm / manual
    verified_level    VARCHAR(20),            -- catalog / created / displayed
    verified_at       DATETIME,
    note              TEXT,
    created_at, updated_at,
    UNIQUE(xunji_name)
)
```

**`weight_strategy` 的定位**：不是换算系数，而是**语义声明 + 安全闸门**。
- `total` / `per_hand` → 原值写入（已确认双边一致）
- `bodyweight` → `weightValue=null`
- `assisted` → **blocked**，未验证前禁止同步（当前保留为显式不支持位）

### 5.2 `exercise_mapping_candidate`（待复核候选）

```sql
exercise_mapping_candidate(
    id                PK,
    xunji_name        TEXT NOT NULL,
    garmin_category   VARCHAR(64) NOT NULL,
    garmin_exercise_name VARCHAR(128),
    garmin_display_name  VARCHAR(200),
    confidence        VARCHAR(10),
    reason            TEXT,                   -- 命中依据：部位/器械/动作模式/LLM 说明
    status            VARCHAR(20) DEFAULT 'pending',   -- pending / accepted / rejected
    created_at, resolved_at
)
```

### 5.3 迁移兼容

现有 16 条硬编码 → 一次性 seed 进 `exercise_mapping`：
- `status='active'`、`verified_level='displayed'`（已过 P2/P3 目视）
- `source='seed'`、`weight_strategy` 按器械推断（杠铃/器械→`total`，哑铃→`per_hand`）
- 保留 `EXERCISE_WHITELIST` 作为 fallback（DB 未初始化时不至于全面 422）

## 6. 候选生成（4 级窄化）

### 第 1 级：部位 → Garmin category 子集

复用 `stats.classify_part()`（7 类），配一张**一次性人工表**（47 条）：

```python
PART_TO_GARMIN_CATEGORIES = {
    "胸":   ["BENCH_PRESS", "FLYE", "PUSH_UP", "CABLE", "PLYO"],
    "背":   ["ROW", "PULL_UP", "LAT_PULLDOWN", "SHRUG", "OLYMPIC_LIFT"],
    "腿":   ["SQUAT", "DEADLIFT", "LUNGE", "LEG_PRESS", "LEG_CURL",
             "LEG_RAISE", "HIP_RAISE", "PLYO"],
    "肩":   ["SHOULDER_PRESS", "LATERAL_RAISE", "SHOULDER_STABILITY", "FLYE"],
    "臂":   ["TRICEPS_EXTENSION", "CURL", "BICEPS_CURL"],
    "核心": ["CORE", "CRUNCH", "PLANK", "SIT_UP"],
    "有氧": ["RUN", "RUN_INDOOR", "INDOOR_BIKE", "CARDIO"],
}
```

### 第 2 级：器械识别（中文 → 英文词根）

```python
EQUIPMENT_TOKENS = {
    "杠铃": "barbell", "哑铃": "dumbbell", "史密斯": "smith machine",
    "绳索": "cable", "龙门": "cable", "器械": "machine", "坐姿器械": "machine",
    "壶铃": "kettlebell", "弹力带": "banded", "药球": "medicine ball",
    "自重": "", "徒手": "",
}
```

### 第 3 级：动作模式识别（中文 → Garmin 英文动作词）

```python
MOVEMENT_TOKENS = {
    "卧推": "bench press", "飞鸟": "flye", "夹胸": "flye",
    "深蹲": "squat", "硬拉": "deadlift", "箭步蹲": "lunge", "腿举": "leg press",
    "划船": "row", "下拉": "pulldown", "引体": "pull up",
    "推举": "shoulder press", "推肩": "shoulder press",
    "侧平举": "lateral raise", "前平举": "front raise",
    "弯举": "curl", "臂屈伸": "extension", "下压": "pushdown",
    "卷腹": "crunch", "转体": "twist", "平板支撑": "plank",
}
```

### 第 4 级：目录内模糊匹配

组合成候选英文串（如 `"dumbbell bench press"`），在**第 1 级已缩窄的 category 子集**内，
用 `garminconnect.exercises.find(term)` 或对 `BY_NAME` 做相似度打分，取 top 1-3。

### 置信度分级

| 级别 | 条件 |
|---|---|
| `high` | 器械 + 动作模式都命中，且 catalog 内唯一匹配 |
| `medium` | 只命中动作模式，或命中 2-3 个候选 |
| `low` | 仅靠部位兜底，或 LLM 判断 |

### LLM 兜底（只处理 medium / low）

- 每批 20 个动作 + **该动作所属部位的 category 候选列表**（不送全部 1527）
- 要求严格 JSON 输出：`{xunji_name, category, exerciseName, confidence, reason}`
- 复用 `adapters/llm.chat`，`purpose='exercise_mapping'` 记账
- 落库前用 `exercises.resolve()` 校验存在性，不存在自动降级 `low`
- 预估成本：150 个动作 ≈ **¥0.3**（DeepSeek，一次性）

## 7. 复核 UI（复用 V5-5 模式）

新增 `/exercise-mappings` 页面，结构与 `CoachPreferencesPage` 同构：

```
[待复核候选]  N 条
  ├ 训记名：哑铃卧推
  ├ 建议：BENCH_PRESS / DUMBBELL_BENCH_PRESS
  │       （Dumbbell Bench Press）
  ├ 置信度：high    依据：器械"哑铃" + 动作模式"卧推" 唯一命中
  ├ 重量语义：[单只 ▾]        ← 默认按器械推断，可改
  └ [采纳]  [换一个候选 ▾]  [忽略]

[已生效映射]  M 条（搜索 / 编辑 / 停用）
```

重量语义默认推断：

| 器械 | 默认 |
|---|---|
| 杠铃 / 器械 / 史密斯 / 绳索 | `total` |
| 哑铃 | `per_hand` |
| 自重 | `bodyweight` |
| 辅助类（引体/双杠辅助） | `assisted`（**默认禁止同步**） |

## 8. mapper 改造（保留纯函数性质）

```python
# 现在
mapping = EXERCISE_WHITELIST.get(name)

# 改成：映射表由调用方查好并注入
def map_plan_day(plan_day, *, mappings: dict | None = None, plan_ref=None):
    mappings = mappings if mappings is not None else EXERCISE_WHITELIST
    ...
```

**关键**：`garmin_workout_mapper` 现在不碰 DB、不碰文件、不碰网络（docstring 明确声明）。
改造必须保持这个性质——查库在 `garmin_plan_sync` 层做，纯函数只接收映射字典。
现有 561 行 mapper 测试可继续用注入方式跑，不破坏。

## 9. 分级验证

| 级 | 做什么 | 成本 | 覆盖范围 | 落库标记 |
|---|---|---|---|---|
| **L1 `catalog`** | `exercises.resolve(display_name)` 或按 `(category, exerciseName)` 命中 | 零（离线） | 全量 | 可 active |
| **L2 `created`** | 真实创建 1 组测试 Workout，回读确认 `exerciseName` 未被规范化掉 | 每 category 1-2 次写入 | ~60-90 次 | 可 active（高可信） |
| **L3 `displayed`** | 用户目视 Connect + FR955 | 人工 | 只验实际在用的 | 最高 |

**L2 的必要性**（来自 §8.1 已记录的真实坑）：Garmin 创建后会把通用
`Bench Press` 与 `Lateral Raise` 的 `exerciseName` **规范化为空串**，`category` 保持不变。
这类行为**目录校验查不出来**，只能靠真实创建 + 回读发现。

## 10. 切片拆分

| 切片 | 内容 | 文件预算 | 依赖 |
|---|---|---|---|
| **V6-1** | 2 张新表 + Alembic 迁移 + seed 现有 16 条 + `map_plan_day` 支持注入（行为不变） | 5 | — |
| **V6-2** | 候选生成器（4 级窄化，纯函数）+ 单测 + 1091 全量覆盖率报告 | 3 | V6-1 |
| **V6-7** | L1 目录校验批处理 + 覆盖率 API/看板 | 3 | V6-2 |
| **V6-4** | 复核 API（列表 / 采纳 / 拒绝 / 改重量语义）+ 落库生效 | 4 | V6-1 |
| **V6-5** | 复核 UI 页面（复用 V5-5 结构 + `ConfirmDialog`） | 4 | V6-4 |
| **V6-6** | 计划预览接入 DB 映射；422 时返回候选提示；预览展示重量口径 | 3 | V6-4 |
| **V6-3** | LLM 兜底候选（批量 + JSON 校验 + 成本记账） | 3 | V6-2 |
| **V6-8** | L2 抽样验证脚本（按 category 选代表动作，真实创建 + 回读） | 2 | V6-7 |

**推荐顺序**：V6-1 → V6-2 → **V6-7（决策点）** → V6-4 → V6-5 → V6-6 → V6-3 → V6-8

**V6-7 是决策点**：跑完 1091 全量覆盖率才知道 4 级窄化能自动覆盖多少。
若 ≥70%，V6-3（LLM 兜底）可延后或不做。

## 11. 风险与对策

| 风险 | 对策 |
|---|---|
| LLM 给出的 category/exerciseName 不存在 | 落库前 `exercises.resolve()` 校验；不通过自动降 `low` 并在 UI 标红 |
| 同 category 但动作选错 | 复核 UI 强制展示 Garmin 英文名 + 可切换候选列表（不只给一个） |
| 辅助动作语义反 | `weight_strategy='assisted'` 默认 `status='disabled'`，显式拦 422 |
| 映射表变大导致预览变慢 | 启动时预载进内存（1091 条约几十 KB）；按需失效刷新 |
| Garmin 改变 category 枚举 | L2 回读校验发现；`verified_level` 可降级重验 |
| 现有 15 个动作回归 | V6-1 seed 时**必须**加回归测试，断言这 15 条映射与 `support_level` 不变 |
| 破坏 mapper 纯函数性质 | V6-1 明确「查库在 sync 层、mapper 只接收注入字典」，测试仍零 DB 依赖 |

## 12. 成本

| 项 | 成本 |
|---|---|
| LLM 候选（假设 150 个走兜底） | **≈ ¥0.3**（DeepSeek 一次性） |
| L2 抽样验证（60-90 次真实写入） | 0 元，但消耗 Garmin 写入配额，需分批 + 429 冷却 |
| 开发 | 8 个切片，按现有节奏约 2-3 天 |

## 13. 已确认的决策

| # | 决策 | 结论 |
|---|---|---|
| 1 | 覆盖范围 | **按需**（只覆盖计划实际出现的动作），不做全量 1091 |
| 2 | 哑铃重量语义 | 训记 = **单只**；Garmin 显示也是**单只** → **双边一致，无需换算** |
| 3 | 复核入口 | 网页 UI（复用 V5-5 模式，手机可用） |
| 4 | L2 验证深度 | 按 category 抽 1-2 个代表动作 |
