# GARMIN-P9 Cursor 服务器灰度执行提示词：部署、分阶段开放与回滚

> 使用位置：P7、P8 均已由 Deepseek Harness 验收通过，代码已经提交并推送后，在**生产服务器项目目录**由 Cursor 执行。
>
> 使用前替换：`<项目路径>`、`<目标提交完整哈希>`、`<站点URL>`、`<计划验收日期YYYY-MM-DD>`。本阶段是真实部署，不是本地开发；不得在本地电脑假装执行。

你是生产发布工程师。目标是把指定提交安全部署到现有 Docker Compose 环境，先关闭 Garmin 写入完成迁移和只读验证，再开放开关，由账号所有者确认一个真实训练日。不得只给方案，按门禁逐步执行；触发中止条件立即停止并保留证据。

## 1. 不可违反的红线

1. 禁止 `docker compose down -v`、删除/重建任何卷、删除备份、删除 P0–P6 或任何 Garmin 远端对象。
2. 禁止 scale backend、增加 uvicorn worker、修改 `docker-compose.override.yml`、Caddy/Nginx 共存方式或服务器网络配置。
3. 禁止 force push、rebase、merge commit、清理未跟踪文件；工作区不干净立即中止。
4. 不得读取/打印密码、token、Cookie、完整 `.env` 或完整进程环境。只允许备份 `.env` 并记录 SHA-256，以及定点修改 `GARMIN_PLAN_SYNC_ENABLED`，其他字节必须保持不变。
5. 不调用真实 LLM，不触发历史回填、全量训记同步或自动批量 Garmin 写入。
6. 不重复登录试探、不反复重启 backend；遇到 401/403/429 停止并报告，按 429 要求冷却。
7. 真实 Workout/日程创建只能来自用户在 `<计划验收日期>` 页面的一次明确确认。Cursor 不得自行选择另一天或直接调用创建接口。
8. 保留 P0–P6 对象，只允许只读回读 P6 `38224225 / 34841221` 验证新版认证，不得更新、改期或删除它们。

## 2. 前置门禁

实读 `docs/DEPLOY.md`、`docs/GARMIN-PLAN-SYNC-MIGRATION.md` 15.1/15.1.1/15.2、Compose 和 preflight。确认：

- 当前目录为 `<项目路径>`，目标为 `<目标提交完整哈希>`，站点为 `<站点URL>`。
- P7/P8 验收报告存在且为通过；目标提交包含 Python 3.12 镜像、Garmin Compose 配置、独立 token 卷和 P8 测试。
- 当前为既有生产环境，postgres/backend/frontend/backup 正常运行；Caddy 是否存在按 override 实际模式判断。
- `git status` 干净，`git fetch origin` 后目标提交存在，当前提交是目标祖先，目标是 `origin/main` 的祖先；只能 fast-forward。
- 当前 Alembic 只有一个 head；目标迁移链包含 `c5d6e7f8a9b0`。
- backend 当前及目标均为单副本。

任何条件不符立即中止，不得“先部署再看看”。

## 3. 回滚锚点与安全快照

在服务器仓库外创建权限 700 的本次运行目录，同时把脱敏报告索引写入仓库 `outputs/garmin_p9/`。记录：

- `PREV_COMMIT`、当前/目标 Alembic、当前 backend/frontend 镜像 ID、容器 StartedAt。
- `.env` 权限和 SHA-256，不记录内容。
- 实际访问模式、运行服务列表、backend 副本数。
- 给旧 backend/frontend 镜像添加本次唯一 rollback 标签。

用 backup 容器生成独立 PostgreSQL custom dump，复制到运行目录，验证非空、`pg_restore --list` 可读、容器内外 SHA-256 一致。任何备份步骤失败都不得替换运行容器。

## 4. 第一阶段：开关 0 部署

1. 若 `.env` 没有 `GARMIN_PLAN_SYNC_ENABLED`，保持 Compose 默认 0；若存在，使用不输出内容的脚本只把该行改为 0，保留权限和其他字节。记录修改前后哈希，不打印行内容。
2. `git merge --ff-only <目标提交完整哈希>`，确认 HEAD 精确等于目标。
3. 先 `docker compose build backend frontend`，超时至少 3600 秒；旧容器继续服务。构建失败不得动数据库和旧容器。
4. 构建成功后执行 `docker compose up -d --no-build backend frontend`，再按现有 override 用 `docker compose up -d` 补齐服务。允许 entrypoint 自动 `alembic upgrade head`，禁止手动 downgrade。
5. 验证：
   - 应运行容器全部 running，backend 单副本；内部与实际站点 `/health` 正常，首页 200。
   - `alembic current == heads == c5d6e7f8a9b0`。
   - PostgreSQL `garmin_plan_sync` 22 个字段和两个唯一约束存在。
   - Python >=3.12，`garminconnect==0.3.20`，`tzdata`/实际时区可核验。
   - 开关为 0、阈值为 900（或用户显式配置值），新旧 token 路径和卷均存在。
   - 最新前端 bundle 包含 Garmin 计划预览/顺延交互，无旧缓存。
   - 日志无本次新增 ERROR/Traceback；`bash scripts/preflight.sh --post` 按实际 IP/Caddy 模式判断。

## 5. 第二阶段：只读 Garmin 验证

只做一次必要认证，不循环重试：

1. 旧 garth：按 `docs/DEPLOY.md` 既有方法验证登录，确认旧 token 卷路径未变。
2. 新版 garminconnect：用 `GarminWorkoutAdapter.from_settings(get_settings())` 只读 `get_workout("38224225")` 和 `get_schedule("34841221")`，断言 ID、2026-11-19、来源键及关联正确。不得调用 create/update/schedule/reschedule。
3. 记录新版 token 文件仅路径、是否存在、大小和挂载信息，不读取内容。
4. 为验证重启持久化，在不提供密码的单个验证进程环境中使用保存 token 再次只读 P6 Workout；不得清空 backend 容器密码，不得把密码写入命令或报告。
5. 用户打开 `<计划验收日期>` Garmin 预览。确认页面 `remote_write_eligible=false`、没有确认写入按钮；预览前后本地 Garmin 同步记录数和远端对象不变。

只读验证失败：保持开关 0，不进入写入阶段。

## 6. 第三阶段：开放一次真实确认

1. 定点把 `.env` 的 `GARMIN_PLAN_SYNC_ENABLED` 改为 1，其他内容不变；`docker compose up -d --no-build --force-recreate backend` 使配置生效，再跑健康/preflight。
2. 向用户明确展示：站点、验收日期、动作/组次/重量/休息、将创建或更新的对象语义。等待用户在页面核对预览并**亲自点击一次确认**。不要代点，不要重复提交。
3. 轮询本地状态直到 synced/failed/conflict，记录实际 Workout ID、日程 ID、attempt 和 JobRun，不打印 payload 中的敏感信息。
4. 成功后只读回读该 Workout/日程：来源候选恰好 1 个、目标日日程恰好 1 个，名称、日期、动作、组次、重量、次数、休息和关联一致。
5. 以用户刚确认的相同 `source_hash` 做一次幂等 POST：必须 HTTP 200、`started=false`；前后 attempt、两个 ID、远端 updatedDate 和对象数量不得变化。若首次请求结果不确定，禁止盲目重发，先对账。
6. 请用户检查 Connect 和 FR955。自动化结果只能标为 `passed_pending_visual`，用户确认显示正常后才能标 `passed`。

## 7. 中止与回滚

- 任何迁移失败、健康检查失败、非预期文件差异、 token 泄漏、重复远端对象或无法解释的 Garmin 错误：立即停止新增写入。
- 能将开关定点改回 0 时先改回 0，保留本地同步记录和远端 ID，禁止自动删除“可能的重复对象”。
- 代码回滚使用第 3 步旧镜像和 `PREV_COMMIT`；新增表向后兼容，不自动 downgrade、不自动恢复整库，避免覆盖故障期间其他真实数据。
- 只有账号所有者明确批准后才允许使用备份恢复数据库或清理远端对象。
- 回滚后验证旧服务健康、HEAD、镜像、实际访问模式和 `.env` 哈希；除开关定点变化外不得有其他环境差异。

## 8. 最终报告

无论成功、中止或回滚，输出：

- 最终状态：成功待目视 / 完整成功 / 发布前中止 / 已停止写入 / 已回滚 / 回滚失败。
- 前后 commit、Alembic、镜像和备份路径/大小/SHA-256。
- 容器、健康、迁移 22 字段/2 约束、Python/库/时区、preflight 结果。
- 新旧 token 路径和持久化证据，不输出任何 secret。
- 开关 0 只读结果、预览零写入证据、开关 1 的真实日期和两个新 ID。
- 创建次数、远端唯一性、幂等 POST 前后 attempt/ID/updatedDate、Connect/FR955 用户状态。
- 是否回滚及原因、证据目录、剩余风险。不得声称未执行的步骤已通过。
