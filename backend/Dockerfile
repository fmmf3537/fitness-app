# 后端生产镜像（V2-5）：FastAPI + APScheduler + Alembic
# Garmin 写入依赖 garminconnect==0.3.20，要求 Python >=3.12
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# 容器时区数据（Compose 经 TZ 注入，默认 Asia/Shanghai）
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt -i https://mirrors.cloud.tencent.com/pypi/simple

# 含 app/（含 app/data/xunji_movements.json 静态数据）、alembic/、alembic.ini
COPY . .
RUN chmod +x docker-entrypoint.sh

EXPOSE 8000

# 启动前先重放迁移（alembic upgrade head），再起 uvicorn
ENTRYPOINT ["./docker-entrypoint.sh"]
