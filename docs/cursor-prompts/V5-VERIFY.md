# V5-VERIFY 切片验收提示词：AI 教练长期记忆 全栈验证

> 你是本仓库的资深全栈工程师，**严格按本提示词执行验收与体验检查**。不要修改任何代码（除非发现 P0 致命 bug）。所有验收步骤完成后输出交付报告。
> 红线：本次任务只跑命令 + 截图 + 写报告，不修改代码；不得改 .env；不得删除任何文件。

## 已核实的项目上下文（实读代码，可直接采信）

- 项目根：`D:\kimi\fitness-app`
- 后端 venv：`backend\.venv\Scripts\python.exe`
- 前端 npm：`frontend\node_modules`（如缺先 `npm ci`）
- 周转时间：本任务预计 10-15 分钟（含前后端测试与构建）

## V5 已上线 7 片（origin main 最新）

- V5-1 数据层：4 表 + 迁移 + CRUD + build_memory_section 纯函数
- V5-2 L2 每日批提炼 + 5 入口 L1+L2 prompt 注入
- V5-3 L3 长期统计（12 周聚合）+ 5 入口 L3 注入
- V5-5 教练须知独立页 + 草稿确认 UI（前端）
- V5-4 独立聊天 API + 服务（后端）
- V5-6 独立聊天页（前端）
- V5-7 报告页"参考记忆"提示（前端 + 后端薄改）

最近 8 个 commit hash（来源：`git log origin/main --oneline | Select-String V5-`）：
```
3c51521 feat(V5-7): 报告页"参考记忆"提示（前端 + 后端薄改）
2e9a666 feat(V5-6): 独立聊天页（前端）
d4803b2 feat(V5-4): 独立聊天（后端 API + 服务）
ad6a9fd feat(V5-5): 教练须知独立页 + 草稿确认 UI（前端）
a88ced1 feat(V5-3): L3 长期统计（12 周聚合）+ 5 入口 l3 注入
624dc1d feat(V5-2): L2 每日批提炼 + 5 入口 prompt 注入
b50f521 docs(V5-1): PRD-V5 + Cursor 切片提示词
6b74f9a feat(V5-1): 数据层（4 表 + 迁移 + CRUD + build_memory_section）
```

## 任务：完整验收 V5

按顺序执行 5 个验收步骤，每步输出结果。

### Step 1 · 后端 pytest 全套（必跑）

```bash
cd D:\kimi\fitness-app\backend
.\.venv\Scripts\python.exe -m pytest tests/ -q --no-header -p no:cacheprovider --tb=line 2>&1 | Tee-Object -FilePath D:\kimi\fitness-app\logs\cursor\verify-v5-backend.log | Out-Null
Get-Content D:\kimi\fitness-app\logs\cursor\verify-v5-backend.log -Tail 5
```

**预期**：
- `996 passed, 6 skipped`
- `Required test coverage of 85% reached. Total coverage: 92.33%`
- 耗时 ~5-8 分钟（首次跑含 alembic roundtrip 等）

如果失败：
- 记下失败模块 + 行号
- **不要自行修代码**，写入交付报告

### Step 2 · 前端 vitest 全套（必跑）

```bash
cd D:\kimi\fitness-app\frontend
npm test 2>&1 | Tee-Object -FilePath D:\kimi\fitness-app\logs\cursor\verify-v5-frontend.log | Out-Null
Get-Content D:\kimi\fitness-app\logs\cursor\verify-v5-frontend.log -Tail 10
```

**预期**：
- `Test Files` 全部通过
- `Tests` 数字 ≥ 325（原基线 312 + V5-5 加 9 + V5-6 加 8 = 329，加 V5-7 加 2 = ~331）

如果失败：
- 记下失败文件 + 用例名
- **不要自行修代码**

### Step 3 · 前端 build（必跑）

```bash
cd D:\kimi\fitness-app\frontend
npm run build 2>&1 | Tee-Object -FilePath D:\kimi\fitness-app\logs\cursor\verify-v5-build.log | Out-Null
Get-Content D:\kimi\fitness-app\logs\cursor\verify-v5-build.log -Tail 15
```

**预期**：
- `dist/` 目录生成
- `built in ~3s` 或类似
- 0 错误

如果失败：记下错误堆栈，不自行修。

### Step 4 · 启动 dev 手动浏览（必做）

#### 4.1 起后端

新开 PowerShell 终端 A：

```bash
cd D:\kimi\fitness-app\backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

预期看到：`Uvicorn running on http://0.0.0.0:8000`

#### 4.2 起前端

新开 PowerShell 终端 B：

```bash
cd D:\kimi\fitness-app\frontend
npm run dev
```

预期看到：`Local: http://localhost:5173/`

#### 4.3 浏览器手动验收（按顺序逐项）

打开 `http://localhost:5173`，用 `APP_PASSWORD=5213537`（你的 `.env` 里那个）登录。

| # | 操作 | 预期结果 | 通过？ |
|---|------|---------|--------|
| 1 | 看顶栏 / 底部 tab | 应有「教练须知」「跟教练聊聊」两个新入口 | ☐ |
| 2 | 点击「教练须知」 | 进入 `/coach-preferences` 页面，标题「教练须知」，右上角有「新建须知」按钮 | ☐ |
| 3 | 点击「新建须知」，填入测试内容（如"测试时膝盖不舒服"），tags 填"膝盖,伤病"，保存 | 弹窗关闭，列表显示新条目，显示 tags 标签 | ☐ |
| 4 | 点击刚创建条目的「编辑」，修改内容后保存 | 列表更新，无重复 | ☐ |
| 5 | 点击「删除」，确认 | 条目消失 | ☐ |
| 6 | 点击「跟教练聊聊」 | 进入 `/coach` 页面，显示空态文案"跟教练说点什么吧——" | ☐ |
| 7 | 输入"我深蹲膝盖疼，下周怎么调？" + 点击发送 | 列表追加 user 右气泡 + assistant 左气泡，含 Markdown 渲染 | ☐ |
| 8 | 滚到底部 | 自动滚动到底部，新消息可见 | ☐ |
| 9 | 输入"再问一下深蹲重量上限" + 回车 | 同样发送成功 | ☐ |
| 10 | 点击右上「清空对话」+ 确认 | 列表清空，显示空态 | ☐ |
| 11 | 回到 `/ai-reports` | 选择任意一条 session_review 报告 | ☐ |
| 12 | 查看报告详情卡 | 应显示「参考了 N 条须知 · M 条记忆 · K 项统计」（N/M/K 非 0） | ☐ |
| 13 | 点击报告下方追问 | 追问 thread 顶部应显示「AI 回答会参考你的长期记忆（须知 / 对话要点 / 训练统计）」提示 | ☐ |

每项用 ☐/☑ 记录结果。**截图保存到 `D:\kimi\fitness-app\logs\cursor\verify-v5-ux-*.png`**（关键 3 张：须知页新建、聊天页发送、报告页参考记忆提示）。

### Step 5 · 关停

```bash
# 两个终端 Ctrl+C
# 或：
Get-Process -Name "uvicorn" -ErrorAction SilentlyContinue | Stop-Process
Get-Process -Name "node" -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -match 'vite|next dev' } | Stop-Process
```

---

## 交付报告模板（必须按此格式输出）

```
## V5 验收报告 · YYYY-MM-DD

### Step 1 后端测试
- 结果：[pass/fail]
- passed: N / skipped: M / failed: K
- 覆盖率: X%
- 耗时: Ts
- 失败用例: （如有）

### Step 2 前端测试
- 结果：[pass/fail]
- 测试文件: N / 用例: M
- 失败用例: （如有）

### Step 3 前端 build
- 结果：[pass/fail]
- 耗时: Ts
- 错误: （如有）

### Step 4 UX 验收
- 后端启动: [pass/fail]（日志最后几行）
- 前端启动: [pass/fail]（日志最后几行）
- 13 项验收清单：
  1-13 各项 ☐/☑ + 简短说明

### Step 5 关停
- [pass/fail]

### 截图
- verify-v5-ux-prefs-create.png: [存在/缺失] + 描述
- verify-v5-ux-chat-send.png: [存在/缺失] + 描述
- verify-v5-ux-report-memory.png: [存在/缺失] + 描述

### 总体结论
- [✅ 全部通过 / ⚠️ 部分通过（说明）/ ❌ 失败（说明）]
- 建议后续动作: （如有）
```

执行（按 5 步走，不要省略任何步骤）；完成后按报告模板输出，不要漏字段。