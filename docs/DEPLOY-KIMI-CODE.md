# Kimi Code 服务器一键部署提示词（含自动安全回滚）

适用于**已经在运行 Docker Compose 生产环境**的健身看板服务器。进入服务器项目目录（通常为 `~/fitness-app`），启动 Kimi Code，把下面整段一次性粘贴执行。

此版本包含：迟到数据补匹配/手动重新匹配、Kimi K3.1 Pro/K3 模型选择与模型级缓存计费；目标数据库 head 为 `f2a3b4c5d6e7`。

---

## 可直接粘贴的提示词

你现在是生产发布工程师。请在当前服务器项目目录中**直接完成本次生产更新，不要只给方案，不要中途等待我的确认**。目标是把现有 `main` 生产环境安全更新到 `origin/main`，并完成构建、数据库迁移、验证和结果报告。任何发布后的失败都必须自动回滚；任何发布前失败都必须保持旧服务不动并清楚报告。

### 一、不可违反的安全约束

1. 不修改、不重建、不回显 `.env` 中的任何值；尤其保护 `FERNET_KEY`、数据库口令、APP 口令和所有 API Key。日志、报告、临时脚本只能记录 `.env` 的 SHA-256，不能记录明文。
2. 禁止 `git push`、`git rebase`、merge 提交、删除未跟踪文件；服务器工作区不干净时，在改动前立即中止报告。
3. 禁止 `docker compose down -v`，禁止删除或重建 `pgdata`、`backups`、`garmin_tokens` 等卷，禁止 `--scale backend=2`。
4. 原样保留 `docker-compose.override.yml` 及现有端口/宿主机 Nginx 共存方式。根据实际运行方式验证 HTTP `:8080` 或 Caddy HTTPS，不要为了套模板改掉现有网络配置。
5. 不主动执行佳明登录，不反复重启 backend，不调用真实 LLM API，不触发历史回填或全量同步。
6. 不删除部署前备份、旧镜像回滚标签和日志。所有临时文件放在仓库外的本次专属目录，权限设为仅当前用户可访问。
7. 不声称未执行的检查已经通过。最终必须明确区分：部署成功、发布前中止、已回滚、回滚失败。

### 二、执行方式：必须是一个带自动回滚陷阱的脚本

先在仓库外创建本次运行目录，例如：

```bash
TS=$(date +%Y%m%d-%H%M%S)
RUN_DIR="$HOME/deploy-backups/fitness-$TS"
mkdir -p "$RUN_DIR"
chmod 700 "$RUN_DIR"
```

在该目录生成并执行**一个** Bash 部署脚本，使用 `set -Eeuo pipefail`，记录完整日志，并设置 `ERR` trap。不要在多个互不保留状态的 shell 调用中假装 trap 仍有效。脚本必须保存：

- `PREV_COMMIT`：部署前 `git rev-parse HEAD`；
- `ENV_BEFORE`：部署前 `.env` 的 SHA-256；
- `REV_BEFORE`：部署前 Alembic current；
- `OLD_BACKEND_IMAGE`、`OLD_FRONTEND_IMAGE`：部署前镜像 ID；
- `DB_BACKUP`：本次 PostgreSQL 自定义格式备份的文件名和绝对路径；
- `RELEASE_STARTED=0/1`：只有即将替换运行容器时才置为 1；
- 实际访问模式和应运行的服务列表（Caddy 是否由 override 禁用）。

脚本失败时按以下原则处理：

- `RELEASE_STARTED=0`：只中止；若代码已经 fast-forward，则恢复工作区到 `PREV_COMMIT`。旧容器未被动过，**不得恢复数据库**。
- `RELEASE_STARTED=1`：执行第六节的完整回滚，禁止只回滚代码而保留新数据库。

### 三、发布前只读检查

1. 确认当前目录是项目根，分支为 `main`，工作区干净，Docker 与 Compose 可用，postgres/backend/frontend/backup 正在运行。若这是全新服务器或核心容器未运行，中止并说明“需要首次部署”，不要套用更新流程。
2. 运行 `bash scripts/preflight.sh` 作为诊断。若唯一差异是既有 override 明确禁用 Caddy、宿主机合法占用 80/443 或使用 `:8080`，记录为已知模式；其他 FAIL、磁盘不足 5G、Compose 配置错误均中止。
3. 检查 `.env` 必填变量是否存在，但不得输出变量值。记录 `.env` 权限和哈希。
4. 读取当前 Compose 服务、镜像、Alembic 版本和磁盘空间。若存在多个 Alembic head，中止。
5. `git fetch origin main`，展示 `PREV_COMMIT..origin/main` 的提交和文件清单。若历史不能 fast-forward，中止。确认目标版本包含迁移 `f2a3b4c5d6e7_settings_llm_models.py`，否则中止，避免部署错版本。

### 四、不可跳过的安全快照

1. 将 `.env` 复制到 `$RUN_DIR/env.before`，`chmod 600`，并核对副本哈希与 `ENV_BEFORE` 一致。
2. 用 backup 容器生成带本次时间戳的**独立** `pg_dump --format=custom --no-owner` 备份，不能覆盖每日备份。复制到 `$RUN_DIR` 后：
   - 文件必须非空；
   - 必须在 backup 容器内用 `pg_restore --list` 验证可读；
   - 容器卷内文件与宿主机副本 SHA-256 必须一致；
   - 将备份绝对路径记录到报告。
3. 给当前 backend/frontend 镜像分别添加唯一回滚标签，例如：
   `fitness-hub-backend:rollback-$TS`、`fitness-hub-frontend:rollback-$TS`。验证标签指向 `OLD_*_IMAGE`。
4. 任一快照步骤失败都必须在发布前中止，禁止继续。

### 五、构建、发布和验证

1. 执行 `git pull --ff-only origin main`，记录 `NEW_COMMIT`；工作区必须干净。
2. 先运行 `docker compose build backend frontend`。构建期间旧容器继续服务；构建失败走发布前中止，不动数据库和旧容器。
3. 构建成功后，将 `RELEASE_STARTED=1`，记录发布时间，然后执行：
   `docker compose up -d --no-build backend frontend`，再按现有 override 用 `docker compose up -d` 补齐其他服务。
4. backend entrypoint 会自动执行 `alembic upgrade head`。最多等待约 2 分钟，采用有限间隔重试；若容器退出、迁移报错或日志出现本次新增 Traceback，立即进入回滚，不能无限等待。
5. 发布后必须全部满足：
   - 现有模式下应运行的容器均 running，backend 内部 `/health` 返回 ok；
   - 按实际模式验证 `:8080` 或 HTTPS 的 `/health` 和首页，健康检查成功且首页 HTTP 200；
   - `alembic current == alembic heads == f2a3b4c5d6e7`；
   - PostgreSQL `settings.llm_models_json` 列存在；
   - backend 中 Kimi 可选模型为 `kimi-k3.1-pro`、`kimi-k3.1-pro-highspeed`、`kimi-k3`，默认模型为 `kimi-k3.1-pro`；
   - frontend 最新静态 bundle 中包含 `kimi-k3.1-pro`，证明不是旧缓存镜像；
   - 本次发布后的 backend 日志无 migration error、Traceback 或启动失败；
   - `.env` 当前哈希仍等于 `ENV_BEFORE`；
   - `git rev-parse HEAD == NEW_COMMIT`，工作区干净。
6. 可运行 `bash scripts/preflight.sh --post` 补充验证，但既有 override 禁用 Caddy 时，要按实际模式判断，不能因“故意不运行 Caddy”误回滚。
7. 所有验证通过后，将 `RELEASE_STARTED=0` 并撤销 ERR trap，保留备份与回滚镜像，输出成功报告。不要主动做任何数据同步或真实 Kimi 调用。

### 六、发布失败后的完整自动回滚（必须实现）

回滚的语义是：**代码、数据库和运行镜像全部回到部署前快照**。因此回滚会丢弃快照之后、故障期间产生的写入；所以第一步必须停止前端和 backend 写入。不要以“新版只加一列”为由跳过数据库恢复。

1. 禁用原 ERR trap，防止回滚过程递归触发；记录回滚原因并保留新版本的失败日志。
2. `docker compose stop frontend backend`，保持 postgres 和 backup 可用。
3. 将 `$RUN_DIR` 中已校验的备份复制到 backup 容器临时路径，再执行：
   `pg_restore --clean --if-exists --no-owner --exit-on-error`，连接参数只使用 backup 容器已有环境变量，不明文写口令。
4. 若数据库恢复失败：**保持 frontend/backend 停止**，报告严重故障、备份路径和日志，禁止把失败的新版本重新拉起来，禁止反复恢复。
5. 数据库恢复成功后，`git reset --hard "$PREV_COMMIT"`；若 `.env` 哈希变化，仅从 `$RUN_DIR/env.before` 恢复并复核哈希。
6. 将部署前保存的 backend/frontend 回滚镜像重新标为 Compose 默认使用的 latest 镜像，再用 `docker compose up -d --no-build --force-recreate backend frontend` 启动旧镜像；按原 override 补齐其余服务。**不要依赖重新下载依赖或重新构建才能回滚。**
7. 回滚后重新验证：旧容器运行、内部与实际外部 `/health`、首页 200、Alembic current 回到 `REV_BEFORE`、旧代码 HEAD 等于 `PREV_COMMIT`、`.env` 哈希不变。
8. 回滚验证通过则以非零状态结束部署脚本并报告“已安全回滚”；回滚验证失败则报告“回滚后仍异常”，保留全部证据，禁止继续试错或反复重启。

### 七、最终报告（无论成功、中止或回滚都必须输出）

| 项目 | 必须报告的值 |
|---|---|
| 最终状态 | 成功 / 发布前中止 / 已安全回滚 / 回滚失败 |
| PREV_COMMIT → NEW_COMMIT | 完整哈希 |
| REV_BEFORE → REV_AFTER | 实际 Alembic 版本；成功时 AFTER 必须为 f2a3b4c5d6e7 |
| 数据库备份 | 绝对路径、大小、SHA-256、pg_restore --list 结果 |
| 旧镜像回滚标签 | backend/frontend 两个标签及对应镜像 ID |
| 构建与容器 | 实际结果 |
| 健康检查 | 内部与实际外部 URL、结果、首页 HTTP 状态 |
| 新版本专项检查 | settings 列、三个 Kimi 模型、前端 bundle |
| `.env` | 部署前后 SHA-256 是否一致，不得输出内容 |
| 回滚 | 是否触发、原因、代码/数据库/镜像/健康检查各自结果 |
| 证据目录 | `$RUN_DIR` 绝对路径 |

提示词结束。
