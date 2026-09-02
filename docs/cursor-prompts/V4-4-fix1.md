# V4-4-fix1 修订提示词：消除 SettingsPage 双 role="alert" 冲突

> 你是本仓库的资深前端工程师。本提示词是唯一任务来源：只按本提示词写代码，**不跑任何验收命令（vitest 一律不跑）**，**不执行任何 git 命令**。
> 红线：禁整文件重写；文件必须无 BOM；不得修改 `.env*`；不得删除任何既有文件；只改本提示词指定文件。

## 问题（审核方亲手跑 vitest 实测：1 failed / 297 passed，36 文件过）

唯一失败：`SettingsPage.test.jsx > 设置加载失败显示错误提示`（既有用例，V4-4 之前一直通过）：
该用例把全部 fetch mock 成 500，然后 `await screen.findByRole('alert')`。

## 根因（已通过 git diff 实读定位）

V4-4 在 `frontend/src/pages/SettingsPage.jsx` 个人资料区给 profileLoadError 的 `<p>`
也加了 `role="alert"`（约 155 行）。当整页加载失败时，页顶错误横幅与 profileLoadError
**同时**渲染两个 `role="alert"`，`findByRole('alert')` 因匹配多个元素而拒绝。

## 修订内容（文件预算：仅改 frontend/src/pages/SettingsPage.jsx，共 1 个文件）

把 profileLoadError 那个 `<p role="alert" …>` 的 `role="alert"` 去掉，
改为 `data-testid="profile-load-error"`（其余 className/内容不变）。
页顶主错误横幅的 `role="alert"` 保持原样。
确认本仓库没有其他测试依赖 `profile-load-error` 的 role 语义（V4-4 新增的两个
profile 用例只查 input 值与保存文案，不受影响）。

## 交付纪律

完成后输出简短交付报告：改动行号与内容、确认未触碰其他文件、红线确认（无 BOM/未跑 vitest/未跑 git）。
