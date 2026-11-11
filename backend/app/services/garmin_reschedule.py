"""训记未训练顺延的本地检测、确认改期和故障恢复。

预览与检测不访问网络；只有确认 POST 启动的 runner 会调用 Garmin。
改期只更新已关联 Workout 和日程，绝不创建、替换或删除远端对象。
"""
from __future__ import annotations

import json
import threading
from datetime import date, datetime, timedelta
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.adapters.garmin_workout_adapter import (
    GarminWorkoutAdapter,
    GarminWorkoutAdapterError,
)
from app.models import GarminPlanSync, JobRun
from app.services import exercise_mapping as mapping_service
from app.services.garmin_plan_sync import (
    ACTIVE_RESCHEDULE_STATUSES,
    PlanSyncConflict,
    PlanSyncError,
    _description_marker,
    _schedule_workout_id,
    get_sync_record,
    recover_stale_syncing,
    source_key_for,
    sync_status_view,
)
from app.services.garmin_workout_mapper import (
    content_hash as calculate_content_hash,
    expand_workout,
    map_plan_day,
    source_hash as calculate_source_hash,
)
from app.services.plans import list_cached_plan_days, query_plan_day

RESCHEDULE_CONFLICT_MESSAGES = {
    "RESCHEDULE_CANDIDATE_AMBIGUOUS": "顺延候选不唯一，请人工核对原训练与目标日期",
    "RESCHEDULE_TARGET_CONFLICT": "目标日期已有其他同步记录，未自动覆盖或改期",
    "RESCHEDULE_TARGET_MISSING": "原顺延目标已消失，请重新刷新计划并人工核对",
}


def _assign(record: GarminPlanSync, **values: Any) -> bool:
    changed = False
    for name, value in values.items():
        if getattr(record, name) != value:
            setattr(record, name, value)
            changed = True
    return changed


def _plan_groups(plan_days: list[dict]) -> dict[tuple[str, date], list[dict]]:
    groups: dict[tuple[str, date], list[dict]] = {}
    for plan_day in plan_days:
        key = (plan_day["plan_ref"], date.fromisoformat(plan_day["date"]))
        groups.setdefault(key, []).append(plan_day)
    return groups


def _is_reschedule_conflict(record: GarminPlanSync) -> bool:
    return (
        record.status == "conflict"
        and record.error_code in RESCHEDULE_CONFLICT_MESSAGES
    )


def _set_conflict(
    record: GarminPlanSync, *, target_date: date, error_code: str
) -> None:
    _assign(
        record,
        status="conflict",
        phase="reschedule",
        reschedule_to_date=target_date,
        error_code=error_code,
        last_error=RESCHEDULE_CONFLICT_MESSAGES[error_code],
    )


def reschedule_candidate_view(
    record: GarminPlanSync, plan_day: dict | None = None
) -> dict:
    """返回脱敏候选；原 source_hash/source_key 仍属于原日期，不伪装已改期。"""
    target_date = record.reschedule_to_date
    current_source_hash = (
        calculate_source_hash(plan_day) if plan_day is not None else record.source_hash
    )
    current_content_hash = (
        calculate_content_hash(plan_day)
        if plan_day is not None
        else record.content_hash
    )
    return {
        "id": record.id,
        "status": record.status,
        "plan_ref": record.plan_ref,
        "title": plan_day.get("title") if plan_day is not None else None,
        # 活动候选始终从当前同步日期出发；审计字段可能仍属于上一轮改期。
        "from_date": record.training_date.isoformat(),
        "to_date": target_date.isoformat() if target_date else None,
        "source_key": (
            source_key_for(record.plan_ref, target_date)
            if target_date is not None
            else record.source_key
        ),
        "source_hash": current_source_hash,
        "previous_source_hash": (
            record.synced_hash
            if record.phase == "reschedule" and record.synced_hash
            else record.source_hash
        ),
        "content_hash": current_content_hash,
        "workout_id": record.workout_id,
        "workout_schedule_id": record.workout_schedule_id,
        "previous_workout_schedule_id": record.previous_workout_schedule_id,
        "error_code": record.error_code,
        "last_error": record.last_error,
        "attempt_count": record.attempt_count,
    }


def detect_reschedule_candidates(session: Session) -> dict:
    """刷新本地顺延候选，唯一匹配才进入 reschedule_pending。

    首次关联只接受同 plan_ref、原日期消失、次日出现且 content_hash 相同。
    已关联候选允许目标日内容继续变化，由后续确认预览展示更新；本函数不生成
    新 Workout payload，不改 training_date/source_key/source_hash/synced_hash。
    """
    plan_days = list_cached_plan_days(session)
    groups = _plan_groups(plan_days)
    records = session.query(GarminPlanSync).all()
    record_by_date = {
        (record.plan_ref, record.training_date): record for record in records
    }
    backfilled = 0
    changed_records = 0

    for record in records:
        is_pending = record.status == "reschedule_pending"
        is_conflict = _is_reschedule_conflict(record)
        if record.status != "synced" and not is_pending and not is_conflict:
            continue
        if (
            not record.synced_hash
            or not record.workout_id
            or not record.workout_schedule_id
        ):
            continue

        old_key = (record.plan_ref, record.training_date)
        old_candidates = groups.get(old_key, [])
        if len(old_candidates) == 1:
            old_day = old_candidates[0]
            if record.content_hash is None:
                backfilled += 1
            changed = _assign(
                record, content_hash=calculate_content_hash(old_day)
            )
            if is_pending or is_conflict:
                changed = _assign(
                    record,
                    status="synced",
                    phase="verify",
                    reschedule_to_date=None,
                    error_code=None,
                    last_error=None,
                ) or changed
            changed_records += int(changed)
            # 原日期仍在缓存中：同日内容变化走普通更新，不误判为顺延。
            continue

        if record.content_hash is None:
            # 旧记录且原日期已消失时没有可靠内容证据，绝不猜测关联。
            continue

        target_date = (
            record.reschedule_to_date
            if (is_pending or is_conflict) and record.reschedule_to_date
            else record.training_date + timedelta(days=1)
        )
        target_key = (record.plan_ref, target_date)
        target_candidates = groups.get(target_key, [])

        if len(old_candidates) > 1 or len(target_candidates) > 1:
            before = (record.status, record.error_code, record.reschedule_to_date)
            _set_conflict(
                record,
                target_date=target_date,
                error_code="RESCHEDULE_CANDIDATE_AMBIGUOUS",
            )
            changed_records += int(
                before != (record.status, record.error_code, record.reschedule_to_date)
            )
            continue

        if not target_candidates:
            if is_pending or is_conflict:
                before = (record.status, record.error_code, record.reschedule_to_date)
                _set_conflict(
                    record,
                    target_date=target_date,
                    error_code="RESCHEDULE_TARGET_MISSING",
                )
                changed_records += int(
                    before
                    != (record.status, record.error_code, record.reschedule_to_date)
                )
            # 初次检测没有唯一次日候选时保持原状态，可能是计划删除或缓存不全。
            continue

        target_record = record_by_date.get(target_key)
        if target_record is not None and target_record.id != record.id:
            before = (record.status, record.error_code, record.reschedule_to_date)
            _set_conflict(
                record,
                target_date=target_date,
                error_code="RESCHEDULE_TARGET_CONFLICT",
            )
            changed_records += int(
                before != (record.status, record.error_code, record.reschedule_to_date)
            )
            continue

        target_day = target_candidates[0]
        target_content_hash = calculate_content_hash(target_day)
        if record.status == "synced" and target_content_hash != record.content_hash:
            # 没有既有顺延关联时，跨日且内容也不同不能证明是同一训练。
            continue

        changed = _assign(
            record,
            status="reschedule_pending",
            phase="reschedule",
            reschedule_to_date=target_date,
            content_hash=target_content_hash,
            error_code=None,
            last_error=None,
        )
        changed_records += int(changed)

    session.commit()
    candidates = [
        record for record in records if record.status == "reschedule_pending"
    ]
    conflicts = [record for record in records if _is_reschedule_conflict(record)]
    items = [
        reschedule_candidate_view(
            record,
            (groups.get((record.plan_ref, record.reschedule_to_date)) or [None])[0],
        )
        for record in candidates
    ]
    return {
        "pending": len(items),
        "conflicts": len(conflicts),
        "backfilled": backfilled,
        "changed_records": changed_records,
        "items": items,
    }


def list_reschedule_candidates(session: Session) -> list[dict]:
    """列出待确认及可恢复的活动顺延；仅做本地超时恢复，不访问 Garmin。"""
    groups = _plan_groups(list_cached_plan_days(session))
    records = (
        session.query(GarminPlanSync)
        .filter(
            GarminPlanSync.phase == "reschedule",
            GarminPlanSync.status.in_(ACTIVE_RESCHEDULE_STATUSES),
        )
        .order_by(GarminPlanSync.reschedule_to_date, GarminPlanSync.id)
        .all()
    )
    for record in records:
        recover_stale_syncing(session, record)
    return [
        reschedule_candidate_view(
            record,
            (groups.get((record.plan_ref, record.reschedule_to_date)) or [None])[0],
        )
        for record in records
    ]


def _unique_target_plan(
    session: Session, *, plan_ref: str, target_date: date
) -> dict:
    matches = [
        item
        for item in list_cached_plan_days(session)
        if item["plan_ref"] == plan_ref
        and item["date"] == target_date.isoformat()
    ]
    if not matches:
        raise PlanSyncError(
            404,
            "RESCHEDULE_TARGET_MISSING",
            "顺延目标计划已消失，请刷新计划后重新核对",
        )
    if len(matches) != 1:
        raise PlanSyncError(
            409,
            "RESCHEDULE_CANDIDATE_AMBIGUOUS",
            RESCHEDULE_CONFLICT_MESSAGES["RESCHEDULE_CANDIDATE_AMBIGUOUS"],
        )
    return matches[0]


def _target_plan_for_request(session: Session, target_date: date) -> dict:
    plan_day = query_plan_day(session, target_date)
    if plan_day is None:
        raise PlanSyncError(
            404,
            "RESCHEDULE_TARGET_MISSING",
            "顺延目标日期没有训练计划，请刷新后重新核对",
        )
    return _unique_target_plan(
        session, plan_ref=plan_day["plan_ref"], target_date=target_date
    )


def _completed_reschedule(
    session: Session,
    *,
    plan_ref: str,
    from_date: date,
    target_date: date,
    expected_source_hash: str,
) -> GarminPlanSync | None:
    """按审计字段识别成功后的旧地址重放，不依赖 JobRun JSON。"""
    return (
        session.query(GarminPlanSync)
        .filter(
            GarminPlanSync.plan_ref == plan_ref,
            GarminPlanSync.training_date == target_date,
            GarminPlanSync.reschedule_from_date == from_date,
            GarminPlanSync.reschedule_to_date == target_date,
            GarminPlanSync.source_hash == expected_source_hash,
            GarminPlanSync.status == "synced",
        )
        .first()
    )


def _validate_active_record(
    session: Session,
    *,
    plan_ref: str,
    from_date: date,
    target_date: date,
) -> GarminPlanSync:
    record = get_sync_record(
        session, plan_ref=plan_ref, training_date=from_date
    )
    if (
        record is None
        or record.phase != "reschedule"
        or record.reschedule_to_date != target_date
    ):
        raise PlanSyncError(
            409,
            "RESCHEDULE_TARGET_CHANGED",
            "原顺延候选已变化，请重新获取候选和预览",
        )
    target_record = get_sync_record(
        session, plan_ref=plan_ref, training_date=target_date
    )
    if target_record is not None and target_record.id != record.id:
        raise PlanSyncError(
            409,
            "RESCHEDULE_TARGET_CONFLICT",
            RESCHEDULE_CONFLICT_MESSAGES["RESCHEDULE_TARGET_CONFLICT"],
        )
    return record


def preview_reschedule(
    session: Session, *, from_date: date, target_date: date
) -> dict:
    """生成目标日完整预览；只用本地数据，可恢复超时状态，零 Garmin 请求。"""
    from app.config import get_settings

    target_day = _target_plan_for_request(session, target_date)
    record = _validate_active_record(
        session,
        plan_ref=target_day["plan_ref"],
        from_date=from_date,
        target_date=target_date,
    )
    mappings = mapping_service.load_all_mappings(session)
    preview = map_plan_day(target_day, mappings=mappings)
    return {
        **preview,
        "from_date": from_date.isoformat(),
        "to_date": target_date.isoformat(),
        "remote_write_eligible": get_settings().garmin_plan_sync_enabled,
        "reschedule": reschedule_candidate_view(record, target_day),
        "sync": sync_status_view(
            record,
            source_key=preview["source_key"],
            source_hash=preview["source_hash"],
        ),
    }


def claim_reschedule(
    session: Session,
    *,
    from_date: date,
    target_date: date,
    expected_source_hash: str,
    enabled: bool,
) -> tuple[GarminPlanSync, bool]:
    """校验目标预览并原子抢占；pending/failed 可恢复，成功后旧地址重放幂等。"""
    if not enabled:
        raise PlanSyncError(
            503,
            "GARMIN_PLAN_SYNC_DISABLED",
            "Garmin 计划写入尚未启用；请设置 GARMIN_PLAN_SYNC_ENABLED=1",
        )
    target_day = _target_plan_for_request(session, target_date)
    current_hash = calculate_source_hash(target_day)
    if expected_source_hash != current_hash:
        raise PlanSyncError(
            409, "PLAN_CHANGED", "训记计划已变化，请重新生成顺延预览后再确认"
        )
    plan_ref = target_day["plan_ref"]
    record = get_sync_record(session, plan_ref=plan_ref, training_date=from_date)
    if record is None:
        completed = _completed_reschedule(
            session,
            plan_ref=plan_ref,
            from_date=from_date,
            target_date=target_date,
            expected_source_hash=expected_source_hash,
        )
        if (
            completed is not None
            and completed.synced_hash == expected_source_hash
            and completed.workout_id
            and completed.workout_schedule_id
        ):
            return completed, False
        raise PlanSyncError(
            404,
            "RESCHEDULE_NOT_FOUND",
            "没有找到对应的顺延记录，请刷新计划后重新核对",
        )

    record = _validate_active_record(
        session,
        plan_ref=plan_ref,
        from_date=from_date,
        target_date=target_date,
    )
    if record.status == "syncing":
        raise PlanSyncError(409, "SYNC_ALREADY_RUNNING", "该训练正在改期，请勿重复提交")
    if record.status == "conflict":
        raise PlanSyncError(
            409,
            record.error_code or "GARMIN_SYNC_CONFLICT",
            record.last_error or "Garmin 顺延存在冲突，请先人工核对",
        )
    if record.status not in {"reschedule_pending", "failed"}:
        raise PlanSyncError(
            409, "RESCHEDULE_CLAIM_FAILED", "顺延状态已变化，请刷新后重试"
        )

    mappings = mapping_service.load_all_mappings(session)
    preview = map_plan_day(target_day, mappings=mappings)
    original_date = record.training_date
    original_source_key = record.source_key
    updated = (
        session.query(GarminPlanSync)
        .filter(
            GarminPlanSync.id == record.id,
            GarminPlanSync.status.in_(("reschedule_pending", "failed")),
            GarminPlanSync.phase == "reschedule",
            GarminPlanSync.training_date == from_date,
            GarminPlanSync.reschedule_to_date == target_date,
        )
        .update(
            {
                GarminPlanSync.source_hash: current_hash,
                GarminPlanSync.content_hash: preview["content_hash"],
                GarminPlanSync.payload_json: json.dumps(
                    preview["workout"], ensure_ascii=False
                ),
                GarminPlanSync.reschedule_from_date: original_date,
                GarminPlanSync.reschedule_source_key: original_source_key,
                GarminPlanSync.status: "syncing",
                GarminPlanSync.phase: "reschedule",
                GarminPlanSync.error_code: None,
                GarminPlanSync.last_error: None,
                GarminPlanSync.attempt_count: GarminPlanSync.attempt_count + 1,
                GarminPlanSync.updated_at: datetime.now(),
            },
            synchronize_session=False,
        )
    )
    if updated != 1:
        session.rollback()
        current = session.get(GarminPlanSync, record.id)
        if current is not None and current.status == "syncing":
            raise PlanSyncError(
                409, "SYNC_ALREADY_RUNNING", "该训练正在改期，请勿重复提交"
            )
        raise PlanSyncError(
            409, "RESCHEDULE_CLAIM_FAILED", "顺延状态已变化，请刷新后重试"
        )
    session.commit()
    record = session.get(GarminPlanSync, record.id)
    session.refresh(record)
    return record, True


def _verify_reschedule_source(remote: dict, allowed_source_keys: set[str]) -> None:
    if _description_marker(remote, "source_key") not in allowed_source_keys:
        raise PlanSyncConflict(
            "GARMIN_WORKOUT_SOURCE_MISMATCH",
            "已关联的 Garmin 训练不属于原顺延来源，已停止覆盖",
        )


def _workout_matches(
    remote: dict,
    desired: dict,
    record: GarminPlanSync,
    *,
    mappings: dict | None = None,
) -> bool:
    try:
        semantics_match = expand_workout(remote, mappings=mappings) == expand_workout(
            desired, mappings=mappings
        )
    except (TypeError, ValueError, KeyError):
        semantics_match = False
    return (
        semantics_match
        and remote.get("workoutName") == desired.get("workoutName")
        and _description_marker(remote, "source_key") == desired_source_key(record)
        and _description_marker(remote, "source_hash") == record.source_hash
    )


def desired_source_key(record: GarminPlanSync) -> str:
    if record.reschedule_to_date is None:
        raise PlanSyncConflict("RESCHEDULE_TARGET_MISSING", "顺延目标日期缺失")
    return source_key_for(record.plan_ref, record.reschedule_to_date)


def _verify_desired_workout(
    remote: dict,
    desired: dict,
    record: GarminPlanSync,
    *,
    mappings: dict | None = None,
) -> None:
    if not _workout_matches(remote, desired, record, mappings=mappings):
        raise PlanSyncConflict(
            "GARMIN_WORKOUT_READBACK_MISMATCH",
            "Garmin 回读的动作、组次、重量、日期来源或哈希不一致",
        )


def _verify_reschedule_schedule(
    record: GarminPlanSync, schedule: dict, *, target_date: date
) -> None:
    if _schedule_workout_id(schedule) != str(record.workout_id):
        raise PlanSyncConflict(
            "GARMIN_SCHEDULE_WORKOUT_MISMATCH",
            "Garmin 日程关联了其他训练，未自动改期",
        )
    if schedule.get("calendarDate") != target_date.isoformat():
        raise PlanSyncConflict(
            "GARMIN_SCHEDULE_DATE_MISMATCH",
            "Garmin 日程改期回读日期不一致，请人工核对后再恢复",
        )


def _finish_reschedule(
    session: Session,
    record: GarminPlanSync,
    *,
    started_at: datetime,
    expected_attempt: int,
    from_date: date,
    target_date: date,
    status: str,
    error_code: str | None = None,
    message: str | None = None,
) -> bool:
    """只结束当前 attempt；恢复或重新抢占后，旧 runner 不得回写完成态。"""
    finished_at = datetime.now()
    final_source_key = (
        source_key_for(record.plan_ref, target_date)
        if status == "synced"
        else record.source_key
    )
    values = {
        GarminPlanSync.status: status,
        GarminPlanSync.error_code: error_code,
        GarminPlanSync.last_error: message,
        GarminPlanSync.updated_at: finished_at,
        GarminPlanSync.phase: "verify" if status == "synced" else "reschedule",
    }
    if status == "synced":
        # 保留 reschedule_from/to 与原来源键作为审计和旧地址幂等依据。
        values.update(
            {
                GarminPlanSync.training_date: target_date,
                GarminPlanSync.source_key: final_source_key,
                GarminPlanSync.synced_hash: record.source_hash,
                GarminPlanSync.synced_at: finished_at,
            }
        )
    updated = (
        session.query(GarminPlanSync)
        .filter(
            GarminPlanSync.id == record.id,
            GarminPlanSync.status == "syncing",
            GarminPlanSync.attempt_count == expected_attempt,
        )
        .update(values, synchronize_session=False)
    )
    if updated != 1:
        session.rollback()
        return False
    session.add(
        JobRun(
            job_name="garmin_plan_reschedule",
            started_at=started_at,
            finished_at=finished_at,
            status=status,
            error=message,
            detail_json=json.dumps(
                {
                    "sync_id": record.id,
                    "from_date": from_date.isoformat(),
                    "to_date": target_date.isoformat(),
                    "source_key": final_source_key,
                    "previous_source_key": record.reschedule_source_key,
                    "workout_id": record.workout_id,
                    "workout_schedule_id": record.workout_schedule_id,
                    "error_code": error_code,
                },
                ensure_ascii=False,
            ),
        )
    )
    session.commit()
    session.refresh(record)
    return True


def run_reschedule(
    session: Session, record_id: int, *, adapter: Any | None = None
) -> None:
    """原地更新已关联 Workout 和日程；任何恢复路径都不得调用创建接口。"""
    started_at = datetime.now()
    record = session.get(GarminPlanSync, record_id)
    if record is None or record.status != "syncing" or record.phase != "reschedule":
        return
    expected_attempt = record.attempt_count
    session.commit()
    target_date = record.reschedule_to_date
    from_date = record.reschedule_from_date or record.training_date
    if target_date is None:
        raise PlanSyncError(409, "RESCHEDULE_TARGET_MISSING", "顺延目标日期缺失")
    try:
        if adapter is None:
            from app.config import get_settings

            adapter = GarminWorkoutAdapter.from_settings(get_settings())
        if not record.workout_id or not record.workout_schedule_id:
            raise PlanSyncConflict(
                "GARMIN_RESCHEDULE_ASSOCIATION_MISSING",
                "顺延缺少原 Workout 或日程关联，禁止创建替代对象",
            )
        desired = json.loads(record.payload_json or "{}")
        mappings = mapping_service.load_all_mappings(session)
        original_source_key = record.reschedule_source_key or source_key_for(
            record.plan_ref, from_date
        )
        target_source_key = source_key_for(record.plan_ref, target_date)

        remote = adapter.get_workout(record.workout_id)
        _verify_reschedule_source(remote, {original_source_key, target_source_key})
        if not _workout_matches(remote, desired, record, mappings=mappings):
            # 已确定原 ID 的完整 PUT；内容或目标日期来源变化都原地更新。
            adapter.update_workout(record.workout_id, {**remote, **desired})
            remote = adapter.get_workout(record.workout_id)
        _verify_desired_workout(remote, desired, record, mappings=mappings)

        schedule = adapter.get_schedule(record.workout_schedule_id)
        if _schedule_workout_id(schedule) != str(record.workout_id):
            raise PlanSyncConflict(
                "GARMIN_SCHEDULE_WORKOUT_MISMATCH",
                "Garmin 日程关联了其他训练，未自动改期",
            )
        allowed_dates = {from_date.isoformat(), target_date.isoformat()}
        if schedule.get("calendarDate") not in allowed_dates:
            raise PlanSyncConflict(
                "GARMIN_SCHEDULE_DATE_MISMATCH",
                "Garmin 日程既不在原日期也不在目标日期，请人工核对",
            )
        if schedule.get("calendarDate") != target_date.isoformat():
            adapter.reschedule_schedule(record.workout_schedule_id, target_date)
            schedule = adapter.get_schedule(record.workout_schedule_id)
        _verify_reschedule_schedule(record, schedule, target_date=target_date)
        _finish_reschedule(
            session,
            record,
            started_at=started_at,
            expected_attempt=expected_attempt,
            from_date=from_date,
            target_date=target_date,
            status="synced",
        )
    except PlanSyncConflict as exc:
        session.rollback()
        _finish_reschedule(
            session,
            record,
            started_at=started_at,
            expected_attempt=expected_attempt,
            from_date=from_date,
            target_date=target_date,
            status="conflict",
            error_code=exc.error_code,
            message=exc.public_message,
        )
    except GarminWorkoutAdapterError as exc:
        session.rollback()
        _finish_reschedule(
            session,
            record,
            started_at=started_at,
            expected_attempt=expected_attempt,
            from_date=from_date,
            target_date=target_date,
            status="failed",
            error_code=exc.error_code,
            message=exc.public_message,
        )
    except Exception as exc:  # noqa: BLE001 - 后台任务只保存脱敏异常类型
        session.rollback()
        _finish_reschedule(
            session,
            record,
            started_at=started_at,
            expected_attempt=expected_attempt,
            from_date=from_date,
            target_date=target_date,
            status="failed",
            error_code="GARMIN_RESCHEDULE_UNEXPECTED",
            message=f"Garmin 顺延失败（{type(exc).__name__}）",
        )


class GarminRescheduleManager:
    """按已抢占记录启动顺延 runner；不在请求事务内执行网络调用。"""

    def __init__(self, runner: Callable[[int], None] | None = None) -> None:
        self._runner = runner

    @staticmethod
    def _default_runner(record_id: int) -> None:
        from app.db import SessionLocal

        session = SessionLocal()
        try:
            run_reschedule(session, record_id)
        finally:
            session.close()

    def _run(self, record_id: int) -> None:
        try:
            (self._runner or self._default_runner)(record_id)
        except Exception:
            return

    def start(
        self,
        session: Session,
        *,
        from_date: date,
        target_date: date,
        expected_source_hash: str,
        enabled: bool,
    ) -> dict:
        record, should_start = claim_reschedule(
            session,
            from_date=from_date,
            target_date=target_date,
            expected_source_hash=expected_source_hash,
            enabled=enabled,
        )
        if should_start:
            threading.Thread(
                target=self._run,
                args=(record.id,),
                daemon=True,
                name=f"garmin-plan-reschedule-{record.id}",
            ).start()
        view_date = record.reschedule_to_date or record.training_date
        return {
            "started": should_start,
            "sync": sync_status_view(
                record,
                source_key=source_key_for(record.plan_ref, view_date),
                source_hash=record.source_hash,
            ),
        }


default_garmin_reschedule_manager = GarminRescheduleManager()


def get_garmin_reschedule_manager() -> GarminRescheduleManager:
    """FastAPI 注入点；测试替换为只 claim 的 manager，避免真实外呼。"""
    return default_garmin_reschedule_manager
