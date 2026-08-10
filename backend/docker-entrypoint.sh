#!/usr/bin/env bash
# 后端容器入口：先重放 Alembic 迁移（幂等），再启动 uvicorn。
set -euo pipefail

echo "[entrypoint] alembic upgrade head ..."
alembic upgrade head

echo "[entrypoint] starting uvicorn on 0.0.0.0:8000 ..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
