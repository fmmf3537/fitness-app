# B2 切片修复提示词：AIReportsPage 重新生成轮询加超时与取消标志

> 你是本仓库的资深前端工程师（React 19 + Vite 8 + Vitest）。本提示词是唯一任务来源：**只修一个具体 bug**，不跑任何验收命令（npm test / vitest 一律不跑），不执行任何 git 命令。
> 红线：禁整文件重写（外科式最小修改）；不得修改 `.env` / `.env.*` / `.env.example` / `.env.production.example`；不得删除任何既有文件；不得改动本提示词文件预算之外的任何文件。

## 必读上下文

修复前请先阅读：
- `PRD.md` §3 US-6（AI 单次点评的异步 + 完成通知）
- `docs/TECH_DEBT.md` §8 Sprint 5（V2-1 Kimi 接入 + AI 报告触发）
- `frontend/src/pages/AIReportsPage.jsx` 第 110-148 行（重点）

## 问题描述（已读源码核实，可直接采信）

`frontend/src/pages/AIReportsPage.jsx:119-148` 的 `handleRegenerate` 函数：

```jsx
try {
  await api('/api/ai-reports/session-review/regenerate', { method: 'POST', ... })
  // 轮询直至后台任务结束
  for (;;) {
    await new Promise((resolve) => setTimeout(resolve, REGEN_POLL_INTERVAL_MS))
    const st = await api(`/api/ai-reports/session-review/regenerate/status?date=${targetDate}`)
    if (!st.running) {
      if (st.error) setRegenError(st.error)
      break
    }
  }
  // ...后续更新选中报告
} catch (err) { ... }
```

### 实际后果

1. **`for(;;)` 无超时上限**：若后端 `running` 标志位卡在 `true`（OOM / 被 kill / 异常退出），前端会**永远每 3 秒调一次 status 接口**，耗电、耗 API 配额、UI 永远显示"重新生成中"
2. **无 cancelled flag**：组件卸载后 `setRegenError` / `setRegenerating` 等 setState 仍会触发，触发 React `setState on unmounted component` warning
3. **`st.error` 仅在 `st.running=false` 分支处理**：若 `running=true` 但有 error（后端可能上报运行中错误），会被忽略

### 已核实的相关事实

- `REGEN_POLL_INTERVAL_MS` 已在文件顶部定义为常量（应当是 3000ms，**实读时确认具体值**）
- `handleRegenerate` 当前用 `setRegenerating(true/false)` 控制 loading 态
- 组件内有 `useRef` 还是 `useState` 风格需实读确认（影响 cancelledRef 还是 cancelled state 的选择）
- 既有测试 `frontend/src/pages/__tests__/AIReportsPage.test.jsx`（409 行，目录已存在）——**不要求新增测试**（前端 lint 强度本就偏弱，本 bug 修复主路径风险低）

## 修复方案（仅此一个）

在 `handleRegenerate` 内：

1. **加 `MAX_POLLS = 60` 常量**（与 `REGEN_POLL_INTERVAL_MS` 同一区域，60 × 3s = 3 分钟上限）
2. **加 cancelled 标志**：
   ```jsx
   const cancelledRef = useRef(false)
   useEffect(() => {
     cancelledRef.current = false
     return () => { cancelledRef.current = true }
   }, [])
   ```
   组件卸载时设 true，handleRegenerate 在每次 setTimeout 醒来后检查
3. **替换 `for(;;)` 为带超时 + cancelled 检查的 while**：
   ```jsx
   let polls = 0
   while (polls++ < MAX_POLLS) {
     if (cancelledRef.current) break
     await new Promise((resolve) => setTimeout(resolve, REGEN_POLL_INTERVAL_MS))
     if (cancelledRef.current) break
     const st = await api(`/api/ai-reports/session-review/regenerate/status?date=${targetDate}`)
     if (st.error) { setRegenError(st.error); break }
     if (!st.running) break
   }
   if (polls >= MAX_POLLS) setRegenError('生成超时（超过 3 分钟），请稍后重试')
   ```
4. **catch 块也检查 cancelled**（避免卸载后报错触发 setRegenError）：
   ```jsx
   } catch (err) {
     if (cancelledRef.current) return
     setRegenError(err.status === 409 ? '该日期点评正在重新生成中，请稍候' : err.message || '重新生成失败')
   }
   ```

### 修复要点

1. **MAX_POLLS = 60**：3 分钟够一次 LLM 重生成（Kimi k2.6 思考模式最长约 1-2 分钟），再长就该报错而不是轮询
2. **`useRef` 而非 `useState`**：避免 cancelled 变化触发组件 re-render
3. **`useEffect` cleanup 设置 cancelled**：组件卸载 / 路由切换时立即标记，setTimeout 醒来后立即跳出
4. **catch 块提前 return**：避免组件卸载后 setRegenError 触发 React warning
5. **不动 `finally { setRegenerating(false) }`**：cancelled 不影响 loading 复位（loading 态属于 UI，不应跟随组件生命周期泄漏）

## 文件预算（共 1 个，不得越界）

改 1：
1. `frontend/src/pages/AIReportsPage.jsx`
   - 顶部 import 增加 `useRef`、`useEffect`（如果尚未引入）
   - 顶部常量区增加 `MAX_POLLS = 60`
   - 函数组件顶部增加 cancelled ref + cleanup effect
   - `handleRegenerate` 内 `for(;;)` 替换为 while
   - `catch` 块增加 cancelled 检查

不要修改：
- ❌ `frontend/src/api/client.js`（API 客户端不动）
- ❌ 其他任何 .jsx / .js
- ❌ 测试文件（不要求新增；本修复属低风险纯逻辑调整）
- ❌ `vite.config.js` / `vitest.config.js`
- ❌ 任何 .env 系列
- ❌ `backend/` 下任何文件

## 自报告要求（交付时必须给出）

1. **改动文件清单**：`frontend/src/pages/AIReportsPage.jsx`（注明行号 +diff 摘要，分块列：import / 常量 / ref / while / catch）
2. **设计取舍**：如有任何偏离本提示词之处（如用 setTimeoutId ref 替代 cancelledRef、降低 MAX_POLLS、改 409 文案等），必须显式列出并说明理由
3. **确认清单**：
   - 未跑 npm test / vitest
   - 未执行 git 命令
   - 未修改 .env 系列
   - 文件无 BOM
   - 未越界修改其他文件
4. **行为自检清单**（交付前自检，不跑实际测试）：
   - [ ] `useRef` 已 import
   - [ ] `useEffect` 已 import
   - [ ] `MAX_POLLS` 常量定义在 `REGEN_POLL_INTERVAL_MS` 附近
   - [ ] cancelledRef 在 cleanup 时设 true（不在 setState 中）
   - [ ] while 循环内至少 2 处 cancelled 检查（setTimeout 前 + API 调用前）
   - [ ] catch 块首行检查 cancelledRef.current
   - [ ] finally 块保留 `setRegenerating(false)` 不动