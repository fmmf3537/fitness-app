# V4-5-fix3 修订提示词：修正测试断言设计缺陷（已经人工批准的第 3 轮）

> 你是本仓库的资深后端工程师。本提示词是唯一任务来源：只按本提示词写代码，**不跑任何验收命令（pytest 一律不跑）**，**不执行任何 git 命令**。
> 红线：禁整文件重写；文件必须无 BOM；不得修改 `.env*`；不得删除任何既有文件；只改本提示词指定文件。

## 背景（审核方已实读定位，生产代码无缺陷，仅修测试断言）

V4-5 当前 878 passed / 4 failed，4 个失败全部在
`backend/tests/test_regenerate_with_feedback.py`，根因是该新测试文件自身的断言设计缺陷：

### 缺陷 1：SQLite id 复用导致「旧报告已删」断言必然失败（3 处）

`regenerate_*_with_feedback` 删旧后建新行，SQLite（非 AUTOINCREMENT）会把 id=1 复用给新行，
`session.get(AIReport, old.id)` 取到的是**新报告**，以下断言必然失败：

- `TestRegenerateSessionReview::test_regenerates_with_chat_feedback`（约 292 行）
- `TestRegenerateSessionReview::test_regenerates_without_chat_feedback`（约 328 行）
- `TestRegenerateNextAdvice::test_regenerates_with_feedback`（约 544 行）

**修法**：把 `assert session.get(AIReport, old.id) is None` 改为计数断言：

```python
remaining = session.query(AIReport).filter(
    AIReport.workout_id == w.id, AIReport.type == "<对应 type>",
).all()
assert len(remaining) == 1
assert remaining[0].id == new_report.id
```

（若该用例已有同义 remaining 断言，则直接删除这行错误断言并在交付报告说明。）

### 缺陷 2：消息编号子串碰撞（1 处）

`TestRegenerateSessionReview::test_collect_feedback_respects_window`（约 363-366 行）：

```python
assert "- 用户：消息0" not in user   # OK，无碰撞
assert "- 教练：消息1" not in user   # 失败：'- 教练：消息11' 包含子串 '- 教练：消息1'
```

**修法**：负断言改为按行精确匹配：

```python
lines = user.splitlines()
assert "- 用户：消息0" not in lines
assert "- 教练：消息1" not in lines
assert "- 用户：消息2" in lines
assert "- 教练：消息11" in lines
```

## 文件预算（共 1 个，不得越界）

- 改 `backend/tests/test_regenerate_with_feedback.py`

**不得改 `backend/app/services/ai.py` / `backend/app/api/ai_reports.py`**（生产代码已审核通过）。

## 交付纪律

完成后输出简短交付报告：每处改动行号与内容、确认未触碰其他文件、
红线确认（无 BOM/未跑 pytest/未跑 git）。
