# PRD —— 健身数据整合分析与指导 APP

> 本文档是面向 AI 辅助开发（vibe coding）的产品需求文档，作为编码时的上下文锚点。
> 开发计划见同目录《开发计划.md》；需求背景见《健身数据整合分析APP-需求文档.md》。
> 版本 V1.0 · 2026-08-03 · 单用户自用

---

## 1. 产品概述

个人健身数据中台 + AI 教练：自动融合「训记」（力量训练组次数据、训练计划）与「佳明 Garmin」（心率/时长/热量/睡眠/恢复等生理数据），形成统一训练档案；调用国内主流大模型生成单次点评、下次训练建议、周/月复盘；可安全写回训记训练记录。

## 2. 技术栈（已定型，勿擅自更换）

| 层 | 选型 |
|---|---|
| 后端 | Python 3.11+ / FastAPI / APScheduler |
| 数据库 | SQLite（开发期）→ PostgreSQL（部署期），ORM 用 SQLAlchemy |
| 佳明接入 | `garminconnect`（python-garminconnect）+ `garth` |
| 训记接入 | 官方 Open API（HTTP，见 §6.1） |
| AI 接入 | 统一适配层，OpenAI 兼容协议优先（Kimi / DeepSeek / MiniMax 均兼容） |
| 前端 | React + Vite + Tailwind CSS + ECharts，响应式 |
| 桌面端 | 后期 Tauri 套壳（V2，非 MVP） |
| 部署 | 低配云服务器 2C4G，Docker Compose |

## 3. 用户故事与验收标准

### US-1 每日数据自动同步（MVP）
> 作为用户，我希望每天早上看到昨天的训记+佳明数据已自动拉取并融合，无需任何手动操作。

- AC1：每日 22:47 定时任务自动拉取当日训记训练记录与佳明活动/健康数据；
- AC2：拉取失败自动重试 3 次（指数退避），仍失败则界面+推送告警；
- AC3：同一天重复运行不产生重复数据（幂等，按 datestr/activityId upsert）；
- AC4：佳明 token 过期时自动用缓存凭据重登，需人工介入时明确提示。

### US-2 同一次运动自动识别（MVP，核心）
> 作为用户，我希望训记和佳明对同一次训练的记录自动合并，特殊情况让我一键确认。

- AC1：训记训练时间区间与佳明活动时间区间重叠率 ≥ 60% → 自动合并；
- AC2：同日时间接近（起止差 ≤ 30min）但重叠不足 → 进入待确认队列，界面提供「合并 / 保持分开」操作；
- AC3：佳明有活动、训记无记录 → 提示并可一键生成训记草稿（走写回确认流）；
- AC4：训记有记录、佳明无活动 → 标记"无佳明数据"正常入库；
- AC5：一天多次训练（早有氧+晚力量）分别正确匹配，互不串扰；
- AC6：连续 7 天真实数据抽检，自动匹配准确率 ≥ 90%。

### US-3 字段级融合规则（MVP）
- AC1：动作名/组数/重量/次数/RPE 一律取训记；
- AC2：训练时长/总热量/心率（平均/最大/曲线）一律取佳明；
- AC3：被覆盖来源的数值保留在原始记录表，详情页可切换查看"训记原始 / 佳明原始 / 融合结果"；
- AC4：融合记录与两侧原始记录有外键引用，可追溯。

### US-4 训练档案看板（AC1/AC2 为 MVP；AC3 趋势页随 V1-6，2026-08-06 修订）
- AC1：日历视图标记有训练的日子，点击进入当日详情；
- AC2：详情页展示融合后的训练卡片（动作×组次表 + 心率曲线 + 时长/热量）；
- AC3：趋势页展示近 4/12 周总容量、各部位训练频次图表。

### US-5 历史数据导入（V1）
> 回溯起点已确认（2026-08-06）：训记 2023-02 启用、佳明 2017 启用。

- AC1：训记按 datestr 逐日回溯，起点 `BACKFILL_START_DATE=2023-02-01`，遵守 15s 限频，空日记进度跳过，可断点续传；
- AC2：**佳明分两类**：活动列表（2017 年起全量，分页拉取）；每日健康（睡眠/HRV/BB 等仅从 2023-02-01 起，与训记对齐，控制 429 风险与耗时）；
- AC3：佳明侧全程单会话长拉取（禁止重复登录触发 IP 级 429），429 时指数退避；
- AC4：导入进度可见（API + 前端进度页），完成后统一执行历史融合。

### US-6 AI 单次点评（V1）
- AC1：每日同步完成后，若当日有融合训练则自动生成点评；
- AC2：输入包含本次训练 + 近 4 周同部位历史 + 近 7 天睡眠/HRV/训练准备度；
- AC3：输出含完成质量、与历史 PR 对比、恢复评估、注意事项，存库可回看。

### US-7 AI 下次训练建议（V1）
- AC1：拉取训记官方计划（未来 30 天，只读）缓存；
- AC2：建议对照计划输出到「动作/重量/组数/次数」粒度；
- AC3：界面分两类呈现：可自动写回项（带 diff 确认按钮）与需手动调整项（附操作指引）。

### US-8 训记写回（V1）
- AC1：任何写回前先展示变更 diff，用户点击确认才执行；
- AC2：更新旧训练保留 localid/start/end 及 note 元数据；
- AC3：写回成功后以服务端返回数据覆盖本地缓存；
- AC4：遵守 45s 写回限频，排队执行。

### US-9 多模型切换（V2）
- AC1：设置页可配置 Kimi / DeepSeek / MiniMax 的 API Key 并切换默认模型；
- AC2：每次调用记录 token 用量与估算成本，月度汇总可见；
- AC3：某模型调用失败可一键切换备用模型重试。

### US-10 周期复盘（V2）
- AC1：每周日 21:13 生成周复盘（频率/部位分布/容量趋势/PR/睡眠关联/下周建议）；
- AC2：每月 1 日 09:23 生成月复盘（含计划完成率与趋势图）；
- AC3：报告可导出 Markdown / PDF。

### US-11 截图识别兜底（V2）
- AC1：可上传训记/佳明截图，调用多模态模型输出结构化 JSON；
- AC2：识别结果先入预览页，用户确认后入库；
- AC3：训记标准报表截图的字段识别准确率 ≥ 95%。

### US-12 身体数据记录（V1，2026-08-03 新增）
> 作为用户，我希望手动记录身高/体重/血压/血糖并看趋势，体重还能同步进训记。

- AC1：录入页支持四类指标：身高(cm)、体重(kg)、血压(收缩压/舒张压 mmHg)、血糖(mmol/L)；
  按 `date + type` upsert，同日同类型重复录入覆盖旧值；
- AC2：身体数据页展示各指标趋势曲线（ECharts），体重曲线与训练容量趋势可同屏对照；
- AC3：体重（及体脂率）可选"同步到训记"：调用训记身体数据 API，严格走
  `dry_run: true` → 展示 res.summary 变更摘要 → 用户确认 → `confirmed: true` 流程；
- AC4：身高/血压/血糖仅存本地（训记 API 无对应类型），界面明确标注"仅本地"；
- AC5：首次使用引导录入身高，身高变化频率低，按 `date + height` 存历史；
- AC6：AI 单次点评/复盘的上下文中纳入近 4 周体重趋势（US-6/US-10 输入扩展）。

## 4. 数据模型（开发以此为准）

```sql
-- 用户配置（单用户，单行表）
settings(id, garmin_token_store, xunji_api_key_enc, default_llm, llm_keys_json_enc, created_at)

-- 训记原始训练（按 datestr+localid 幂等）
xunji_train(id PK, datestr, localid, title, start_ms, end_ms, note_json, raw_json, fetched_at,
            UNIQUE(datestr, localid))

-- 佳明原始活动（按 activity_id 幂等）
garmin_activity(id PK, activity_id UNIQUE, activity_type, name, start_ts, end_ts,
                duration_s, calories, avg_hr, max_hr, raw_json, fetched_at)

-- 佳明每日健康（按日期幂等）
garmin_daily(id PK, date UNIQUE, steps, resting_hr, stress_avg, body_battery_high, body_battery_low,
             hrv_status, sleep_json, raw_json, fetched_at)

-- 身体数据（手动录入，按 date+type 幂等）
body_metric(id PK, date, type,      -- height / weight / bp_systolic / bp_diastolic / blood_glucose
            value REAL, unit,       -- cm / kg / mmHg / mmol/L
            synced_to_xunji BOOLEAN DEFAULT FALSE,   -- 仅 weight/bodyfat 可能为 TRUE
            note, created_at, updated_at,
            UNIQUE(date, type))

-- 融合训练档案（核心表）
workout(id PK, date, title,
        xunji_train_id FK NULL, garmin_activity_id FK NULL,
        match_status,          -- auto_matched / manual_matched / xunji_only / garmin_only / pending
        tags,                  -- 佳明活动类型作标签（M4 2026-08-04 补充，落实 §5.2）
        duration_s, calories, avg_hr, max_hr,   -- 以佳明为准
        movements_json,                         -- 以训记为准：[{name, difficulty?, sets:[{weight,unit,reps,time,done,rpe?}]}]
        created_at, updated_at)

-- 待确认队列
match_candidate(id PK, workout_id FK, xunji_train_id FK, garmin_activity_id FK,
                reason, status,  -- pending / merged / split
                created_at, resolved_at)

-- 训记官方计划缓存（只读）
xunji_plan(id PK, plan_ref, plan_json, date_from, date_to, fetched_at)

-- AI 报告
ai_report(id PK, type,        -- session_review / next_advice / weekly / monthly
          workout_id FK NULL, period_start, period_end,
          model, prompt_tokens, completion_tokens, cost_estimate,
          content_md, created_at)

-- LLM 调用记账
llm_call(id PK, provider, model, purpose, prompt_tokens, completion_tokens, cost_estimate, status, created_at)

-- 任务运行日志
job_run(id PK, job_name, started_at, finished_at, status, error, detail_json)
```

## 5. 核心业务规则

### 5.1 匹配算法（伪代码，实现时严格遵循）

```
def match(xunji_trains, garmin_activities, date):
    pairs, unmatched_x, unmatched_g = [], list(xunji_trains), list(garmin_activities)
    # 第一轮：时间重叠 ≥ 60%（重叠时长 / 较短区间时长）
    for x in unmatched_x:
        for g in unmatched_g:
            if overlap_ratio(x, g) >= 0.6:
                pairs.append((x, g, 'auto_matched')); remove both; break
    # 第二轮：同日且起止差 ≤ 30min → 待确认
    for x in unmatched_x:
        for g in unmatched_g:
            if abs(start_diff(x, g)) <= 30min or abs(end_diff(x, g)) <= 30min:
                create_match_candidate(x, g, reason='time_close'); remove both; break
    # 剩余：xunji_only / garmin_only（garmin_only 且类型为力量训练时提示可生成训记草稿）
```

### 5.2 融合优先级
动作维度 → 训记；时长/热量/心率 → 佳明；标题 → 训记（佳明类型作标签）。

### 5.3 限频纪律
训记读 15s / 完整读 30s / 写回 45s；`too frequent` 时按 `retry_after_ms` 等待；按 datestr 缓存，同日不重复请求。

### 5.4 写回安全
diff 预览 → 用户确认 → 执行 → 服务端返回覆盖缓存；保留 localid/start/end/note；动作名只用 GitHub `Foveluy/Xunji-movements` 标准中文名。

## 6. 外部接口规格

### 6.1 训记 Open API（已实测连通，2026-08-03）

```
# 读取训练
POST https://trains.xunjiapp.cn/api_trains_for_llm_v2
Authorization: Bearer <XUNJI_KEY>
{"schema_version": "train_open_api_v2", "datestr": "2026-08-03", "include_full_data": false}
# 成功数据在 res.trains；响应可能 gzip 压缩

# 读取官方计划（只读，gzip）
POST https://api.xunjiapp.cn/open/plan/query_gzip
{"schema_version": "plan_open_api_v1", "action": "list"}
{"schema_version": "plan_open_api_v1", "action": "get", "plan_ref": "platform:155",
 "start_date": "...", "end_date": "...", "include_movements": true}

# 写回训练
POST https://trains.xunjiapp.cn/api_upsert_trains_for_llm_v2
{"schema_version": "train_open_api_v2", "client_request_id": "<uuid>", "dry_run": false,
 "include_full_data": false, "res": [{...}]}
# 约束：单次 ≤4 条/同一天；每训练 ≤15 动作；每动作 ≤20 组
```

Key 从环境变量 `XUNJI_API_KEY` 读取，**禁止硬编码进代码库**。

### 6.1b 训记身体数据 API（2026-08-03 新版 Key 新增）

```
# 查询身体数据（gzip 响应）
POST https://api.xunjiapp.cn/open/body/query_gzip
Authorization: Bearer <XUNJI_BODY_API_KEY>
{"start_date": "2026-01-01", "end_date": "2026-08-03",
 "types": ["weight", "bodyfat"], "include_latest": true, "include_records": true,
 "limit": 500, "offset": 0}

# 写入身体数据（按 datestr+type upsert）
POST https://api.xunjiapp.cn/open/body/upsert_gzip
{"schema_version": "body_open_api_v1", "client_request_id": "<uuid>",
 "dry_run": true,                                  # 第一步：预览，展示 res.summary
 "records": [{"datestr": "2026-08-03", "type": "weight", "value": 72.4}]}
# 第二步：用户确认后 → 同记录 + "dry_run": false, "confirmed": true
```

- Key 从环境变量 `XUNJI_BODY_API_KEY` 读取（`xjbody_...`）；接口文档原件 `素材/训记key_新版.txt`；
- 训记类型仅 `weight/bodyfat/围度`；腰围字段固定拼写 `weist`；身高/血压/血糖不支持，仅本地；
- 限频：同 key 同 endpoint 15s/次；
- 同文件新增的饮食 API（`xjfood_...` + 食物搜索 Key）**本期不实现**，仅登记环境变量占位。

### 6.2 佳明（2026-08-04 修正：中国区账号）

- **用户账号在中国区（garmin.cn）**，全球区端点登录可成功但返回空数据（陷阱，已在 M3 踩实）；
- **接入方式**：`garminconnect` 封装库对 CN 区 resume 会话有 bug，**改用底层 `garth` 库直连**：
  - 登录：`garth.configure(domain='garmin.cn')` → `garth.login(email, password)` → `garth.save(token_store)`；
  - 后续会话：`garth.configure(...)` → `garth.resume(token_store)`；
  - 取数：`garth.connectapi(path, params=...)`（活动列表 `/activitylist-service/activities/search/activities` 等）；
  - 已实测（2026-08-04）：可拉到 strength_training/badminton 等活动；
- **风控**：佳明有 IP 级 429（连续登录 2-3 次即触发）——同一进程只登录一次并复用会话；收到 429 指数退避；历史导入期间禁止重复登录；
- 凭据从环境变量 `GARMIN_EMAIL` / `GARMIN_PASSWORD` 读取；token 缓存于 `~/.garminconnect`；
- 失效降级：保留文件手动导入入口（`/import/fit`），支持 FIT/TCX/GPX/KML 四种格式（V3-7 扩展）：
  - GPX 兼容 1.1/1.0 命名空间，心率取 `gpxtpx:TrackPointExtension/gpxtpx:hr`，距离无原始字段时按 haversine 逐点累加；
  - **GPX 命名空间陷阱（V3-10c 踩实）**：XML 命名空间是大小写敏感的 URI，官方为大写 `http://www.topografix.com/GPX/1/1`（小写形式仅作兜底）；命名空间全不匹配时按 local-name 匹配；`trk/extensions/totalDistance` 存在时直接采用为距离（小米运动健康导出特征：version="1.0" 属性但 xmlns 用 1/1 命名空间）；
  - KML 仅支持含 `gx:Track`（`<when>` 时间戳 + `<gx:coord>`）的轨迹导出；仅 LineString（无时间戳）的 KML 无法确定运动日期，直接拒绝并提示导出含 gx:Track 的版本；
  - 全部用标准库 `xml.etree.ElementTree` 解析（零新依赖），落库/去重/重匹配复用 FIT/TCX 既有管线。

### 6.3 LLM 适配层

统一接口 `chat(messages, **opts) -> {content, prompt_tokens, completion_tokens}`：

| Provider | Base URL | 默认模型 | 备注 |
|---|---|---|---|
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat` | OpenAI 兼容；**2026-08-06 实测可用，V1-1 首发接入** |
| MiniMax | `https://api.minimaxi.com/v1` | `MiniMax-M2` | OpenAI 兼容；**已实测可用**；M2 为推理模型，输出含 `<think>` 块，适配层须剥离后再落库 |
| Kimi | `https://api.moonshot.cn/v1` | `kimi-k2.6`（视觉+文本，256k）；备选旗舰 `kimi-k3`（原生视觉，1M） | OpenAI 兼容；用户暂无 Key，V2-1 前补申请；**2026-08-07 核查：k2 系列已下线、k2.5/moonshot-v1 系列 8/31 下线，一律不可用**；截图识别（V2-3）直接用 kimi-k2.6/k3 的多模态能力，无需单独视觉模型 |

Key 存 settings 表（加密），设置页可切换默认模型；每次调用写 llm_call 记账。

## 7. 非功能需求

- 所有密钥/token 加密存储（Fernet 对称加密，主密钥从环境变量读），不入日志、不入 Git；
- 全站访问需登录口令（单用户简单会话认证即可）；
- 每日数据库备份，保留 30 天；
- AI 生成类操作异步执行 + 完成通知；常规页面 < 1s；
- 佳明接入封装为独立 `garmin_adapter` 模块，接口失效可替换实现；
- AI 分析只发送最小必要数据子集。

## 8. 明确不做（防范围蔓延）

- 不做小米运动健康接入（用户已放弃）；睡眠数据佳明单源；
- 不做训记官方计划的修改（API 只读）；
- 不做饮食/营养记录（训记饮食 API 已备案，后续可扩展）；
- 不做多用户、社交功能；
- MVP 不做桌面套壳与手机推送（V2 再说）。
