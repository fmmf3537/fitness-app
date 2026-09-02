# V4-5-fix2 修订提示词：四处缺陷一次修齐

> 你是本仓库的资深后端工程师。本提示词是唯一任务来源：只按本提示词写代码，**不跑任何验收命令（pytest 一律不跑）**，**不执行任何 git 命令**。
> 红线：禁整文件重写；文件必须无 BOM；不得修改 `.env*`；不得删除任何既有文件；只改本提示词指定文件。

## 审核实测（7 failed / 878 passed）——四个根因全部已定位

### 根因 1：删旧后 `session.get(AIReport, old.id)` 仍返回旧对象（4 个用例）

`regenerate_session_review_with_feedback`（ai.py 约 904-907 行）与
`regenerate_next_advice_with_feedback`（约 950-953 行）的
`.delete(synchronize_session=False)` 不会清理 identity map，测试断言旧报告已删失败
（伴随 SAWarning: Identity map already had an identity）。
**修**：这两处改为 `.delete(synchronize_session="evaluate")`。
（`regenerate_session_reviews`（约 799 行）是旧代码，不动。）

### 根因 2：`_collect_feedback` 窗口截取错误（1 个用例）

12 条消息应取尾部 10 条（丢弃最早 2 条），实测最早的消息仍出现在 prompt 里。
**修**：确认实现为「按 id 正序取最后 REGEN_FEEDBACK_WINDOW=10 条，并保持正序格式化」——
可用 `order_by(ReportChatMessage.id.desc()).limit(10)` 再 reverse，或取全部后 `[-10:]`。
修后 `- 用户：消息0` / `- 教练：消息1` 不出现，`- 教练：消息11` 出现。

### 根因 3：API 异常分支顺序错误，429 变 404（1 个用例）

`api/ai_reports.py` 两个新端点（约 436-444、462-476 行）中
`except ValueError` 写在 `except ai_service.RegenerateLimitError` **之前**，
而 `RegenerateLimitError` 是 `ValueError` 子类 → 429 分支不可达。
**修**：两个端点都把 `except ai_service.RegenerateLimitError`（→ 429）放到
`except ValueError`（→ 404）**前面**。

### 根因 4：测试内 fake_chat 签名不接受 llm.chat 关键字参数（1 个用例）

`TestApiAuthAndBoundaries::test_session_review_success_returns_serialized_report`
monkeypatch `ai.llm.chat` 的 fake 只收 `messages`，而真实调用是
`llm.chat(msgs, session=session, purpose=...)` → TypeError。
**修**：该 fake 签名改为 `fake_chat(messages, **kwargs)`（可在 kwargs 里断言
purpose == f"session_review_regen:w{id}"，有则保留该断言）。

## 文件预算（共 3 个，不得越界）

1. 改 `backend/app/services/ai.py`（根因 1、2）
2. 改 `backend/app/api/ai_reports.py`（根因 3）
3. 改 `backend/tests/test_regenerate_with_feedback.py`（根因 4；若修完后发现既有断言与新行为冲突可微调，须自报告）

## 交付纪律

完成后输出简短交付报告：每根因的改动行号与内容、确认未触碰预算外文件、
红线确认（无 BOM/未跑 pytest/未跑 git）。
