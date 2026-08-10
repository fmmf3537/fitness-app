"""FastAPI 入口。"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.ai_reports import router as ai_reports_router
from app.api.auth import router as auth_router
from app.api.backfill import router as backfill_router
from app.api.llm import router as llm_router
from app.api.body_metrics import router as body_metrics_router
from app.api.match_candidates import router as match_candidates_router
from app.api.screenshot import router as screenshot_router
from app.api.settings import router as settings_router
from app.api.stats import router as stats_router
from app.api.sync import router as sync_router
from app.api.workouts import router as workouts_router
from app.api.writeback import router as writeback_router

_scheduler = None  # 模块级持引用，防止 GC


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _scheduler
    if os.getenv("SCHEDULER_ENABLED", "1") == "1":
        from app.scheduler import create_scheduler
        _scheduler = create_scheduler()
        _scheduler.start()
    yield


app = FastAPI(title="Fitness Hub", version="0.1.0", lifespan=lifespan)
app.include_router(auth_router)
app.include_router(sync_router)
app.include_router(workouts_router)
app.include_router(match_candidates_router)
app.include_router(settings_router)
app.include_router(llm_router)
app.include_router(stats_router)
app.include_router(ai_reports_router)
app.include_router(backfill_router)
app.include_router(writeback_router)
app.include_router(body_metrics_router)
app.include_router(screenshot_router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
