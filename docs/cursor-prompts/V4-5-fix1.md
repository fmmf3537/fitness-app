# V4-5-fix1 修订提示词：重生成日限改走 llm_call 记账（护栏真实生效）

> 你是本仓库的资深后端工程师。本提示词是唯一任务来源：只按本提示词写代码，**不跑任何验收命令（pytest 一律不跑）**，**不执行任何 git 命令**。
> 红线：禁整文件重写；文件必须无 BOM；不得修改 `.env*`；不得删除任何既有文件；只改本提示词指定文件。

## 问题（审核方实读交付代码 + 执行器自报遗留风险 #1 确认）

V4-5 的 `_check_regen_limit` 统计「当日该 workout 该 type 的 ai_report 行数 >= 5」，
但重生成是**删旧+建新**，净效果恒为 1 行——真实使用中连点多少次都不会触发 429，
PRD「每日每 workout 重生成上限 5 次」护栏形同虚设（当前只有测试手工造 5 条才触发）。

## 修订方案（已核实可行性）

`app/adapters/llm.py` 的 `llm.chat(msgs, session=..., purpose=...)` 会把 `purpose`
原样落 `llm_call` 表（`_parse_and_record` → `LLMCall(purpose=purpose, ...)`）。
llm_call 行**不随报告删除而消失**，且用量统计按 (provider, model) 分组、不按 purpose，
用专用 purpose 串记账无副作用。改用它做真实计数。

## 修订内容（文件预算：改 2 + 改 1 测试 = 共 3 个，不得越界）

### 1. `backend/app/services/ai.py`

- models import 行加 `LLMCall`。
- `generate_session_review` / `generate_next_advice` 各加 keyword-only 参数
  `purpose: str | None = None`；默认 chat_fn 闭包改为
  `llm.chat(msgs, session=session, purpose=purpose or "session_review")`
  （next_advice 对应 `or "next_advice"`）。chat_fn 外部注入时该参数无作用（测试路径）。
- `_check_regen_limit(session, workout_id, report_type)` 改为统计 `LLMCall`：
  `purpose == f"{report_type}_regen:w{workout_id}"` 且 `created_at >= 当日 00:00（本地）`
  的行数 >= `REGEN_DAILY_LIMIT` 时抛 `RegenerateLimitError`（消息含「每日重生成上限 5 次」）。
  用 `datetime.combine(date.today(), time.min)` 构造下界，避免 func.date 时区歧义。
- `regenerate_session_review_with_feedback` /
  `regenerate_next_advice_with_feedback`：调 generate 时传
  `purpose=f"{report_type}_regen:w{workout_id}"`
  （分别为 `session_review_regen:w{id}` / `next_advice_regen:w{id}`）。

### 2. `backend/app/api/ai_reports.py`

无需改动（若自查发现无需改动，在交付报告中明确说明）。

### 3. `backend/tests/test_regenerate_with_feedback.py`

- 日限用例改为：造 5 条 `LLMCall(purpose="session_review_regen:w{workout_id}", created_at=当日)`
  → 第 6 次 API 调用 429；昨日同 purpose 行不计入。
- 新增真实闭环用例：不注入 chat_fn，改为 `monkeypatch.setattr(app.services.ai.llm, "chat", fake)`
  （fake 内部模拟 llm.chat 行为：手动 `session.add(LLMCall(purpose=入参 purpose, ...))` + commit，
  返回合法 content）——连续重生成 5 次成功、第 6 次 429，证明护栏在真实路径生效。
- 既有「手工造 5 条 ai_report」的日限用例如与新机制重复可改写或删除（删除需在报告中说明）。

## 交付纪律

完成后输出完整交付报告：改动行号与内容、测试调整清单、确认未触碰预算外文件、
红线确认（无 BOM/未跑 pytest/未跑 git）、遗留风险。
