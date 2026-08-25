"""V2-7 手动同步后台执行管理器（复用 backfill 模式：内存状态 + 后台线程）。

纪律：
- 同一时刻只允许一个同步在跑，重复触发抛 SyncAlreadyRunningError（API 层转 409）；
- 后台线程内自建 DB 会话（sync_fn 不传 session，daily_sync 内部 SessionLocal 自建），
  不复用请求作用域会话；
- 同步结果/异常只落内存状态，不落库（job_run 已由 daily_sync 自己写）。
"""
from __future__ import annotations

import threading
from datetime import date, datetime
from typing import Callable

from app.services.sync import daily_sync


class SyncAlreadyRunningError(Exception):
    """已有同步在运行，对应 HTTP 409。"""


class SyncState:
    def __init__(self) -> None:
        self.running = False
        self.day: date | None = None
        self.user_id: int | None = None
        self.started_at: datetime | None = None
        self.finished_at: datetime | None = None
        self.status: str | None = None  # running / success / failed / None(从未运行)
        self.result: dict | None = None
        self.error: str | None = None


class SyncManager:
    """后台线程执行 daily_sync，内存保存当前/最近一次同步状态。"""

    def __init__(self, sync_fn: Callable[..., dict] = daily_sync) -> None:
        self._sync_fn = sync_fn
        self._lock = threading.Lock()
        self._state = SyncState()

    def start(self, day: date, user_id: int | None = None) -> dict:
        with self._lock:
            if self._state.running:
                raise SyncAlreadyRunningError("已有同步任务进行中")
            self._state = SyncState()
            self._state.running = True
            self._state.day = day
            self._state.user_id = user_id
            self._state.status = "running"
            self._state.started_at = datetime.now()
            thread = threading.Thread(
                target=self._run_safe, args=(day, user_id), daemon=True, name="manual-sync",
            )
            thread.start()
        return {"status": "started", "date": day.isoformat()}

    def _run_safe(self, day: date, user_id: int | None = None) -> None:
        try:
            result = self._sync_fn(day, user_id=user_id)
            with self._lock:
                self._state.result = result
                self._state.status = result.get("status", "success")
                self._state.error = result.get("error")
        except Exception as exc:  # noqa: BLE001 - 后台线程异常只落状态
            with self._lock:
                self._state.status = "failed"
                self._state.error = f"{type(exc).__name__}: {exc}"
        finally:
            with self._lock:
                self._state.running = False
                self._state.finished_at = datetime.now()

    def status(self) -> dict:
        with self._lock:
            s = self._state
            return {
                "running": s.running,
                "status": s.status,
                "date": s.day.isoformat() if s.day else None,
                "started_at": s.started_at.isoformat() if s.started_at else None,
                "finished_at": s.finished_at.isoformat() if s.finished_at else None,
                "error": s.error,
                "result": s.result,
            }


default_manager = SyncManager()
