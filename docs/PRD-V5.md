# PRD-V5 —— AI 教练长期记忆（L1 教练须知 + L2 对话记忆 + L3 长期统计）

> 面向 AI 辅助开发（vibe coding）的需求定稿，编码时的唯一依据。
> 版本 V5.0 · 2026-09 · 单用户自用 · 与《开发提示词手册.md》Sprint 编号衔接（下一个 Sprint 12）
> 本文档由用户逐问答确认，8 个决策点全部拍板。

---

## 1. 问题背景与目标

### 1.1 现状痛点（代码实证）

| # | 痛点 | 代码证据 |
|---|---|---|
| P1 | AI 点评时无法统一参考更多历史数据：现仅注入近 4 周同动作历史（`limit=3`）+ 近 7 天恢复 + 近 4 周体重 | `ai.py:148 query_movement_history`（weeks=4, limit=3）、`ai.py:318 query_recovery_summary`（days=7） |
| P2 | 历史对话强调的点下一次不生效：`_collect_feedback` 仅取**同一 workout 旧报告**最近 10 条追问注入重生成，不跨报告、不跨日期、不进 daily_sync 自动生成 | `ai.py:877 _collect_feedback`（REGEN_FEEDBACK_WINDOW=10） |
| P3 | 没有"用户长期偏好"这种结构化记忆——用户说"深蹲时膝盖有旧伤要提示"，下一次点评完全不知道 | 数据库无教练须知/偏好表；`settings` 表仅存密钥/LLM 配置 |

### 1.2 目标

给 AI 教练加**长期记忆**，让点评/建议/复盘/追问回答都能：
- 参考更长周期的历史数据（12 周聚合而非 4 周明细）
- 记住用户历史对话中强调的要求
- 记住用户手写的长期偏好，AI 每周自动提炼新要求供确认

---

## 2. 总体架构：三层记忆

把记忆拆成三个可独立实现的层，Token 成本逐层可控：

```
┌─────────────────────────────────────────────────────┐
│  每次 AI 产出（点评/建议/复盘/追问）                  │
│  prompt = 既有内容 + L1 教练须知 + L2 对话记忆      │
│                      (tag 检索 top-k) + L3 长期统计 │
└─────────────────────────────────────────────────────┘
        ▲                    ▲                ▲
        │ 必带，低消           │ 按需，中消      │ 必带，低消
┌───────┴──────┐   ┌─────────┴────────┐  ┌────┴─────┐
│ L1 教练须知   │   │ L2 对话记忆摘要   │  │ L3 长期统计│
│ - 用户手写打底│   │ - 每日同步时提炼  │  │ - 12 周聚合│
│ - AI 每周提炼│   │ - tag/关键词检索  │  │ - 容量/部位│
│   草稿确认生效│   │   top-5 注入      │  │ - 体重/PR  │
└──────────────┘   └──────────────────┘  └───────────┘
```

---

## 3. 已确认决策（8 项，勿擅自更改）

| # | 决策点 | 结论 | 说明 |
|---|---|---|---|
| D1 | L1 写入方式 | **C：手动打底 + AI 每周提炼草稿确认** | 用户手写核心须知；每周复盘任务里 AI 从本周对话提炼新要求草稿，用户确认后并入正式清单 |
| D2 | 作用范围 | **C：全部 5 类产出** | session_review / next_advice / weekly / monthly / report_chat 全部注入三层记忆 |
| D3 | 生效频率 | **A：每次自动生成都注入** | 不设档位开关，每次生成都带 L1 + L2(top-k) + L3 |
| D4 | 入口形态 | **C：追问框 + 教练须知页 + 独立聊天入口** | 追问框（已有）+ 教练须知独立页 + 独立"跟教练聊天"入口，三入口并存 |
| D5 | L2 检索方式 | **C：先 tag/关键词，后向量** | V1 用关键词/tag 匹配检索 top-k；效果不佳再升级 embedding 向量检索 |
| D6 | L2 提炼节奏 | **B：每日同步时批提炼** | 每日 22:47 每日同步跑完后，把当天新增追问/聊天统一提炼成摘要 |
| D7 | 独立聊天定位 | **B：持久对话（存历史）** | 新表 coach_chat_message（不绑定 report_id），可回看/继续；不触发动作 |
| D8 | 教练须知页权限 | **C：完全可编辑（增/删/改）** | 手写打底 + 删除过时 + 编辑措辞；AI 提炼草稿单独列表带"采纳/忽略" |

---

## 4. 费用评估（2026-09 行情，已确认可行）

### 4.1 每次生成记忆注入的 token 增量

| 层 | 内容 | 增量估算 |
|---|---|---|
| L1 教练须知 | 15-30 条 × 每条 30 字 ≈ 900 字 | ≈ 1,200 输入 token |
| L2 对话记忆 | 检索 top-5 条 × 每条 120 字 ≈ 600 字 | ≈ 800 输入 token |
| L3 长期统计 | 12 周聚合 ≈ 500 字 | ≈ 650 输入 token |
| **合计/次** | | **≈ 2,650 输入 token** |

### 4.2 周/月成本（5 类产出全量接入）

每周记忆注入次数 ≈ 14.25 次（点评 4 + 建议 4 + 周报 1 + 月报 0.25 + 追问 5）
每周记忆注入输入 ≈ 14.25 × 2,650 ≈ **37,800 tokens**
每周提炼（每日批提炼）≈ 输入含当天对话 + 输出 ≈ 6,000 tokens
**每周合计 ≈ 43,800 输入 + 500 输出**

| Provider | 周成本 | 月成本 |
|---|---|---|
| DeepSeek（代码表 1/2 元） | ≈ ¥0.05 | ≈ ¥0.2 |
| MiniMax（2.1/8.4 元） | ≈ ¥0.09 | ≈ ¥0.4 |
| Kimi（6.5/27 元） | ≈ ¥0.29 | ≈ ¥1.2 |
| Kimi（官方 $3/$15 ≈ ¥21.5/¥107） | ≈ ¥0.96 | ≈ ¥3.8 |

**结论：即使最贵组合（Kimi + 全量注入），月成本 ≤¥5；默认 DeepSeek 月成本 ≈¥0.2。Token 平衡完全可行，无成本压力。**（注：受沙箱 TLS 限制，Kimi 官方价待用户双击确认，代码内单价表 `llm.py:65-72` 是 2026-08-07 校准值。）

---

## 5. 数据模型（新增 4 张表 + 扩 1 张）

```sql
-- ① 教练须知（L1 正式清单，手动维护 + AI 采纳）
coach_preference(
    id PK,
    content TEXT NOT NULL,        -- 须知内容，如"深蹲时注意右膝旧伤，重量≥80kg 要提示"
    category VARCHAR(30),         -- manual / ai_suggested
    tags VARCHAR(200),            -- 逗号分隔：深蹲,膝盖,伤
    source TEXT,                  -- 'user' | 'weekly_review' | 'daily_distill'
    active BOOLEAN DEFAULT TRUE,  -- FALSE = 已删除（软删）
    created_at, updated_at
)

-- ② AI 提炼草稿（L1 待确认，D1）
coach_preference_draft(
    id PK,
    content TEXT NOT NULL,
    tags VARCHAR(200),
    source VARCHAR(30),           -- sys_prompt / daily_distill / weekly_review
    status VARCHAR(20) DEFAULT 'pending',  -- pending / accepted / rejected / merged
    created_at, resolved_at
)

-- ③ 对话记忆摘要（L2）
coach_memory(
    id PK,
    summary TEXT NOT NULL,        -- 提炼后的摘要，如"用户强调训练时右膝有旧伤，深蹲需谨慎"
    tags VARCHAR(200),            -- 检索用 tag
    source VARCHAR(20),           -- report_chat / coach_chat
    ref_report_id INTEGER NULL,   -- 来源报告（report_chat 时）
    ref_chat_id INTEGER NULL,     -- 来源聊天（coach_chat 时）
    active BOOLEAN DEFAULT TRUE,
    created_at
)

-- ④ 独立聊天消息（D7）
coach_chat_message(
    id PK,
    role VARCHAR(10),             -- user / assistant
    content TEXT,
    model VARCHAR(100) NULL,
    prompt_tokens INTEGER NULL, completion_tokens INTEGER NULL,
    cost_estimate REAL NULL,
    client_request_id VARCHAR(64) UNIQUE,  -- 幂等键（沿用 report_chat 惯例）
    created_at
)

-- ⑤ 扩展 settings（D8 可选，用于记忆相关配置，如提炼使用的 provider）
settings: + memory_default_provider VARCHAR(50) NULL   -- 为空用当前默认 LLM
```

> 迁移命名建议：新 alembic 迁移 `coach_memory_tables`，down_revision 接当前 head（`b7c8d9e0f1a2`，V4-7 建立的 workout_set_hr）。
> 所有新表遵循项目的 SQLAlchemy 2.x `Mapped`/`mapped_column` 风格 + 幂等 UniqueConstraint。

---

## 6. 功能规格

### 6.1 L1 教练须知（新增）

- **页面**：`/coach-preferences`（新增路由，放设置页同级的独立页，或设置页 tab）
- **操作**：新增（手写）/ 编辑 / 软删（active=False）/ 查看
- **AI 提炼**：
  - 每周复盘任务（周日 21:13）里，把本周全部追问+聊天对话作为输入，调 LLM 提炼出"用户可能的新长期要求"草稿（**结构化输出**：`[{"content": "...", "tags": "..."}]`，≤5 条）
  - 草稿落 `coach_preference_draft(status='pending')`，页面显示"待确认"列表，按钮：采纳（→ 并入 coach_preference，category='ai_suggested'）/ 忽略（status='rejected'）
  - 提炼失败不阻断周复盘（沿用 `except: pass` 纪律，记 job_run）+ 与既有"已存在的同内容草稿"去重（按 content 归一化）

### 6.2 L2 对话记忆（新增）

- **提炼**：每日 22:47 每日同步 run 完成后，若当天有新增 report_chat / coach_chat 消息 → 调用 LLM 逐对话提炼成摘要（输入=该对话全部消息，输出=`[{"summary": "...", "tags": "..."}]` ≤3 条）
  - 落 `coach_memory(active=True)`
  - 失败单独记 job_run，不阻断同步主流程
- **检索注入**（D5，V1 关键词/tag）：
  - 每次生成时，取本次上下文的 tag 集合（训练动作名 / 部位 / 活动类型 / 报告类型）
  - 在 `coach_memory` 中按 tags 关键词匹配（`LIKE %tag%` 或内存 contains），按最近 created_at 排序取 **top-5**
  - 命中不足 5 条时用无 tag 匹配兜底（如"恢复""注意"类通用条目）
  - 注入 prompt 段：`## 用户历史对话要点（AI 参考）` + 近期 top-5 条摘要
- **未来升级**：引入 embedding 列 + 向量检索（记录于 TECH_DEBT，不本期实现）

### 6.3 L3 长期统计（既有函数扩展）

- 复用 `query_period_training_summary`（`ai.py:1764`）但窗口从"当前周期"扩展到 **近 12 周**：
  - 新增 `query_longterm_stats(session, current_date)` 返回：12 周训练频率 / 部位分布 / 总容量趋势（4周 vs 12周对比，衡量进步） / PR 事件（近 12 周 vs 历史上限）
  - 注入 prompt 段：`## 近 12 周长期趋势（AI 参考）`，聚合值而非明细（token 低）
- `query_recovery_summary` 保持 7 天窗口不变（恢复数据时效性要求高）

### 6.4 独立聊天入口（D7 新增）

- **后端**：`coach_chat_message` 表 + `/api/coach/chat` 端点（POST 发消息 / GET 历史 / DELETE 清空）
  - 消息装配 = system（教练人设 + 当前记忆概况：L1 须知 + L2 top-5 + L3 概览）+ 最近 30 条历史 + 新消息
  - 沿用 report_chat 的 client_request_id 幂等、MAX_CHAT_HISTORY window、成本记账（llm_call）
  - 单轮消息上限 1000 字（沿用 `MAX_CONTENT_LENGTH`）
- **前端**：`/coach`（新增路由）聊天页，Bubble UI + 历史列表 + 清空按钮
- **不触发动作**（D7：不做"聊天里说要生成报告→自动触发"）

### 6.5 prompt 注入位置（5 个入口统一改）

| 入口 | 文件/函数 | 注入段 |
|---|---|---|
| session_review | `build_session_review_prompt`（ai.py:398） | 恢复段前插入记忆段 |
| next_advice | `build_next_advice_prompt`（ai.py:1203） | 计划段后插入 |
| weekly / monthly | `build_weekly_prompt`（ai.py:2023）/ `build_monthly_prompt`（2071） | 周期汇总后插入 |
| report_chat | `build_system_prompt`（report_chat.py:56） | 报告全文后追加记忆段 |

统一注入函数：`build_memory_section(l1: list, l2: list, l3: dict) -> str`，纯函数、可测试。

---

## 7. 非功能要求

- **token 记账**：所有新 LLM 调用（提炼 + 聊天）写入 `llm_call`，purpose 用 `memory_distill` / `coach_chat`
- **限频纪律**：提炼任务只在 daily_sync / weekly_review 内跑，复用现有 job_run 日志与重试（次数 ≤3）
- **成本护栏**：单次提炼输入上限截断（对话过长只提炼最近 100 条，超长截尾）；提炼输出强制 JSON 校验（沿用 next_advice 的 schema 校验模式）
- **幂等**：coach_preference 按 content 去重；draft 按 content+source 去重；coach_chat 按 client_request_id 幂等；coach_memory 按 (source, ref_id) 幂等
- **安全**：无新密钥；记忆内容属个人数据，随数据库备份；软删除优先

---

## 8. 明确不做（防范围蔓延）

- ❌ 不做 memory 的向量检索（本期）；TECH_DEBT 登记
- ❌ 不做独立聊天触发动作（"生成周报"等意图识别）
- ❌ 不做多用户/记忆按用户隔离（单用户自用）
- ❌ 不做记忆条目的自动过期（用户手工删即可）
- ❌ 不为记忆引入新的第三方依赖（V1 用纯 Python + 现有 SQLAlchemy）

---

## 9. 验收标准（AC）

| # | 验收 |
|---|---|
| AC1 | 教练须知页可新增/编辑/软删条目；AI 每周提炼草稿出现"采纳/忽略"按钮，采纳后并入正式清单且不重复 |
| AC2 | 用户在某报告追问"以后深蹲提醒我膝盖旧伤"，次日 session_review 自动生成时该句出现在"用户历史对话要点"段 |
| AC3 | 每日同步后 coach_memory 有新增；同步失败时提炼不阻断同步主流程（job_run 有 failed 记录） |
| AC4 | 独立聊天页可发消息、回看历史、清空；消息幂等（重复点击不重复调用 LLM） |
| AC5 | 全部 5 类产出的 prompt 均含"记忆"段；无记忆数据时该段不出现（空数据优雅降级） |
| AC6 | 后端单测覆盖记忆段组装纯函数（build_memory_section）、提炼 JSON 校验、检索 top-k、去重；覆盖率 ≥85% 门禁保持 |
| AC7 | 真实运行一周，记忆注入带来的额外 LLM 成本 ≤¥1（DeepSeek 档）并记录于 job_run/llm_call |

---

## 10. 分工建议（后续给 Cursor 用）

按 V4 切片流水线风格拆片：

| 切片 | 内容 | 预算 |
|---|---|---|
| V5-1 | 后端：4 张新表 + 迁移 + 模型 + coach_preference/draft CRUD API | 5 文件（模型+迁移+2 API+测试） |
| V5-2 | 后端：L2 提炼任务（daily_sync 挂钩）+ coach_memory 检索函数 + build_memory_section + 5 入口注入 | 6-8 文件 |
| V5-3 | 后端：L3 query_longterm_stats + 注入 | 2 文件 |
| V5-4 | 后端：独立聊天 coach_chat_message + API | 3 文件 |
| V5-5 | 前端：教练须知页 + 草稿确认 UI | 3 文件 |
| V5-6 | 前端：独立聊天页 | 3 文件 |
| V5-7 | 前端：各页面 prompt 显示优化（可选，展示"本次参考记忆"）| 2-3 文件 |

---

*以上方案已覆盖全部 8 项确认决策。用户审核通过后，按 V4 切片流水线（起草→执行→轮询→亲手审核→修订→提交）逐片实施。*