# GARMIN-P7 Cursor 开发提示词：生产运行环境适配

> 你是本仓库的资深 DevOps / 后端工程师。只在本地工作区完成生产制品适配，**不部署、不启动生产容器、不执行 Git、不访问 Garmin、不运行 pytest / Docker build / Compose up**。Deepseek Harness 将独立验收。
>
> 红线：外科式最小修改；禁止修改真实 `.env`、任何凭据/token、数据库文件和既有迁移；禁止删除文件、卷或远端对象；禁止整文件重写；保持既有 `docker-compose.override.yml`、Caddy/IP 共存模式和旧 garth 读取路径不变。

## 1. 目标与已核实上下文

项目根：`D:\kimi\fitness-app`。

Garmin 写入已经在 Python 3.12.14 + `garminconnect==0.3.20` 下完成 P0–P6 真实验收。生产侧当前存在明确阻塞：

- `backend/Dockerfile` 仍为 `python:3.11-slim`；新版写入依赖只在 Python >=3.12 安装。
- `.github/workflows/ci.yml` 两个 Python 任务仍为 3.11。
- `docker-compose.yml` 未传递 `GARMIN_PLAN_SYNC_ENABLED`、`GARMIN_PLAN_SYNC_STALE_SECONDS`、`GARMIN_WORKOUT_TOKENSTORE`，也没有新版 token 的独立持久卷。
- 旧 garth 读取使用 `/root/.garminconnect`，必须原样保留；新版 token 不得与其混用。
- `backend/app/config.py` 已支持写入开关和 900 秒超时阈值；`backend/app/adapters/garmin_workout_adapter.py` 已支持 `GARMIN_WORKOUT_TOKENSTORE`，不需要改应用代码。
- `backend/requirements.txt` 已固定 `garminconnect==0.3.20; python_version >= "3.12"`，不需要改依赖文件。
- `backend/tests/test_deploy_production.py` 当前还断言 `python:3.11`，必须随制品更新。

开始前实读上述文件，以及 `docs/DEPLOY.md`、`scripts/preflight.sh`、`.env.example`、`.env.production.example`、`backend/docker-entrypoint.sh`。模板可以修改，真实 `.env` 绝对不可读、不可写。

## 2. 文件预算

只允许修改以下 7 个文件：

1. `backend/Dockerfile`
2. `.github/workflows/ci.yml`
3. `docker-compose.yml`
4. `.env.production.example`
5. `scripts/preflight.sh`
6. `docs/DEPLOY.md`
7. `backend/tests/test_deploy_production.py`

不得修改 `.env.example`（开发模板已有 Garmin 新配置）、`backend/requirements.txt`、应用服务代码、前端、Alembic 或任何测试数据。确需越界时停止并说明，不要自行扩预算。

## 3. 必须实现的改动

### 3.1 Python 3.12 与容器时区

- 后端基础镜像改为 `python:3.12-slim`。
- CI 的 backend 和 backend-postgres 两个任务均使用 Python 3.12，保留 PostgreSQL 16 服务容器和既有覆盖率门禁。
- 镜像以最小方式安装 Debian `tzdata`，清理 apt 缓存；Compose backend 显式传递 `TZ`，默认 `Asia/Shanghai`，允许部署者覆盖。
- 不改变 entrypoint 的 `alembic upgrade head` 和单进程 uvicorn 行为，不增加 worker/副本。

### 3.2 Compose Garmin 写入配置

backend environment 增加：

```yaml
GARMIN_PLAN_SYNC_ENABLED: ${GARMIN_PLAN_SYNC_ENABLED:-0}
GARMIN_PLAN_SYNC_STALE_SECONDS: ${GARMIN_PLAN_SYNC_STALE_SECONDS:-900}
GARMIN_WORKOUT_TOKENSTORE: ${GARMIN_WORKOUT_TOKENSTORE:-/var/lib/fitness/garmin-workout/tokens}
TZ: ${TZ:-Asia/Shanghai}
```

backend volumes 保留旧卷并新增：

```yaml
- garmin_tokens:/root/.garminconnect
- garmin_workout_tokens:/var/lib/fitness/garmin-workout
```

顶层 volumes 新增 `garmin_workout_tokens:`，不得重命名或删除 `garmin_tokens`。默认开关必须为 0；超时阈值只控制本地状态恢复，不得引入任何自动 Garmin 写入任务。

### 3.3 生产模板与部署文档

`.env.production.example` 补充上述开关、阈值、可选 tokenstore 和 `TZ` 的安全示例。默认 tokenstore 使用容器内路径，不放任何真实账号、密码或 token。

`docs/DEPLOY.md` 增加 Garmin Plan Sync 专用小节，至少说明：

1. 旧 garth token 与新版 garminconnect token 的路径和卷不同，不能互相复制。
2. 首次以开关 0 部署；健康检查、迁移和只读认证通过后才允许改为 1。
3. 开关变化需要重建 backend 使环境生效，但不能反复重启试探 Garmin。
4. 新版适配器只读认证/回读方法；命令不得打印密码、token、Cookie 或完整环境。
5. 预览、普通同步、顺延确认的安全语义；服务器不会自动批量写入。
6. 单 backend 副本、备份、回滚和 429 冷却要求。
7. 容器重建后新版 token 持久化验证方法。

### 3.4 Preflight

在 `scripts/preflight.sh` 增加非敏感检查，不改变既有检查语义：

- 部署前：开关若未设置应视为默认 0；阈值必须是正整数；`GARMIN_DOMAIN` 仍必须为 `garmin.cn`；tokenstore 若显式设置必须是绝对容器路径。
- `--post`：backend 内 Python >=3.12，`importlib.metadata.version("garminconnect") == "0.3.20"`；Garmin 三项环境存在；tokenstore 父目录存在且可写；旧 `/root/.garminconnect` 挂载仍存在；backend 仅 1 个副本；输出 `date` / `%Z` 供时区核验。
- 不得读取或打印 token 文件内容，不得用 `env`、`set`、`printenv`  Dump 环境，不得因为开关为 0 而失败。

### 3.5 部署静态测试

更新 `backend/tests/test_deploy_production.py`：

- Python 3.11 断言改为 3.12，并检查 `tzdata`。
- 断言 Compose 包含三个 Garmin 变量、默认开关 0、独立新卷、旧卷保持、`TZ`。
- 断言生产模板和部署文档包含新配置与分阶段开放说明。
- 断言 preflight 包含 Python/库版本、token 可写和单副本检查。
- 不启动 Docker、不访问网络，不读取真实 `.env`。

## 4. 明确不做

- 不实现首次“日期与内容同时变化”的自动关联。
- 不平移 garth 读取，不删除 garth。
- 不实现自动批量 Garmin 同步、自动改期或删除。
- 不修复 P8 的 PostgreSQL 测试或 AI 限流问题。
- 不执行服务器部署，不创建 Garmin 对象。

## 5. 开发自报告

最终报告必须包含：

1. 7 个预算文件的实际改动清单、位置和用途；若有未改文件也说明。
2. Compose 默认开关、两个 token 路径、两个卷和时区值。
3. preflight 新增检查清单及敏感信息保护方式。
4. 明确确认：未跑 pytest/Docker/Compose up、未执行 Git、未访问 Garmin、未读取或修改真实 `.env`、未改应用逻辑和迁移。
5. 列出需要 Deepseek Harness 实际执行的 Linux 镜像构建、Compose 配置和测试结果，不得预先声称通过。
