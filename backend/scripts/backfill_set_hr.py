"""V4-9 存量逐组心率全量回填（手动触发，幂等可重跑，不进每日同步链路）。

用法：cd backend && ./.venv/Scripts/python.exe scripts/backfill_set_hr.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/

from app.db import make_engine, make_session_factory
from app.models import Workout
from app.services.set_hr import compute_workout_set_hr


def run_backfill(session, *, log=print) -> dict:
    """对全部「未软删 + 训记佳明双关联」workout 逐个重算逐组心率。

    幂等：compute_workout_set_hr 内部先删后插。单 workout 异常不影响整体
    （rollback 后继续）。返回统计 dict。
    """
    stats = {"scanned": 0, "with_rows": 0, "rows": 0, "no_data": 0, "failed": 0}
    workouts = (
        session.query(Workout)
        .filter(
            Workout.deleted_at.is_(None),
            Workout.xunji_train_id.isnot(None),
            Workout.garmin_activity_id.isnot(None),
        )
        .order_by(Workout.date, Workout.id)
        .all()
    )
    for w in workouts:
        stats["scanned"] += 1
        try:
            rows = compute_workout_set_hr(session, w)
        except Exception as exc:  # 单点失败不阻断全量
            session.rollback()
            stats["failed"] += 1
            log(f"[failed] workout {w.id} {w.date}: {exc!r}")
            continue
        if rows:
            stats["with_rows"] += 1
            stats["rows"] += len(rows)
            log(f"[ok] workout {w.id} {w.date} {w.title or ''}: {len(rows)} 组")
        else:
            stats["no_data"] += 1
    log(f"回填完成：{stats}")
    return stats


def main() -> int:
    engine = make_engine()
    session = make_session_factory(engine)()
    try:
        run_backfill(session)
    finally:
        session.close()
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
