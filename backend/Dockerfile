# 后端生产镜像（V2-5）：FastAPI + APScheduler + Alembic
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 含 app/（含 app/data/xunji_movements.json 静态数据）、alembic/、alembic.ini
COPY . .
RUN chmod +x docker-entrypoint.sh

EXPOSE 8000

# 启动前先重放迁移（alembic upgrade head），再起 uvicorn
ENTRYPOINT ["./docker-entrypoint.sh"]
