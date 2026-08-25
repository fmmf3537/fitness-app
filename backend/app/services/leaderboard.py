"""M5-1 排行榜服务：四指标计算 + leaderboard_cache 读写 + 23:30 预计算。

指标语义：
- frequency: days 内 workout 条数（COUNT）
- volume: days 内 SUM(duration_s)（训练秒数）
- calories: days 内 SUM(calories)
- streak: days 内 distinct 训练日期数（简化版，非严格连续 streak）

opt-out：settings.leaderboard_opt_out_json 形如
{"frequency": false, "volume": true} —— true 表示该指标退出排行。
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import LeaderboardCache, Setting, User, Workout

METRICS = ("frequency", "volume", "calories", "streak")
WINDOWS = ("7d", "30d")
WINDOW_DAYS = {"7d": 7, "30d": 30}


def _is_opted_in(session: Session, user_id: int, metric: str | None = None) -> bool:
    """用户是否参与排行榜（默认 True；settings 中对应 metric=true 则退出）。"""
    row = session.scalars(select(Setting).where(Setting.user_id == user_id)).first()
    if row is None or not row.leaderboard_opt_out_json:
        return True
    try:
        data = json.loads(row.leaderboard_opt_out_json)
    except (ValueError, TypeError):
        return True
    if isinstance(data, dict):
        if metric is None:
            # 全部指标都 True → 视为整体退出
            return not all(bool(data.get(m)) for m in METRICS)
        return not bool(data.get(metric, False))
    if isinstance(data, list):
        # 兼容：指标名列表，或（误用）user_id 列表
        if metric is None:
            return user_id not in data
        return metric not in data and user_id not in data
    return True


def _window_start(days: int, *, now: date | None = None) -> date:
    today = now or date.today()
    return today - timedelta(days=days - 1)


def _active_users(session: Session) -> list[User]:
    return list(
        session.scalars(select(User).where(User.is_active.is_(True)).order_by(User.id))
    )


def _rank_rows(rows: list[dict]) -> list[dict]:
    rows.sort(key=lambda r: r["value"], reverse=True)
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows


def compute_frequency(session: Session, days: int, *, now: date | None = None) -> list[dict]:
    """训练频率 = days 天内 workout 数量（按 user 聚合）。"""
    start = _window_start(days, now=now)
    end = now or date.today()
    rows: list[dict] = []
    for user in _active_users(session):
        if not _is_opted_in(session, user.id, "frequency"):
            continue
        count = session.scalar(
            select(func.count())
            .select_from(Workout)
            .where(
                Workout.user_id == user.id,
                Workout.deleted_at.is_(None),
                Workout.date >= start,
                Workout.date <= end,
            )
        ) or 0
        if count <= 0:
            continue
        rows.append({
            "user_id": user.id,
            "username": user.username,
            "value": int(count),
        })
    return _rank_rows(rows)


def compute_volume(session: Session, days: int, *, now: date | None = None) -> list[dict]:
    """总容量 = SUM(duration_s)（训练秒数）。"""
    start = _window_start(days, now=now)
    end = now or date.today()
    rows: list[dict] = []
    for user in _active_users(session):
        if not _is_opted_in(session, user.id, "volume"):
            continue
        total = session.scalar(
            select(func.coalesce(func.sum(Workout.duration_s), 0))
            .where(
                Workout.user_id == user.id,
                Workout.deleted_at.is_(None),
                Workout.date >= start,
                Workout.date <= end,
            )
        ) or 0
        if total <= 0:
            continue
        rows.append({
            "user_id": user.id,
            "username": user.username,
            "value": int(total),
        })
    return _rank_rows(rows)


def compute_calories(session: Session, days: int, *, now: date | None = None) -> list[dict]:
    """总热量 = SUM(calories)。"""
    start = _window_start(days, now=now)
    end = now or date.today()
    rows: list[dict] = []
    for user in _active_users(session):
        if not _is_opted_in(session, user.id, "calories"):
            continue
        total = session.scalar(
            select(func.coalesce(func.sum(Workout.calories), 0))
            .where(
                Workout.user_id == user.id,
                Workout.deleted_at.is_(None),
                Workout.date >= start,
                Workout.date <= end,
            )
        ) or 0
        if total <= 0:
            continue
        rows.append({
            "user_id": user.id,
            "username": user.username,
            "value": int(total),
        })
    return _rank_rows(rows)


def compute_streak(session: Session, days: int, *, now: date | None = None) -> list[dict]:
    """连续训练 streak（简化：days 内 distinct 训练日期数）。"""
    start = _window_start(days, now=now)
    end = now or date.today()
    rows: list[dict] = []
    for user in _active_users(session):
        if not _is_opted_in(session, user.id, "streak"):
            continue
        count = session.scalar(
            select(func.count(func.distinct(Workout.date)))
            .where(
                Workout.user_id == user.id,
                Workout.deleted_at.is_(None),
                Workout.date >= start,
                Workout.date <= end,
            )
        ) or 0
        if count <= 0:
            continue
        rows.append({
            "user_id": user.id,
            "username": user.username,
            "value": int(count),
        })
    return _rank_rows(rows)


_COMPUTE_FNS = {
    "frequency": compute_frequency,
    "volume": compute_volume,
    "calories": compute_calories,
    "streak": compute_streak,
}


def compute_metric(
    session: Session,
    metric: str,
    days: int,
    *,
    now: date | None = None,
) -> list[dict]:
    """统一入口。返回 [{user_id, username, value, rank}]，按 value 降序。"""
    if metric not in _COMPUTE_FNS:
        raise ValueError(f"未知 metric：{metric}")
    return _COMPUTE_FNS[metric](session, days, now=now)


def get_cached(session: Session, metric: str, window: str) -> list[dict] | None:
    """从 leaderboard_cache 表读。返回 None 表示未缓存。"""
    row = session.scalars(
        select(LeaderboardCache).where(
            LeaderboardCache.metric == metric,
            LeaderboardCache.window == window,
        )
    ).first()
    if row is None:
        return None
    try:
        return json.loads(row.payload_json)
    except (ValueError, TypeError):
        return None


def get_cached_row(session: Session, metric: str, window: str) -> LeaderboardCache | None:
    return session.scalars(
        select(LeaderboardCache).where(
            LeaderboardCache.metric == metric,
            LeaderboardCache.window == window,
        )
    ).first()


def save_cached(session: Session, metric: str, window: str, payload: list[dict]) -> None:
    """写或更新 leaderboard_cache 行（upsert）。"""
    row = session.scalars(
        select(LeaderboardCache).where(
            LeaderboardCache.metric == metric,
            LeaderboardCache.window == window,
        )
    ).first()
    payload_json = json.dumps(payload, ensure_ascii=False, default=str)
    now = datetime.now()
    if row is None:
        session.add(LeaderboardCache(
            metric=metric,
            window=window,
            payload_json=payload_json,
            computed_at=now,
        ))
    else:
        row.payload_json = payload_json
        row.computed_at = now
    session.commit()


def precompute_leaderboards(
    *,
    session: Session | None = None,
    now: date | None = None,
) -> dict:
    """每日 23:30 跑：4 指标 × 2 窗口 = 8 个缓存行。"""
    own_session = session is None
    session = session or SessionLocal()
    started_at = datetime.now()
    computed = 0
    failed: list[tuple[str, str, str]] = []
    try:
        for metric in METRICS:
            for window in WINDOWS:
                days = WINDOW_DAYS[window]
                try:
                    payload = compute_metric(session, metric, days, now=now)
                    save_cached(session, metric, window, payload)
                    computed += 1
                except Exception as exc:
                    failed.append((metric, window, str(exc)))
        detail = {
            "computed": computed,
            "failed": [{"metric": m, "window": w, "error": e} for m, w, e in failed],
        }
        # 复用 sync._write_job_run（不改 sync.py）
        from app.services.sync import _write_job_run

        _write_job_run(
            session,
            "precompute_leaderboards",
            started_at,
            {
                "status": "success" if not failed else "failed",
                "error": None if not failed else f"{len(failed)} combo(s) failed",
                "detail": detail,
            },
        )
        return detail
    finally:
        if own_session:
            session.close()
