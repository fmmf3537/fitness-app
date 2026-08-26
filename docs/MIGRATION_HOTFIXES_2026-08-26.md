# multiuser-v2 数据迁移 Hotfix 记录（2026-08-26）

迁移单用户版 (main 分支 d605491) 的 509MB SQLite 数据库到 multiuser-v2
PostgreSQL 时发现并修复的 3 个 hotfix。已 commit 到 multiuser-v2 分支。

## 1. 登录后 useCurrentUser 死循环（commit 03d20d8）

**症状**：浏览器点击登录后一直在登录页面，进不去首页。

**根因**：`frontend/src/contexts/CurrentUserContext.jsx` 用 `useMemo([])` 只在
挂载时读一次 localStorage。`LoginPage` 调 `login()` 成功后 `setToken` 写
localStorage + `navigate('/')`，但 Provider 不感知后续 token 写入 →
`useCurrentUser()` 永远 `null` → `RequireAuth` 立刻跳回 `/login` → 死循环。

**修复**：
- `frontend/src/api/client.js`：加 `subscribeAuth()` / `notifyAuthChange()`，
  `setToken` / `clearToken` 时通知
- `frontend/src/contexts/CurrentUserContext.jsx`：改 `useSyncExternalStore`
  + module-level cached snapshot（避免 `getCurrentUser()` 每次返回新对象
  导致 `useSyncExternalStore` 的 `Object.is` 判等失败触发无限渲染）

## 2. sqlite→postgres 导入后 SERIAL 序列没刷（commit 782e53c）

**症状**：第一次 sync 报 `IntegrityError: duplicate key value violates unique
constraint "job_run_pkey"`，同步失败。

**根因**：`import_from_singleuser_sqlite.py` 用 `executemany` + `INSERT
... VALUES (...)` 显式指定 `id` 列，PostgreSQL SERIAL 序列在显式 INSERT
时不会自增。结果：表 `max(id) = N`，序列还在 1，业务代码用 `DEFAULT id` →
`nextval` 返回 1 → 跟导入的 id=1 冲突。

**修复**：新增 `backend/scripts/fix_postgres_sequences.py`，遍历所有有
`id` 列的表，`setval(pg_get_serial_sequence(t, 'id'), max(id))`。

**后续 follow-up**：可以合并到 `import_from_singleuser_sqlite.py` 作为
最后一步自动执行（避免重跑迁移的人忘记跑 setval）。

## 3. 系统级 cron 缺 user_id → XunjiKeyNotConfiguredError（commit acc9ef3）

**症状**：浏览器调"刷新"或 cron 跑 `health_check` / `sync_plan_cache` 时
报 `XunjiKeyNotConfiguredError: XUNJI_API_KEY 未配置（settings 表与环境
变量都没有）`。

**根因**：M3-2 把 `XunjiClient.__init__` 改 user_id kw-only（per-user 凭据
隔离），但 `app/services/sync.py` 的 `health_check()` 和 `sync_plan_cache()`
还在用老的"env 优先"模式：

```python
xunji = XunjiClient(session)  # user_id=None（kw-only 默认）
```

`_resolve_xunji_api_key(session, None)` → session+user_id 都不全 → 走 env
路径 → `.env` 没填 XUNJI_API_KEY（dev 简化版，真实 key 在 settings 表
per-user）→ raise。

**修复**：给 `health_check` / `sync_plan_cache` 加 `user_id: int = 1` kw-only
默认参数（系统级 cron 任务代表"系统"用 admin 凭据；未来用户多了应改成
M4-1 那种 `sync_all_users` 模式遍历所有 `is_active` 用户）。

测试兼容：`test_alerts.py` 2 个测试 mock 了 `xunji` / `garmin`，不传
`user_id`，行为兼容（mock 优先于 client 创建）。

## 未解决的外部问题

**容器访问 `trains.xunjiapp.cn:443` timeout**：

容器内 DNS 解析正常（121.43.244.197），TCP 连接 `api.xunjiapp.cn:443` 和
`baidu.com:443` 都 OK，但 `trains.xunjiapp.cn:443` 持续 TimeoutError。

**性质**：外部网络/路由问题（可能 Docker 默认 bridge 有 ACL 限制，或
该 IP 在大陆被 GFW 屏蔽），不是 multiuser-v2 代码 bug。

**建议**：
- 主机浏览器（不走 Docker bridge）访问 `https://trains.xunjiapp.cn/`
  应该 OK
- 部署到腾讯云 CVM 后再观察（云上容器网络更宽松）
- 临时 workaround：在 `docker-compose.yml` 给 backend 加
  `network_mode: host`，让容器共享主机网络栈

## 关联 commit

- `03d20d8` fix(frontend): 登录后 useCurrentUser 不刷新，死循环跳回 /login
- `782e53c` fix(migration): 补 setval 脚本 — import sqlite 后 postgres 序列需重置
- `acc9ef3` fix(sync): 系统级 cron 任务 (health_check / sync_plan_cache) 缺 user_id
