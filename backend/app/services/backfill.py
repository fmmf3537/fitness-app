"""V1-2 历史数据全量导入（PRD US-5）。

纪律：
- 训记：从 BACKFILL_START_DATE（默认 2023-02-01）逐日回溯至今，请求间隔严格 15s
  （适配器限频装饰器按 datestr 维度计时，跨日期节奏由本服务保证）；
- 空训练日记入 backfill_progress(status='empty')，与 done 一样跳过不重拉；
- 佳明活动列表：全量分页（每页 100 条，页间 ≥0.5s 由适配器全局限速保证），
  页进度落 backfill_progress(source='garmin_activity', date='page:<offset>')；
- 佳明每日健康：仅从 BACKFILL_START_DATE 起（与训记对齐，控制 429 风险）；
- 全程单会话长拉取：整个 run 复用同一对适配器实例，绝不重复登录；
- 单日/单阶段容错：单日失败记 status='failed'（下次运行重试）继续后续日期，
  单阶段失败记入 state.errors 继续后续阶段，不得终止整个导入线程；
- 断点续传：重启后从最后一个未完成日期/页继续；
- 全部完成后自动对全部有数据的日期跑一遍 matcher+fuse；
- 进度加权：训记 70% / 佳明活动 10% / 佳明健康 15% / 融合 5%（活动总量不可预知，
  该段仅 0/1 二态，页数与活动数在 details 中单独展示）。
"""
from __future__ import annotations

import json
import threading
import time
from datetime import date, datetime, timedelta
from typing import Any, Callable

from sqlalchemy.orm import Session, sessionmaker

from app.models import BackfillProgress, GarminActivity, JobRun, XunjiTrain
from app.services.matcher import match_day

# 训记逐日回溯的请求间隔（PRD §5.3 读 15s）
XUNJI_DAY_INTERVAL_S = 15.0
# 佳明活动列表分页大小（任务约定：每页 100 条）
GARMIN_PAGE_SIZE = 100
# ETA 估算：佳明每日健康单日成本（4 次调用 × 0.5s 限速 + 余量）
GARMIN_DAILY_DAY_COST_S = 3.0

SOURCE_XUNJI = "xunji"
SOURCE_GARMIN_ACTIVITY = "garmin_activity"
SOURCE_GARMIN_DAILY = "garmin_daily"
SOURCE_FUSION = "fusion"

# 进度权重：训记 70% / 佳明活动 10% / 佳明健康 15% / 融合 5%
WEIGHTS = {"xunji": 0.70, "activities": 0.10, "daily": 0.15, "fusion": 0.05}

_DONE_STATUSES = ("done", "empty")


class BackfillState:
    """单次导入运行的内存状态（进度接口实时部分；持久进度在 backfill_progress 表）。"""

    def __init__(self) -> None:
        self.running = False
        self.phase = "idle"  # idle / xunji / garmin_activities / garmin_daily / fusion / done / error
        self.started_at: datetime | None = None
        self.finished_at: datetime | None = None
        self.error: str | None = None
        self.errors: list[str] = []
        self.xunji_done = 0
        self.xunji_failed = 0
        self.activity_pages = 0
        self.activities = 0
        self.daily_done = 0
        self.daily_failed = 0
        self.fusion_done = 0
        self.fusion_failed = 0
        self.fusion_total = 0

    def snapshot(self) -> dict:
        return {
            "xunji_done": self.xunji_done,
            "xunji_failed": self.xunji_failed,
            "activity_pages": self.activity_pages,
            "activities": self.activities,
            "daily_done": self.daily_done,
            "daily_failed": self.daily_failed,
            "fusion_done": self.fusion_done,
            "fusion_failed": self.fusion_failed,
            "fusion_total": self.fusion_total,
        }


class BackfillRunner:
    """一次完整的历史导入：训记 → 佳明活动 → 佳明健康 → 历史融合。

    session/xunji/garmin 由调用方构造（整个 run 复用，保证佳明单会话）；
    sleep/state/today 可注入以便测试。
    """

    def __init__(
        self,
        session: Session,
        xunji: Any,
        garmin: Any,
        *,
        start_date: date,
        today: date | None = None,
        page_size: int = GARMIN_PAGE_SIZE,
        sleep: Callable[[float], None] = time.sleep,
        state: BackfillState | None = None,
    ) -> None:
        self._session = session
        self._xunji = xunji
        self._garmin = garmin
        self._start = start_date
        self._today = today or date.today()
        self._page_size = page_size
        self._sleep = sleep
        self._state = state or BackfillState()

    # ---------- 主流程 ----------

    def run(self) -> dict:
        """按阶段执行；单阶段失败记录后继续，绝不因单日异常终止整个导入。"""
        state = self._state
        state.started_at = state.started_at or datetime.now()
        phases = [
            ("xunji", self._backfill_xunji),
            ("garmin_activities", self._backfill_activities),
            ("garmin_daily", self._backfill_daily),
            ("fusion", self._fuse_all),
        ]
        try:
            for phase_name, fn in phases:
                state.phase = phase_name
                try:
                    fn()
                except Exception as exc:  # 阶段级容错：记录后继续下一阶段
                    state.errors.append(f"{phase_name}: {exc}")
            state.phase = "done"
            status = "success" if not state.errors else "partial"
        except Exception as exc:  # pragma: no cover - 兜底，正常不会到这里
            state.phase = "error"
            state.error = str(exc)
            state.errors.append(f"fatal: {exc}")
            status = "failed"
        finally:
            state.finished_at = datetime.now()
        self._write_job_run(status)
        return {"status": status, "errors": list(state.errors), "detail": state.snapshot()}

    def _write_job_run(self, status: str) -> None:
        state = self._state
        run = JobRun(
            job_name="backfill",
            started_at=state.started_at,
            finished_at=datetime.now(),
            status=status,
            error="; ".join(state.errors) or None,
            detail_json=json.dumps(state.snapshot(), ensure_ascii=False, default=str),
        )
        self._session.add(run)
        self._session.commit()

    # ---------- 进度落库 ----------

    def _mark(self, source: str, date_key: str, status: str, detail: str | None = None) -> None:
        row = (
            self._session.query(BackfillProgress)
            .filter_by(source=source, date=date_key)
            .first()
        )
        if row is None:
            row = BackfillProgress(source=source, date=date_key)
            self._session.add(row)
        row.status = status
        row.detail = detail
        row.finished_at = datetime.now()
        self._session.commit()

    def _completed_dates(self, source: str) -> set[str]:
        rows = (
            self._session.query(BackfillProgress.date)
            .filter(BackfillProgress.source == source,
                    BackfillProgress.status.in_(_DONE_STATUSES))
            .all()
        )
        return {r[0] for r in rows}

    def _completed_page_offsets(self) -> set[int]:
        rows = (
            self._session.query(BackfillProgress.date)
            .filter_by(source=SOURCE_GARMIN_ACTIVITY, status="done")
            .all()
        )
        offsets = set()
        for (key,) in rows:
            if key.startswith("page:"):
                offsets.add(int(key.split(":", 1)[1]))
        return offsets

    # ---------- 阶段一：训记逐日回溯 ----------

    def _backfill_xunji(self) -> None:
        done = self._completed_dates(SOURCE_XUNJI)
        requested = False  # 本 run 是否已发过请求（首次请求前不睡）
        day = self._start
        while day <= self._today:
            ds = day.isoformat()
            if ds not in done:
                if requested:
                    self._sleep(XUNJI_DAY_INTERVAL_S)
                requested = True
                try:
                    trains = self._xunji.fetch_trains(ds)
                    self._mark(SOURCE_XUNJI, ds, "done" if trains else "empty")
                    self._state.xunji_done += 1
                except Exception as exc:  # 单日容错：记 failed 继续，次日重试交给下次运行
                    self._mark(SOURCE_XUNJI, ds, "failed", detail=str(exc))
                    self._state.xunji_failed += 1
            day += timedelta(days=1)

    # ---------- 阶段二：佳明活动全量分页 ----------

    def _backfill_activities(self) -> None:
        done_pages = self._completed_page_offsets()
        start_offset = 0
        while start_offset in done_pages:  # 连续已完成页 → 从最后未完成页继续
            start_offset += self._page_size
        skip_ids = {r[0] for r in self._session.query(GarminActivity.activity_id)}

        def on_page(start: int, count: int) -> None:
            self._mark(SOURCE_GARMIN_ACTIVITY, f"page:{start}", "done")
            self._state.activity_pages += 1

        self._state.activities += self._garmin.sync_all_activities(
            page_size=self._page_size,
            start_offset=start_offset,
            skip_ids=skip_ids,
            on_page=on_page,
        )
        self._mark(SOURCE_GARMIN_ACTIVITY, "all", "done")

    # ---------- 阶段三：佳明每日健康（与训记起点对齐） ----------

    def _backfill_daily(self) -> None:
        done = self._completed_dates(SOURCE_GARMIN_DAILY)
        day = self._start
        while day <= self._today:
            ds = day.isoformat()
            if ds not in done:
                try:
                    self._garmin.sync_daily(ds)
                    self._mark(SOURCE_GARMIN_DAILY, ds, "done")
                    self._state.daily_done += 1
                except Exception as exc:  # 单日容错：记 failed 继续
                    self._mark(SOURCE_GARMIN_DAILY, ds, "failed", detail=str(exc))
                    self._state.daily_failed += 1
            day += timedelta(days=1)

    # ---------- 阶段四：历史融合 ----------

    def _fuse_all(self) -> None:
        """对全部有原始数据的日期统一跑 matcher+fuse（幂等，可重复执行）。"""
        dates = {r[0] for r in self._session.query(XunjiTrain.datestr).all()}
        for (start_ts,) in self._session.query(GarminActivity.start_ts).filter(
            GarminActivity.start_ts.isnot(None)
        ):
            dates.add(start_ts.date().isoformat())
        days = sorted(dates)
        self._state.fusion_total = len(days)
        for ds in days:
            try:
                match_day(self._session, date.fromisoformat(ds))
                self._state.fusion_done += 1
            except Exception as exc:
                self._state.fusion_failed += 1
                self._state.errors.append(f"fusion {ds}: {exc}")
        self._mark(SOURCE_FUSION, "all", "done")


# ---------- 进度与 ETA ----------


def compute_status(
    session: Session,
    state: BackfillState,
    *,
    start_date: date,
    today: date | None = None,
) -> dict:
    """汇总 backfill_progress 表（持久）与 state（内存）计算进度百分比和 ETA。"""
    today = today or date.today()
    total_days = (today - start_date).days + 1

    def rows(source: str) -> list[BackfillProgress]:
        return session.query(BackfillProgress).filter_by(source=source).all()

    xunji_rows = rows(SOURCE_XUNJI)
    xunji_done = sum(1 for r in xunji_rows if r.status in _DONE_STATUSES)
    daily_rows = rows(SOURCE_GARMIN_DAILY)
    daily_done = sum(1 for r in daily_rows if r.status in _DONE_STATUSES)
    act_rows = rows(SOURCE_GARMIN_ACTIVITY)
    act_finished = any(r.date == "all" and r.status == "done" for r in act_rows)
    act_pages = sum(1 for r in act_rows if r.date.startswith("page:"))
    fusion_rows = rows(SOURCE_FUSION)
    fusion_finished = any(r.date == "all" and r.status == "done" for r in fusion_rows)

    if fusion_finished:
        fusion_frac = 1.0
    elif state.fusion_total:
        fusion_frac = state.fusion_done / state.fusion_total
    else:
        fusion_frac = 0.0

    percent = round(
        100.0
        * (
            WEIGHTS["xunji"] * (xunji_done / total_days)
            + WEIGHTS["activities"] * (1.0 if act_finished else 0.0)
            + WEIGHTS["daily"] * (daily_done / total_days)
            + WEIGHTS["fusion"] * fusion_frac
        ),
        1,
    )
    percent = min(percent, 100.0)
    eta_seconds = int(
        (total_days - xunji_done) * XUNJI_DAY_INTERVAL_S
        + (total_days - daily_done) * GARMIN_DAILY_DAY_COST_S
    )
    if percent >= 100.0:
        eta_seconds = 0

    return {
        "running": state.running,
        "phase": state.phase,
        "started_at": state.started_at.isoformat() if state.started_at else None,
        "finished_at": state.finished_at.isoformat() if state.finished_at else None,
        "error": state.error,
        "errors": list(state.errors),
        "percent": percent,
        "eta_seconds": eta_seconds,
        "details": {
            "xunji": {"done": xunji_done, "total": total_days},
            "garmin_activities": {
                "finished": act_finished,
                "pages": act_pages,
                "activities": state.activities,
            },
            "garmin_daily": {"done": daily_done, "total": total_days},
            "fusion": {"done": state.fusion_done, "total": state.fusion_total},
        },
    }


# ---------- 后台运行管理 ----------


class BackfillManager:
    """管理单例导入线程：POST /start 启动后台线程，GET /status 查询进度。"""

    def __init__(
        self,
        *,
        session_factory: sessionmaker | None = None,
        xunji_factory: Callable[[Session], Any] | None = None,
        garmin_factory: Callable[[Session], Any] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._session_factory = session_factory
        self._xunji_factory = xunji_factory
        self._garmin_factory = garmin_factory
        self._sleep = sleep
        self._state = BackfillState()
        self._lock = threading.Lock()

    def _sf(self) -> sessionmaker:
        if self._session_factory is None:
            from app.db import SessionLocal

            self._session_factory = SessionLocal
        return self._session_factory

    def start(self) -> dict:
        """启动后台导入线程；已在运行时不重复启动。导入全程后台执行，不阻塞服务。"""
        with self._lock:
            if self._state.running:
                return {"started": False, "message": "backfill 已在运行中"}
            self._state = BackfillState()
            self._state.running = True
            self._state.started_at = datetime.now()
            thread = threading.Thread(target=self._run_safe, daemon=True, name="backfill")
            thread.start()
            return {"started": True, "message": "backfill 已启动"}

    def _run_safe(self) -> None:
        session = self._sf()()
        try:
            from app.config import get_settings

            settings = get_settings()
            start = date.fromisoformat(settings.backfill_start_date or "2023-02-01")
            if self._xunji_factory is not None:
                xunji = self._xunji_factory(session)
            else:
                from app.adapters.xunji import XunjiClient

                xunji = XunjiClient(session)
            if self._garmin_factory is not None:
                garmin = self._garmin_factory(session)
            else:
                from app.adapters.garmin_adapter import GarminClient

                garmin = GarminClient(session)
            runner = BackfillRunner(
                session, xunji, garmin,
                start_date=start, sleep=self._sleep, state=self._state,
            )
            runner.run()
        except Exception as exc:  # 线程兜底：异常只落状态，绝不炸掉进程
            self._state.error = str(exc)
            self._state.errors.append(f"fatal: {exc}")
            self._state.phase = "error"
        finally:
            self._state.running = False
            self._state.finished_at = datetime.now()
            session.close()

    def status(self) -> dict:
        session = self._sf()()
        try:
            from app.config import get_settings

            settings = get_settings()
            start = date.fromisoformat(settings.backfill_start_date or "2023-02-01")
            return compute_status(session, self._state, start_date=start)
        finally:
            session.close()


default_manager = BackfillManager()
