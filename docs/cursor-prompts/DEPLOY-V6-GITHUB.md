# AI 辅助部署提示词 — 健身看板 V6（GitHub 驱动）

> 适用工具：Kimi Code / OpenCode / Cursor Agent / 任一 AI Coding CLI
> 部署架构：GitHub（代码托管） → 服务器（git pull + Docker Compose 部署）
> 最新版本：commit `d43a5a8`（UIX-09 暗色模式）

---

## 你的部署架构（已确认）

```
GitHub main 分支          服务器 /opt/fitness-app/
      │                         │
      │  push                   │  git pull origin main
      └────────────────────────►│
                                  │  docker compose up -d --build
                                  │
                              Docker 容器
                              (backend + frontend + postgres + caddy)
```

---

## 第 0 步：确认当前状态（部署前必须做）

把以下内容发给 AI，让它在**服务器上**执行：

```
请帮我执行以下命令，截图或复制所有输出给我：

1. 查看当前最新 commit（本地和 GitHub 对比）
```bash
cd /opt/fitness-app && git log --oneline -5
git log origin/main --oneline -5
```

2. 查看正在运行的容器
```bash
cd /opt/fitness-app && docker compose ps
```

3. 检查后端健康状态
```bash
curl -s http://localhost:8000/health 2>/dev/null || curl -s http://localhost:8080/health 2>/dev/null || echo "健康检查端点未响应"
```

4. 检查数据库记录数（确认数据完整）
```bash
docker compose exec postgres psql -U fitness -d fitness -c "SELECT COUNT(*) FROM workouts;" 2>/dev/null
```

5. 查看最近的 git pull 日期
```bash
cd /opt/fitness-app && git log --oneline -1 --format="%h %s (%ci)"
```

把以上 5 个命令的输出全部发给我，我来决定是否可以部署。
```

---

## 第 1 步：创建 GitHub Actions 部署工作流（如还没有）

如果你的 GitHub 仓库还没有自动部署工作流，让 AI 帮你创建：

```
请在本地仓库创建文件：.github/workflows/deploy.yml

内容如下（复制粘贴进去）：

```yaml
name: Deploy to Production

on:
  push:
    branches: [main]
  workflow_dispatch:  # 允许手动触发

jobs:
  deploy:
    name: Deploy to Server
    runs-on: ubuntu-latest
    environment: production

    steps:
      - name: Checkout code
        uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Deploy to server via SSH
        uses: appleboy/ssh-action@v1.0.3
        with:
          host: ${{ secrets.SERVER_HOST }}
          username: ${{ secrets.SERVER_USER }}
          key: ${{ secrets.SERVER_SSH_KEY }}
          port: ${{ secrets.SERVER_SSH_PORT || 22 }}
          envs: MAIN_DEPLOYMENT
          script: |
            set -e
            cd /opt/fitness-app

            # 备份数据库（部署前必须！）
            docker compose exec postgres pg_dump -U fitness -d fitness --data-only > /opt/backups/fitness_$(date +%Y%m%d_%H%M%S).sql
            echo "数据库备份完成"

            # 拉取最新代码
            git fetch origin main
            git reset --hard origin/main
            echo "代码已更新到: $(git log --oneline -1)"

            # 确定需要重建的服务（根据改动）
            BACKEND_CHANGED=$(git diff --name-only HEAD~1 HEAD | grep -E '^(backend/|app/|)')
            FRONTEND_CHANGED=$(git diff --name-only HEAD~1 HEAD | grep -E '^(frontend/src/|frontend/index.html)')

            if [ -n "$BACKEND_CHANGED" ]; then
              echo "Backend changed, rebuilding..."
              docker compose build backend
              docker compose up -d --no-deps backend
            fi

            if [ -n "$FRONTEND_CHANGED" ]; then
              echo "Frontend changed, rebuilding..."
              docker compose build frontend
              docker compose up -d --no-deps frontend
            fi

            if [ -z "$BACKEND_CHANGED" ] && [ -z "$FRONTEND_CHANGED" ]; then
              echo "Only docs/config changed, no rebuild needed"
            fi

            # 验证部署
            sleep 5
            curl -sf http://localhost:8000/health || curl -sf http://localhost:8080/health || echo "健康检查未通过"

            echo "部署完成，当前版本: $(git log --oneline -1)"
```

创建后执行：
```bash
git add .github/workflows/deploy.yml
git commit -m "feat: add GitHub Actions deployment workflow"
git push origin main
```
```

---

## 第 2 步：配置 GitHub Secrets（如还没有）

告诉 AI 需要配置的 secrets：

```
请帮我在 GitHub 仓库设置以下 Secrets（Settings → Secrets and variables → Actions）：

1. SERVER_HOST：服务器 IP 地址（如 1.2.3.4）
2. SERVER_USER：SSH 用户名（如 root 或 ubuntu）
3. SERVER_SSH_KEY：服务器的 SSH 私钥（cat ~/.ssh/id_rsa 的内容）
4. SERVER_SSH_PORT：SSH 端口（默认 22，如果改了的话）

配置方法：
1. 打开 GitHub 仓库 → Settings → Secrets and variables → Actions → New repository secret
2. 逐个添加上面的 secrets
3. SSH_KEY 那个要用多行文本粘贴，name 填 SERVER_SSH_KEY
```

---

## 第 3 步：服务器准备（如第一次配置部署）

让 AI 在服务器上执行：

```
请在服务器上执行以下命令：

1. 创建备份目录
```bash
sudo mkdir -p /opt/backups
sudo chmod 755 /opt/backups
```

2. 确保 SSH 公钥已授权（这样 GitHub Actions 能免密登录）
```bash
cat ~/.ssh/authorized_keys  # 看是否有内容
```

3. 如果没有 SSH 密钥对，创建一对：
```bash
ssh-keygen -t rsa -b 4096 -C "github-actions@fitness-app" -f ~/.ssh/id_rsa -N ""
cat ~/.ssh/id_rsa.pub >> ~/.ssh/authorized_keys
```

4. 把 ~/.ssh/id_rsa 的内容复制给我（我会配置到 GitHub Secrets）

5. 确认 Docker Compose 正常：
```bash
cd /opt/fitness-app && docker compose ps
```
```

---

## 第 4 步：执行部署（日常使用）

每次有新 commit 要部署时，让 AI 执行：

```
请帮我执行以下部署步骤：

1. 首先确认 GitHub 最新 commit：
```bash
git fetch origin
git log --oneline origin/main -3
```

2. 确认要部署的 commit 是 d43a5a8（UIX-09 暗色模式）或更新的 commit

3. 执行数据库备份：
```bash
cd /opt/fitness-app
docker compose exec postgres pg_dump -U fitness -d fitness --data-only > /opt/backups/fitness_$(date +%Y%m%d_%H%M%S).sql
ls -lh /opt/backups/fitness_*.sql | tail -3
```

4. 拉取最新代码：
```bash
cd /opt/fitness-app
git fetch origin main
git pull origin main
git log --oneline -3
```

5. 重建并启动服务：
```bash
cd /opt/fitness-app
docker compose up -d --build
```

6. 等待启动完成：
```bash
sleep 10
docker compose ps
```

7. 验证：
```bash
curl -sf http://localhost:8000/health 2>/dev/null || curl -sf http://localhost:8080/health 2>/dev/null || echo "健康检查失败"
docker compose exec backend alembic current
```

8. 验证数据库数据未丢失：
```bash
docker compose exec postgres psql -U fitness -d fitness -c "SELECT COUNT(*) FROM workouts;"
```

如果任何步骤报错，立即停止并告诉我。
```

---

## 第 5 步：手动触发 GitHub Actions 部署

如果你配置好了 GitHub Actions 工作流，用这个方式部署：

```
请帮我手动触发 GitHub Actions 部署：

1. 打开 GitHub 仓库：https://github.com/fmmf3537/fitness-app（或你的仓库地址）
2. 点击 Actions 标签
3. 点击左侧 "Deploy to Production"
4. 点击右侧 "Run workflow" 按钮
5. 选择 main 分支，点击绿色 "Run workflow"
6. 等待 workflow 运行完成（约 3-5 分钟）
7. 截图给我看运行结果

或者用 GitHub CLI：
```bash
gh workflow run deploy.yml --ref main
gh workflow run deploy.yml --watch
```
```

---

## 第 6 步：回滚方案（如果部署后出问题）

### 方案 A：回滚到上一个 commit（在服务器上执行）

```
如果部署后出现问题，让我执行回滚：

```bash
cd /opt/fitness-app

# 1. 停止当前服务
docker compose down

# 2. 恢复数据库（如果有数据问题）
docker exec -i $(docker compose ps -q postgres) psql -U fitness -d fitness < /opt/backups/fitness_20260914_120000.sql
# 注意：把文件名替换成最新的备份文件

# 3. 回滚到上一个稳定 commit
git revert --no-commit HEAD
git commit -m "revert: rollback problematic commit"
# 如果 revert 有冲突，用：
git checkout <上一个稳定commit> -- backend/ frontend/

# 4. 重建
docker compose up -d --build

# 5. 验证
curl -sf http://localhost:8000/health && echo "回滚成功"
```
```

### 方案 B：直接 checkout 到指定 commit

```
如果方案 A 复杂，直接告诉我：
- 要回滚到哪个 commit（例如 af62f7a）
- 我执行：
```bash
cd /opt/fitness-app
git checkout af62f7a -- backend/ frontend/
docker compose up -d --build backend frontend
docker compose logs --tail 20 backend
```
```

---

## 快速验证清单（部署后必做）

```
请帮我执行以下验证，把结果发给我：

1. 后端健康检查：
curl -s http://localhost:8000/health

2. 数据库记录数：
docker compose exec postgres psql -U fitness -d fitness -c "SELECT COUNT(*) FROM workouts;" -t

3. 最新 commit 确认：
cd /opt/fitness-app && git log --oneline -1

4. 容器状态：
docker compose ps

5. 前端可访问：
curl -sf -o /dev/null -w "%{http_code}" http://localhost/ || curl -sf -o /dev/null -w "%{http_code}" http://localhost:8080/
```

---

## 重要红线（任何部署操作必须遵守）

| 禁止操作 | 原因 |
|---------|------|
| ❌ `docker compose down -v` | 会删除数据库数据 |
| ❌ `docker compose down` 不带 `-v` 之后不 `up` | 服务下线 |
| ❌ 修改 `.env` 文件 | 服务器配置与 GitHub 不同 |
| ❌ `git push --force` | 覆盖 GitHub 历史 |
| ❌ 删除 `/opt/backups/` 目录 | 备份是回滚唯一保障 |
| ❌ `docker compose up --scale backend=2` | 后端 token/调度器必须单副本 |
| ✅ 部署前先备份数据库 | 永远在部署之前 |
| ✅ 部署后立即验证 | 早发现问题早回滚 |
| ✅ 只改 backend 或只改 frontend | 按改动范围重建，不贪多 |

---

## AI 部署助手完整提示词模板

把以下内容完整复制给 Kimi Code / OpenCode：

```
请帮我执行健身看板的最新版本部署（V6，commit d43a5a8）。

## 当前环境
- GitHub 仓库：你的仓库地址
- 服务器路径：/opt/fitness-app
- 部署方式：GitHub push → 服务器 git pull → docker compose up -d --build

## 我的需求
1. 首先帮我执行第 0 步，确认服务器当前状态（5 个检查命令）
2. 如果有 GitHub Actions deploy workflow，直接触发它（第 5 步）
3. 如果没有，执行第 4 步手动部署（服务器上 git pull + 重建）
4. 部署完成后执行验证清单
5. 如果有问题，执行第 6 步回滚

## 重要约束
- 数据库绝对不能丢（备份永远在部署之前）
- 只重建有改动的服务（backend 或 frontend，不要动 postgres）
- 任何步骤报错立即停止，问我怎么办
- 不碰 .env 文件
- 回滚方案我已经准备好（在第 6 步）
```

---

## GitHub Actions 部署工作流（完整代码）

如果你需要直接创建这个文件，这是完整内容：

```yaml
name: Deploy to Production

on:
  push:
    branches: [main]
  workflow_dispatch:  # 允许手动从 GitHub UI 触发

jobs:
  # 先跑测试，确保不部署坏代码
  test:
    name: Run Tests
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 20
          cache: npm
          cache-dependency-path: frontend/package-lock.json
      - run: npm ci
        working-directory: frontend
      - run: npx vitest run
        working-directory: frontend
      - run: npm run build
        working-directory: frontend

  deploy:
    name: Deploy to Server
    runs-on: ubuntu-latest
    needs: test  # 测试通过才部署
    if: github.ref == 'refs/heads/main'
    environment: production

    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Deploy to server via SSH
        uses: appleboy/ssh-action@v1.0.3
        with:
          host: ${{ secrets.SERVER_HOST }}
          username: ${{ secrets.SERVER_USER }}
          key: ${{ secrets.SERVER_SSH_KEY }}
          port: ${{ secrets.SERVER_SSH_PORT || 22 }}
          envs: MAIN_DEPLOYMENT
          debug: false
          command: |
            set -e
            cd /opt/fitness-app

            # ===== 部署前备份 =====
            BACKUP_FILE="/opt/backups/fitness_$(date +%Y%m%d_%H%M%S).sql"
            docker compose exec -T postgres pg_dump -U fitness -d fitness --data-only > "$BACKUP_FILE"
            echo "✅ 数据库已备份到: $BACKUP_FILE"

            # ===== 拉取最新代码 =====
            git fetch origin main
            CURRENT_COMMIT=$(git rev-parse HEAD)
            git reset --hard origin/main
            NEW_COMMIT=$(git log --oneline -1)
            echo "📦 代码更新: $CURRENT_COMMIT → $NEW_COMMIT"

            # ===== 确定重建范围 =====
            BACKEND_CHANGED=$(git diff --name-only $CURRENT_COMMIT..origin/main | grep -E '^(backend/|app/|alembic/|)')
            FRONTEND_CHANGED=$(git diff --name-only $CURRENT_COMMIT..origin/main | grep -E '^(frontend/)')

            echo "Backend 改动: ${BACKEND_CHANGED:-无}"
            echo "Frontend 改动: ${FRONTEND_CHANGED:-无}"

            # ===== 重建 =====
            if [ -n "$BACKEND_CHANGED" ]; then
              echo "🔨 重建 backend..."
              docker compose build backend
              docker compose up -d --no-deps backend
            fi

            if [ -n "$FRONTEND_CHANGED" ]; then
              echo "🔨 重建 frontend..."
              docker compose build frontend
              docker compose up -d --no-deps frontend
            fi

            if [ -z "$BACKEND_CHANGED" ] && [ -z "$FRONTEND_CHANGED" ]; then
              echo "ℹ️ 仅有配置/文档改动，无需重建容器"
            fi

            # ===== 验证 =====
            sleep 8
            HEALTH=$(curl -sf http://localhost:8000/health 2>/dev/null || curl -sf http://localhost:8080/health 2>/dev/null)
            if [ -z "$HEALTH" ]; then
              echo "❌ 健康检查失败"
              docker compose logs --tail 30 backend
              exit 1
            fi
            echo "✅ 健康检查通过: $HEALTH"

            # ===== Alembic 迁移确认 =====
            ALEMBIC_CURRENT=$(docker compose exec -T backend alembic current 2>/dev/null | tr -d '\n')
            echo "📋 Alembic 当前版本: $ALEMBIC_CURRENT"

            echo "🎉 部署完成！最新版本: $(git log --oneline -1)"
```

把这个保存到 `.github/workflows/deploy.yml`，然后：
```bash
git add .github/workflows/deploy.yml
git commit -m "feat: add GitHub Actions production deploy workflow"
git push origin main
```
