# PRD V4 —— 点评修正与深度分析增强（2026-09-02 定稿）

> 基于 2026-09-02 代码实测分析编制。配套《PRD.md》《开发计划.md》使用。
> 状态：**已定稿**（5 项开放问题全部与用户确认完毕）

## 需求总览

| # | 需求 | 性质 | 现状根因（代码实测） |
|---|---|---|---|
| F1 | 非训记活动（羽毛球/跑步等）点评总说"最近没有记录" | Bug 修复 | `ai.py generate_session_review` 仅以训记动作名查 `query_movement_history`，garmin_only 活动无 movements → 历史恒空 |
| F2 | 引体向上等辅助动作的重量被误读为负重 | Bug 修复 | 训记原始数据 `exetype` 字段已区分（`help`=辅助 / `plus_weight`=负重），但 prompt 渲染与历史统计均未使用该语义 |
| F3 | 训练详情页点评支持追评对话，并可通过对话重新生成点评/海报/下次建议 | 新功能 | 追问组件 `ReportChatSection` 已存在（V3-8），但仅挂在 AI 报告页；详情页只有 `SessionReviewSection` 展示，无对话与再生成入口 |
| F4 | 训记每个动作的每一组匹配佳明心率的逐组分析 | 新功能 | 佳明 raw_json 内含带时间戳心率序列（`directTimestamp`+`directHeartRate`，约 2s/点）及自动识别组次（`exercise_sets`，含 startTime/duration/reps/动作类别），逐组匹配技术上可行 |
| F5 | 皮脂钳多方案测量→自动算体脂率→存入身体数据 | 新功能 | `body_metric` 已有 `bodyfat` 类型可存结果；需新增测量记录表与多公式计算 |

---

## F1 非训记活动点评无历史（Bug）

### 根因（已实测定位）

`backend/app/services/ai.py:396-402`：历史上下文只按 movements_json 中的动作名循环查
`query_movement_history`（精确名称匹配）。garmin_only 活动 movements 为空 →
prompt 中「近4周同动作历史」恒为"无数据"，AI 只能回答"最近没有该训练记录"。

### 方案

1. 新增 `query_activity_history(session, activity_type, date, weeks=N)`：
   按佳明 `activity_type`（映射到 workout.tags）查近 N 周同类活动，
   返回 {次数, 最近 K 次列表（日期/时长/平均心率/最大心率/热量）, 平均时长, 平均心率}。
2. `build_session_review_prompt` 改造：
   - 有 movements → 走现有"同动作历史"；
   - 无 movements（garmin_only）→ 注入"同类活动历史"段落，标题如「近4周同类活动（羽毛球）历史」。
3. 活动类型显示名映射表（typeKey → 中文）：badminton→羽毛球、running→跑步 等。

### 验收

- 用 2026-08 某次羽毛球 workout 重新生成点评，内容引用近 4 周真实羽毛球记录（次数、最近几次日期与心率）。
- 单元测试：构造 3 次历史羽毛球活动，断言 prompt 中含"同类活动历史"与正确次数。
- 回归：力量训练（有 movements）prompt 结构不变。

### 开放问题

- ~~Q1.1/Q1.2~~ **已确认（2026-09-02）**：近 4 周窗口 + 汇总统计 + 最近 3 次明细（日期/时长/平均与最大心率/热量）。

---

## F2 辅助重量语义修正（Bug）

### 根因（已实测定位）

训记 movements 带 `exetype` 字段，实测数据：

- `2026-08-10 引体向上 exetype="help"`，weight 75/70/65 kg → 这是**辅助重量**（助力带/器械辅助）
- `2026-07-31 引体向上 exetype="plus_weight"`，weight 80 kg → **负重**

但 `build_session_review_prompt`（ai.py:287-297）只渲染 `{weight}{unit} × {reps}`，
`query_movement_history` 的 PR/容量统计也把 weight 当负荷——辅助 75kg 被当成负重 75kg，
点评出现"你能负重 75kg 做引体"这类严重误读。

### 方案

1. **prompt 渲染加语义**：按 exetype 渲染为
   - `help` → `辅助 75kg × 7`
   - `plus_weight` → `负重 +80kg × 7`
   - 其他/空 → 维持现状
2. **有效负荷折算**（用于历史对比与 PR）：有效负荷 = 当时体重 + 负重 − 辅助。
   体重取该训练日或最近一次 `body_metric(type='weight')`；无体重记录则不折算、仅在 prompt 标注语义。
3. **历史统计分组**：`query_movement_history` 按 (动作名, exetype) 分组统计，
   PR 与容量在组内计算，避免辅助数据污染负重 PR。
4. exetype 透传：确认 `fuse.py`/xunji 适配层到 movements_json 的链路完整保留 exetype（实测已在，仅需消费端使用）。

### 验收

- 用 2026-08-10 训练重新生成点评，不再出现"负重 75kg"表述，出现"辅助 75kg"及有效负荷分析。
- 单元测试：help / plus_weight / 无 exetype 三类动作的 prompt 渲染与 PR 统计。
- 体重缺失时降级为语义标注，不报错。

### 开放问题

- ~~Q2.1~~ **已确认（2026-09-02）**：方案 B——语义标注 + 有效负荷折算（体重 + 负重 − 辅助，体重取训练日最近一次记录，缺失时降级为仅语义标注）。
- ~~Q2.2~~ **已确认**：按 `exetype` 字段通用处理，覆盖引体向上、双杠臂屈伸等所有辅助/负重类动作，不写死动作名。

---

## F3 详情页点评追评 + 对话驱动重新生成（新功能）

### 现状

- 追问对话已完整存在：`report_chat_message` 表、`services/report_chat.py`（幂等、成本护栏、
  20 条历史窗）、前端 `ReportChatSection.jsx`——但仅挂在 AI 报告页。
- 详情页 `WorkoutDetailPage` 只有 `SessionReviewSection`（展示）+ `NextAdviceSection`。
- 海报 `api/posters.py /data` 按 report_id 装配，点评的 one_liner 是海报文案来源之一。

### 方案

1. **详情页接入对话**：`SessionReviewSection` 内嵌 `ReportChatSection`（复用，报告 id 取自该 workout 的 session_review）。
2. **对话驱动重新生成**：对话区增加「根据以上讨论重新生成」按钮：
   - 后端新端点 `POST /api/ai/session_review/{workout_id}/regenerate_with_feedback`：
     将最近 N 条对话作为「用户反馈」段落注入 `build_session_review_prompt`，
     删旧报告重生成（复用 `regenerate_session_reviews` 单 workout 版）。
   - 点评重生成后，海报数据自动引用新 one_liner（无需单独重生成海报）。
   - 「重新生成下次建议」同理：对话反馈注入 `build_next_advice_prompt`。
3. 护栏：重生成按钮防抖 + 每日每 workout 重生成次数上限（如 5 次），记账照走 `llm_call`。

### 验收

- 详情页可直接追问；点击重新生成后新点评体现对话中的用户反馈（如"那天我感冒"→ 点评提及）。
- 海报预览显示新 one_liner。
- 幂等与 token 记账不重不漏。

### 开放问题

- ~~Q3.1~~ **已确认（2026-09-02）**：方案 A——显式按钮触发。对话区下方「根据以上讨论重新生成」按钮，对话注入 prompt 的"用户反馈"段；带覆盖确认提示；每 workout 每日重生成上限 5 次；海报 one_liner 随点评自动更新。
- ~~Q3.2~~ **已确认**：「重新生成下次建议」为独立按钮，仅当该 workout 已存在 next_advice 时显示。

---

## F4 逐组心率匹配（新功能）

### 数据基础（已实测确认）

佳明 `raw_json`（以 activity 632131160 为例）：

- `details.activityDetailMetrics`：1684 个采样点，含 `directTimestamp`（毫秒时间戳）与
  `directHeartRate`（bpm），约 2 秒一点 —— 完整心率时间序列。
- `exercise_sets.exerciseSets`：42 组，每组含 `startTime`、`duration`、`repetitionCount`、
  `setType`（ACTIVE/REST）、`exercises`（自动识别动作类别，如 DEADLIFT/SQUAT，多候选）。

训记侧：组次**无独立时间戳**（仅动作顺序与 `time`=组间休息秒数），
因此逐组匹配以佳明侧组次为时间锚点，训记组次按顺序对齐。

### 方案

1. **新表 `workout_set_hr`**：workout_id / movement_name / set_index /
   hr_avg / hr_max / hr_min / set_start / set_end / confidence（high/low）/ match_method。
2. **匹配引擎 `services/set_hr.py`**：
   - 从 garmin raw_json 提取 HR 序列 + ACTIVE 组次窗口；
   - 训记动作组次按全局顺序与佳明 ACTIVE 组次顺序对齐；
   - 佳明动作类别 → 训记动作名映射表（如 DEADLIFT→硬拉、SQUAT→深蹲、BENCH_PRESS→卧推）
     用于校验顺序对齐，类别不一致时降置信度并尝试局部重排；
   - 计算每组窗口内 HR 统计（组中心率均值/峰值 + 组后 30s 恢复心率可选）。
3. **展示**：详情页动作组次表每组追加"心率 均值/峰值"列（或展开行），
   低置信度组标注"~"前缀。
4. **注入点评**：session_review prompt 增加「逐组心率」摘要段（每动作：组心率均值趋势，如逐组爬升），
   供 AI 分析组间强度衰减与恢复。
5. **降级**：佳明侧无 exercise_sets（老活动/未佩戴心率设备）时该 workout 无逐组数据，UI 不显示该列。

### 验收

- 2026-08-26 力量训练：每组显示心率均值/峰值，抽 3 组手工对照佳明 Connect 曲线误差 ≤3 bpm。
- 单元测试：顺序对齐、类别校验冲突降级、无 exercise_sets 降级。
- 点评 prompt 含逐组心率摘要（抽查重新生成的点评引用该数据）。

### 开放问题

- ~~Q4.1~~ **已确认（2026-09-02）**：增强版——每组输出组中平均/峰值心率 + 组后 30 秒恢复心率（利用佳明 REST 窗口计算回落幅度）。
- ~~Q4.2~~ **已确认**：历史存量 workout 全量回填逐组心率（独立手动触发脚本，不进每日同步链路）。

---

## F5 皮脂钳体脂率测量（新功能）

### 方案

1. **新表 `skinfold_record`**：date / method / sites_json（各部位 mm 值）/
   bodyfat_result / note；同日同 method 幂等 upsert。
2. **测量方案**（前端选择 + 公式实现，均需性别/年龄）：

   | 方案 | 部位 | 自测可行性 |
   |---|---|---|
   | Jackson-Pollock 3 点（男） | 胸、腹、大腿 | ✅ 全部可自测 |
   | Jackson-Pollock 3 点（女） | 三头、髂前上棘、大腿 | ⚠️ 三头需辅助 |
   | Durnin-Womersley 4 点 | 肱二头、肱三头、肩胛下、髂前上棘 | ❌ 多处需辅助 |
   | Jackson-Pollock 7 点 | 胸、腋中、三头、肩胛下、腹、髂前、大腿 | ❌ 需辅助 |

   公式：先算身体密度（各方案专属回归式），再 Siri 公式转体脂率：体脂率 = (4.95/密度 − 4.5) × 100。
3. **设置页**新增性别、出生日期（公式必需）。
4. **结果落库**：计算结果自动写入 `body_metric(type='bodyfat')`（复用现有趋势图/同步链路），
   明细留在 `skinfold_record`；前端测量表单显示该方案部位图示与上次测量值。
5. 前端入口：身体数据页新增「皮脂钳测量」面板（与体脂秤图片导入并列）。

### 验收

- 每个方案用文献样例数据校验公式输出（误差 ≤0.1%）。
- 提交后 body_metric 出现对应日期 bodyfat 记录，趋势图可见。
- 非法输入（mm 超界 2~60、缺性别/年龄）有明确提示。

### 开放问题

- ~~Q5.1~~ **已确认（2026-09-02）**：4 方案全实现；UI 默认按性别置顶对应 JP3 方案，其余收进"更多方案"；方案卡片标注"✅ 可自测 / ⚠️ 需辅助"。
- ~~Q5.2~~ **已确认**：性别、出生日期存设置页（settings 表加字段），录入一次永久生效。

---

## 开发任务拆解（按依赖排序，2026-09-02 定稿）

| # | 任务 | 依赖 | 验收 |
|---|---|---|---|
| V4-1 | F1 修复：`query_activity_history` + garmin_only 点评 prompt 注入同类活动历史（近4周汇总+最近3次明细） | — | 用真实羽毛球 workout 重生成点评，引用真实历史；力量训练 prompt 结构回归不变 |
| V4-2 | F2 修复：exetype 语义渲染（辅助/负重）+ 有效负荷折算（体重缺失降级）+ 历史统计按 exetype 分组 | — | 2026-08-10 点评不再出现"负重 75kg"；help/plus_weight/无标记三类单测通过 |
| V4-3 | F5 皮脂钳：`skinfold_record` 表 + 4 方案公式（文献样例校验 ≤0.1% 误差）+ 设置页性别/出生日期 + 前端测量面板 + 结果写入 bodyfat | — | 提交后趋势图出现 bodyfat 点；非法输入有提示 |
| V4-4 | F3 详情页追评：SessionReviewSection 内嵌 ReportChatSection；`regenerate_with_feedback` 端点（对话注入"用户反馈"段，日限 5 次，覆盖确认）；下次建议独立重生成按钮 | V4-1, V4-2（重生成走新 prompt） | 详情页追问→重生成后新点评体现反馈；海报 one_liner 更新；幂等与记账不重不漏 |
| V4-5 | F4 逐组心率：`workout_set_hr` 表 + `services/set_hr.py`（HR 序列提取、顺序对齐+类别校验、组中均值/峰值+组后 30s 恢复）+ 详情页组次表心率列（低置信度标 ~） | — | 2026-08-26 抽 3 组对照佳明 Connect 误差 ≤3 bpm；无 exercise_sets 降级不显示 |
| V4-6 | F4 回填：存量 workout 全量回填脚本（手动触发）+ 逐组心率摘要注入 session_review prompt | V4-5 | 回填幂等可重跑；重生成点评引用逐组心率数据 |
| V4-7 | 联调与回归：全量 pytest + vitest + 前端 build 通过；覆盖率门禁 ≥85% 维持 | 全部 | CI 全绿 |

**建议实施顺序**：V4-1 → V4-2（两个 Bug 先行，见效快）→ V4-3（独立模块）→ V4-4 → V4-5 → V4-6 → V4-7。
每完成一个任务提交一次 Git，保持可回滚。
