"""M6 待确认队列 API：列出 pending 候选，合并/保持分开（PRD US-2 AC2）。"""
from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.auth import require_auth
from app.db import get_session
from app.models import GarminActivity, MatchCandidate, XunjiTrain
from app.services.fuse import fuse_workout

router = APIRouter(
    prefix="/api/match-candidates", tags=["match-candidates"],
    dependencies=[Depends(require_auth)],
)


class ResolveRequest(BaseModel):
    action: Literal["merge", "split"]


def _xunji_brief(t: XunjiTrain | None) -> dict | None:
    if t is None:
        return None
    return {
        "id": t.id, "datestr": t.datestr, "title": t.title,
        "start_ms": t.start_ms, "end_ms": t.end_ms,
    }


def _garmin_brief(g: GarminActivity | None) -> dict | None:
    if g is None:
        return None
    return {
        "id": g.id, "activity_id": g.activity_id,
        "activity_type": g.activity_type, "name": g.name,
        "start_ts": g.start_ts.isoformat() if g.start_ts else None,
        "end_ts": g.end_ts.isoformat() if g.end_ts else None,
        "duration_s": g.duration_s, "calories": g.calories,
        "avg_hr": g.avg_hr, "max_hr": g.max_hr,
    }


def _serialize(c: MatchCandidate, session: Session) -> dict:
    return {
        "id": c.id,
        "reason": c.reason,
        "status": c.status,
        "workout_id": c.workout_id,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "resolved_at": c.resolved_at.isoformat() if c.resolved_at else None,
        "xunji_train": _xunji_brief(
            session.get(XunjiTrain, c.xunji_train_id) if c.xunji_train_id else None
        ),
        "garmin_activity": _garmin_brief(
            session.get(GarminActivity, c.garmin_activity_id)
            if c.garmin_activity_id else None
        ),
    }


@router.get("")
def list_candidates(session: Session = Depends(get_session)) -> dict:
    """待确认队列（仅 pending）。"""
    rows = (
        session.query(MatchCandidate)
        .filter(MatchCandidate.status == "pending")
        .order_by(MatchCandidate.id)
        .all()
    )
    return {"candidates": [_serialize(c, session) for c in rows]}


@router.post("/{candidate_id}/resolve")
def resolve_candidate(
    candidate_id: int,
    req: ResolveRequest,
    session: Session = Depends(get_session),
) -> dict:
    """合并 → manual_matched 融合记录；保持分开 → 两侧各自成档。"""
    c = session.get(MatchCandidate, candidate_id)
    if c is None:
        raise HTTPException(status_code=404, detail="候选不存在")
    if c.status != "pending":
        raise HTTPException(status_code=409, detail="候选已处理")

    train = session.get(XunjiTrain, c.xunji_train_id) if c.xunji_train_id else None
    activity = (
        session.get(GarminActivity, c.garmin_activity_id) if c.garmin_activity_id else None
    )
    if train is not None:
        day = date.fromisoformat(train.datestr)
    elif activity is not None and activity.start_ts is not None:
        day = activity.start_ts.date()
    else:
        raise HTTPException(status_code=422, detail="候选缺少可定位日期的记录")

    workout_ids: list[int] = []
    if req.action == "merge":
        if train is None or activity is None:
            raise HTTPException(status_code=422, detail="缺少一侧记录，无法合并")
        w = fuse_workout(session, day, xunji=train, garmin=activity,
                         match_status="manual_matched")
        workout_ids.append(w.id)
        c.workout_id = w.id
        c.status = "merged"
    else:  # split
        if train is not None:
            workout_ids.append(
                fuse_workout(session, day, xunji=train, match_status="xunji_only").id
            )
        if activity is not None:
            # garmin_only_strength 候选在拆分前已有 garmin_only workout，避免重复建
            existing = c.workout_id
            if existing and train is None:
                workout_ids.append(existing)
            else:
                workout_ids.append(
                    fuse_workout(session, day, garmin=activity,
                                 match_status="garmin_only").id
                )
        c.status = "split"

    c.resolved_at = datetime.now()
    session.commit()
    return {"ok": True, "candidate": _serialize(c, session), "workout_ids": workout_ids}
