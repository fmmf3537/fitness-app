"""M6 训练档案看板 API：日历 + 详情（融合/训记原始/佳明原始 三视图）。"""
import calendar as _cal
import json
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.auth import require_auth
from app.db import get_session
from app.models import GarminActivity, Workout, XunjiTrain
from app.services.workouts import delete_workout, list_deleted_workouts, restore_workout

router = APIRouter(
    prefix="/api/workouts", tags=["workouts"],
    dependencies=[Depends(require_auth)],
)


def _parse_json(text: str | None):
    if not text:
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None


def extract_heart_rate_series(raw_json: str | None) -> list[dict]:
    """从佳明活动 raw_json 提取心率序列 [{t, hr}]。

    优先识别 garminconnect 活动详情的 metricDescriptors + activityDetailMetrics
    结构（真实返回中描述符字段名为 metricsIndex，兼容旧的 index）；
    其次尝试 heartRateDTOs 列表；兜底接受任意 key 含 heart 的纯数值列表。
    无数据返回 []。
    """
    raw = _parse_json(raw_json)
    if not isinstance(raw, dict):
        return []
    details = raw.get("details")
    if isinstance(details, dict):
        descriptors = details.get("metricDescriptors") or []
        rows = details.get("activityDetailMetrics") or []
        for d in descriptors:
            key = str(d.get("key") or "").lower()
            idx = d.get("metricsIndex")
            if not isinstance(idx, int):
                idx = d.get("index")
            if "heart" in key and isinstance(idx, int):
                series = [
                    r["metrics"][idx]
                    for r in rows
                    if isinstance(r, dict)
                    and isinstance(r.get("metrics"), list)
                    and len(r["metrics"]) > idx
                    and isinstance(r["metrics"][idx], (int, float))
                ]
                return [{"t": i, "hr": int(v)} for i, v in enumerate(series)]
        # 兜底一：heartRateDTOs 列表（部分活动类型直接返回该结构）
        hr_dtos = details.get("heartRateDTOs")
        if isinstance(hr_dtos, list):
            values = []
            for item in hr_dtos:
                if not isinstance(item, dict):
                    continue
                for k, v in item.items():
                    if "heart" in k.lower() and isinstance(v, (int, float)):
                        values.append(v)
                        break
            if values:
                return [{"t": i, "hr": int(v)} for i, v in enumerate(values)]
    # 兜底：summary/details 下任意 key 含 heart 的数值列表
    for container in (details, raw.get("summary")):
        if isinstance(container, dict):
            for k, v in container.items():
                if "heart" in k.lower() and isinstance(v, list) and v and all(
                    isinstance(x, (int, float)) for x in v
                ):
                    return [{"t": i, "hr": int(x)} for i, x in enumerate(v)]
    return []


@router.get("/calendar")
def workout_calendar(
    month: str = Query(pattern=r"^\d{4}-\d{2}$"),
    session: Session = Depends(get_session),
) -> dict:
    """月历数据：当月有训练的日子及其融合状态（PRD US-4 AC1）。"""
    year, mon = int(month[:4]), int(month[5:7])
    first = date(year, mon, 1)
    last = date(year, mon, _cal.monthrange(year, mon)[1])
    rows = (
        session.query(Workout)
        .filter(
            Workout.date >= first,
            Workout.date <= last,
            Workout.deleted_at.is_(None),
        )
        .order_by(Workout.date, Workout.id)
        .all()
    )
    days: dict[str, dict] = {}
    for w in rows:
        key = w.date.isoformat()
        days.setdefault(key, {"date": key, "workouts": []})["workouts"].append(
            {"id": w.id, "title": w.title, "match_status": w.match_status, "tags": w.tags}
        )
    return {"month": month, "days": list(days.values())}


@router.get("/deleted")
def workout_deleted_list(session: Session = Depends(get_session)) -> dict:
    """已删除训练列表（V3-11，供设置页恢复操作）。"""
    return {
        "workouts": [
            {
                "id": w.id,
                "date": w.date.isoformat(),
                "title": w.title,
                "match_status": w.match_status,
                "deleted_at": w.deleted_at.isoformat() if w.deleted_at else None,
            }
            for w in list_deleted_workouts(session)
        ]
    }


@router.get("/{workout_id}")
def workout_detail(workout_id: int, session: Session = Depends(get_session)) -> dict:
    """训练详情：融合视图 + 训记原始 + 佳明原始（PRD US-3 AC3 / US-4 AC2）。"""
    w = session.get(Workout, workout_id)
    if w is None or w.deleted_at is not None:
        raise HTTPException(status_code=404, detail="workout 不存在")
    train = session.get(XunjiTrain, w.xunji_train_id) if w.xunji_train_id else None
    activity = (
        session.get(GarminActivity, w.garmin_activity_id) if w.garmin_activity_id else None
    )
    garmin_raw = _parse_json(activity.raw_json if activity else None)
    return {
        "id": w.id,
        "date": w.date.isoformat(),
        "title": w.title,
        "match_status": w.match_status,
        "tags": w.tags,
        "duration_s": w.duration_s,
        "calories": w.calories,
        "avg_hr": w.avg_hr,
        "max_hr": w.max_hr,
        "movements": _parse_json(w.movements_json) or [],
        "heart_rate": extract_heart_rate_series(activity.raw_json if activity else None),
        "xunji_raw": _parse_json(train.raw_json if train else None),
        "garmin_raw": garmin_raw,
    }


@router.delete("/{workout_id}")
def workout_delete(workout_id: int, session: Session = Depends(get_session)) -> dict:
    """软删除一次训练（V3-11）：幂等，重复删除返回 200。"""
    w = delete_workout(session, workout_id)
    if w is None:
        raise HTTPException(status_code=404, detail="workout 不存在")
    return {"ok": True, "id": workout_id}


@router.post("/{workout_id}/restore")
def workout_restore(workout_id: int, session: Session = Depends(get_session)) -> dict:
    """恢复已删除的训练（V3-11）：不重建 AI 报告。"""
    w = restore_workout(session, workout_id)
    if w is None:
        raise HTTPException(status_code=404, detail="workout 不存在或未删除")
    return {"ok": True, "id": workout_id}
