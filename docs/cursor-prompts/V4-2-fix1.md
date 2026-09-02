# V4-2-fix1 修订提示词：修正两处 PR 行断言与既有浮点渲染风格不一致

> 你是本仓库的资深后端工程师。本提示词是唯一任务来源：只按本提示词写代码，**不跑任何验收命令（pytest 一律不跑）**，**不执行任何 git 命令**。
> 红线：禁整文件重写；文件必须无 BOM；不得修改 `.env*`；不得删除任何既有文件；只改本提示词指定文件。

## 问题（审核方亲手跑 pytest 实测，2 failed / 814 passed）

`backend/tests/test_ai.py` 中两个新增用例断言失败，**实现代码 ai.py 无需改动**：

1. `TestExetypeIntegration::test_pr_not_polluted_by_other_exetype`（约 867 行）：
   断言 `"个人纪录（PR）负重：+80 kg"` 失败。
2. `TestExetypePromptHistoryRendering::test_plus_weight_history_pr_line_uses_plus_phrase`（约 912 行）：
   同一断言失败。

## 根因

`pr_weight` 是浮点（80.0），prompt 实际渲染为 `个人纪录（PR）负重：+80.0 kg`。
这与既有普通组渲染风格一致（既有用例断言的就是 `个人纪录（PR）重量：5.0 kg`，浮点原样）。
因此是**测试断言写错**，不是实现错。

## 修订内容（文件预算：仅改 backend/tests/test_ai.py，共 1 个文件）

把上述两处的断言字符串从 `个人纪录（PR）负重：+80 kg` 改为 `个人纪录（PR）负重：+80.0 kg`。
若同用例内还有其他对 PR 行的类似断言（如 `+90 kg` / `+80 kg` 形式），一并按实际浮点渲染修正。
不改 `backend/app/services/ai.py`。

## 交付纪律

完成后输出简短交付报告：改动行号与内容、确认未触碰 ai.py、红线确认（无 BOM/未跑 pytest/未跑 git）。
