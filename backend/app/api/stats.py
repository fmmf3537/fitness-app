"""V1 趋势统计 API：GET /api/stats/trends（前端图表数据）。"""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.auth import require_auth
from app.db import get_session
from app.models import BodyMetric, GarminDaily, Workout
from app.services import stats as stats_service

router = APIRouter(
    prefix="/api/stats",
    tags=["stats"],
    dependencies=[Depends(require_auth)],
)


@router.get("/trends")
def stats_trends(
    weeks: int = Query(default=4),
    session: Session = Depends(get_session),
) -> dict:
    """近 N 周趋势：周容量 / 部位频率 / 体重体脂 / 睡眠×容量。weeks 仅支持 4 或 12。"""
    if weeks not in (4, 12):
        raise HTTPException(status_code=422, detail="weeks 只支持 4 或 12")
    end = date.today()
    start = end - timedelta(days=weeks * 7 - 1)

    workout_rows = (
        session.query(Workout)
        .filter(Workout.date >= start, Workout.date <= end)
        .all()
    )
    workouts = [
        {"date": w.date, "movements": stats_service.parse_movements(w.movements_json)}
        for w in workout_rows
    ]
    weekly_volume, body_part_frequency = stats_service.weekly_trends(workouts, start, end)

    metric_rows = (
        session.query(BodyMetric)
        .filter(
            BodyMetric.date >= start,
            BodyMetric.date <= end,
            BodyMetric.type.in_(["weight", "bodyfat"]),
        )
        .order_by(BodyMetric.date)
        .all()
    )
    sleep_rows = (
        session.query(GarminDaily)
        .filter(
            GarminDaily.date >= start,
            GarminDaily.date <= end,
            GarminDaily.sleep_json.isnot(None),
        )
        .order_by(GarminDaily.date)
        .all()
    )

    return {
        "weeks": weeks,
        "weekly_volume": weekly_volume,
        "body_part_frequency": body_part_frequency,
        "body_metrics": stats_service.body_metrics_series(
            [(r.date, r.type, r.value) for r in metric_rows]
        ),
        "sleep_volume": stats_service.sleep_volume_series(
            [(r.date, r.sleep_json) for r in sleep_rows], workouts
        ),
    }
