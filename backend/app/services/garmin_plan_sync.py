"""训记计划日到 Garmin Workout 的单向同步状态机。

预览/状态查询保持纯本地；只有用户确认 POST 才会实例化 Garmin 写入适配器。
网络调用不跨数据库事务，远端 ID 分阶段落库，恢复时先对账再决定是否创建。
"""
from __future__ import annotations

import json
import threading
from datetime import date, datetime, timedelta
from typing import Any, Callable

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.adapters.garmin_workout_adapter import (
    GarminWorkoutAdapter,
    GarminWorkoutAdapterError,
)
from app.models import GarminPlanSync, JobRun
from app.services import exercise_mapping as mapping_service
from app.services.garmin_workout_mapper import (
    content_hash as calculate_content_hash,
    expand_workout,
    map_plan_day,
    source_hash as calculate_source_hash,
)

DEFAULT_STALE_SYNC_SECONDS = 15 * 60
STALE_SYNC_ERROR_CODE = "GARMIN_SYNC_INTERRUPTED"
STALE_SYNC_MESSAGE = "上次 Garmin 写入可能因进程中断而停止，已自动恢复；请重新确认后继续"


class PlanSyncError(RuntimeError):
    """可映射为 HTTP 响应的脱敏同步错误。"""

    def __init__(
        self,
        status_code: int,
        error_code: str,
        message: str,
        *,
        issues: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.public_message = message
        self.issues = issues or []


class PlanSyncConflict(RuntimeError):
    """远端归属、候选数量或日程关联不安全，禁止自动覆盖。"""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.public_message = message


def source_key_for(plan_ref: str, training_date: date | str) -> str:
    day = training_date.isoformat() if isinstance(training_date, date) else training_date
    return f"xunji-plan:v1:{plan_ref}:{day}"


def recover_stale_syncing(
    session: Session,
    record: GarminPlanSync | None,
    *,
    now: datetime | None = None,
    stale_after_seconds: int | None = None,
) -> bool:
    """将超时的本地抢占标记为可恢复失败，不发起任何 Garmin 请求。

    通过 updated_at + attempt_count 条件更新避免覆盖刚完成或已重新抢占的记录。
    保留 phase、payload、远端 ID 和顺延审计字段，后续确认沿用既有恢复状态机。
    """
    if record is None or record.status != "syncing":
        return False
    # 同一请求会话可能缓存了其他会话更新前的对象，先以数据库当前值判定。
    session.refresh(record)
    if record.status != "syncing":
        return False
    if stale_after_seconds is None:
        from app.config import get_settings

        stale_after_seconds = get_settings().garmin_plan_sync_stale_seconds
    current_time = now or datetime.now()

    # 另一会话可能刚更新数据库；第一次 CAS 失败后最多按新快照重检一次。
    for _ in range(2):
        if record.status != "syncing":
            return False
        observed_at = record.updated_at or record.created_at
        if observed_at is None:
            return False
        elapsed = current_time - observed_at
        # 观测值比"现在"还新：说明该时间戳由另一个时钟写入（例如历史行由数据库
        # server_default 的 UTC 生成），属于时钟错位而非超时，按活跃处理。
        if elapsed < timedelta(0):
            return False
        if elapsed < timedelta(seconds=stale_after_seconds):
            return False

        expected_attempt = record.attempt_count
        updated = (
            session.query(GarminPlanSync)
            .filter(
                GarminPlanSync.id == record.id,
                GarminPlanSync.status == "syncing",
                GarminPlanSync.updated_at == observed_at,
                GarminPlanSync.attempt_count == expected_attempt,
            )
            .update(
                {
                    GarminPlanSync.status: "failed",
                    GarminPlanSync.error_code: STALE_SYNC_ERROR_CODE,
                    GarminPlanSync.last_error: STALE_SYNC_MESSAGE,
                    GarminPlanSync.updated_at: current_time,
                },
                synchronize_session=False,
            )
        )
        if updated == 1:
            session.add(
                JobRun(
                    job_name=(
                        "garmin_plan_reschedule"
                        if record.phase == "reschedule"
                        else "garmin_plan_sync"
                    ),
                    started_at=observed_at,
                    finished_at=current_time,
                    status="failed",
                    error=STALE_SYNC_MESSAGE,
                    detail_json=json.dumps(
                        {
                            "sync_id": record.id,
                            "source_key": record.source_key,
                            "workout_id": record.workout_id,
                            "workout_schedule_id": record.workout_schedule_id,
                            "error_code": STALE_SYNC_ERROR_CODE,
                            "recovery": "stale_syncing",
                            "attempt_count": expected_attempt,
                        },
                        ensure_ascii=False,
                    ),
                )
            )
            session.commit()
            session.refresh(record)
            return True
        session.rollback()
        session.refresh(record)
    return False


def get_sync_record(
    session: Session, *, plan_ref: str, training_date: date
) -> GarminPlanSync | None:
    record = (
        session.query(GarminPlanSync)
        .filter(
            GarminPlanSync.plan_ref == plan_ref,
            GarminPlanSync.training_date == training_date,
        )
        .first()
    )
    recover_stale_syncing(session, record)
    return record


ACTIVE_RESCHEDULE_STATUSES = ("reschedule_pending", "syncing", "failed", "conflict")


def get_pending_reschedule_for_target(
    session: Session, *, plan_ref: str, target_date: date
) -> GarminPlanSync | None:
    """返回占用目标日期的活动顺延，覆盖待确认、失败和冲突恢复。"""
    record = (
        session.query(GarminPlanSync)
        .filter(
            GarminPlanSync.plan_ref == plan_ref,
            GarminPlanSync.reschedule_to_date == target_date,
            GarminPlanSync.phase == "reschedule",
            GarminPlanSync.status.in_(ACTIVE_RESCHEDULE_STATUSES),
        )
        .first()
    )
    recover_stale_syncing(session, record)
    return record


def get_sync_records(
    session: Session, *, start: date, end: date
) -> dict[tuple[str, date], GarminPlanSync]:
    rows = (
        session.query(GarminPlanSync)
        .filter(
            GarminPlanSync.training_date >= start,
            GarminPlanSync.training_date <= end,
        )
        .all()
    )
    for row in rows:
        recover_stale_syncing(session, row)
    return {(row.plan_ref, row.training_date): row for row in rows}


def _isoformat(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _sync_result(preview: dict[str, Any]) -> dict[str, Any]:
    """ADR §7.2：三类动作不得混成一个警告列表。"""
    return {
        "written_movements": [
            m.get("name") for m in (preview.get("movements") or []) if m.get("name")
        ],
        "skipped_movements": list(preview.get("skipped") or []),
        "excluded_movements": list(preview.get("excluded") or []),
    }


def _has_skipped(record: GarminPlanSync) -> bool:
    """读取 claim 阶段落库的缺口记录（解析失败按无缺口处理，不阻断同步）。"""
    try:
        data = json.loads(record.sync_result_json or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return False
    if not isinstance(data, dict):
        return False
    skipped = data.get("skipped_movements")
    return bool(skipped)


def _sync_result_for_view(record: GarminPlanSync | None) -> dict[str, Any]:
    """状态视图用：计数 + skipped 明细；不返回完整 written 列表。"""
    empty = {
        "written": 0,
        "skipped": 0,
        "excluded": 0,
        "skipped_movements": [],
    }
    if record is None:
        return empty
    try:
        data = json.loads(record.sync_result_json or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return empty
    if not isinstance(data, dict):
        return empty
    written = data.get("written_movements") or []
    skipped = data.get("skipped_movements") or []
    excluded = data.get("excluded_movements") or []
    if not isinstance(written, list):
        written = []
    if not isinstance(skipped, list):
        skipped = []
    if not isinstance(excluded, list):
        excluded = []
    return {
        "written": len(written),
        "skipped": len(skipped),
        "excluded": len(excluded),
        "skipped_movements": list(skipped),
    }


def sync_status_view(
    record: GarminPlanSync | None,
    *,
    source_key: str,
    source_hash: str,
) -> dict:
    """返回脱敏状态；活动顺延优先于普通更新判断。"""
    if record is None:
        status = "not_synced"
    elif (
        record.phase == "reschedule"
        and record.status in ACTIVE_RESCHEDULE_STATUSES
    ):
        status = record.status
    elif record.status == "partial":
        # partial 即使 synced_hash == source_hash 也不得被覆盖成 synced
        status = "partial"
    elif (
        record.synced_hash
        and record.synced_hash == source_hash
        and record.workout_id
        and record.workout_schedule_id
    ):
        status = "synced"
    elif record.synced_hash and record.synced_hash != source_hash:
        status = "update_available"
    else:
        status = record.status

    return {
        "id": record.id if record else None,
        "status": status,
        "phase": record.phase if record else None,
        "source_key": source_key,
        "source_hash": source_hash,
        "content_hash": record.content_hash if record else None,
        "synced_hash": record.synced_hash if record else None,
        "workout_id": record.workout_id if record else None,
        "workout_schedule_id": record.workout_schedule_id if record else None,
        "reschedule_from_date": (
            (
                record.training_date
                if record.phase == "reschedule"
                else (record.reschedule_from_date or record.training_date)
            ).isoformat()
            if record
            and (
                record.phase == "reschedule"
                or record.reschedule_from_date is not None
            )
            else None
        ),
        "reschedule_to_date": (
            record.reschedule_to_date.isoformat()
            if record and record.reschedule_to_date
            else None
        ),
        "previous_workout_schedule_id": (
            record.previous_workout_schedule_id if record else None
        ),
        "error_code": record.error_code if record else None,
        "last_error": record.last_error if record else None,
        "sync_result": _sync_result_for_view(record),
        "attempt_count": record.attempt_count if record else 0,
        "synced_at": _isoformat(record.synced_at) if record else None,
    }


def _record_view(session: Session, record: GarminPlanSync) -> dict:
    target_date = (
        record.reschedule_to_date
        if record.phase == "reschedule" and record.reschedule_to_date
        else record.training_date
    )
    return sync_status_view(
        record,
        source_key=source_key_for(record.plan_ref, target_date),
        source_hash=record.source_hash,
    )


def _raise_record_busy_or_conflict(record: GarminPlanSync | None) -> None:
    if record is not None and record.status == "syncing":
        raise PlanSyncError(409, "SYNC_ALREADY_RUNNING", "该训练正在同步，请勿重复提交")
    if record is not None and record.status == "conflict":
        raise PlanSyncError(
            409,
            record.error_code or "GARMIN_SYNC_CONFLICT",
            record.last_error or "Garmin 同步存在冲突，请先人工核对",
        )
    raise PlanSyncError(409, "SYNC_CLAIM_FAILED", "同步状态已变化，请刷新后重试")


def _claim_existing(
    session: Session,
    record: GarminPlanSync,
    *,
    current_hash: str,
    current_content_hash: str,
    payload: dict[str, Any],
    mapping_hash: str | None = None,
    sync_result_json: str | None = None,
) -> GarminPlanSync:
    updated = (
        session.query(GarminPlanSync)
        .filter(
            GarminPlanSync.id == record.id,
            GarminPlanSync.status.notin_(("syncing", "conflict")),
        )
        .update(
            {
                GarminPlanSync.source_hash: current_hash,
                GarminPlanSync.content_hash: current_content_hash,
                GarminPlanSync.payload_json: json.dumps(payload, ensure_ascii=False),
                GarminPlanSync.sync_result_json: sync_result_json,
                GarminPlanSync.mapping_hash: mapping_hash,
                GarminPlanSync.status: "syncing",
                GarminPlanSync.phase: "update" if record.workout_id else "create",
                GarminPlanSync.reschedule_to_date: None,
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
        _raise_record_busy_or_conflict(session.get(GarminPlanSync, record.id))
    session.commit()
    # 条件 UPDATE 使用 synchronize_session=False；必须刷新同一 identity map
    # 中的旧对象，否则 runner 会看到更新前的 failed/synced 并直接退出。
    record = session.get(GarminPlanSync, record.id)
    session.refresh(record)
    return record


def claim_plan_sync(
    session: Session,
    plan_day: dict[str, Any],
    *,
    expected_source_hash: str,
    enabled: bool,
) -> tuple[GarminPlanSync, bool]:
    """校验预览哈希并原子抢占；返回 (记录, 是否需要启动 runner)。"""
    if not enabled:
        raise PlanSyncError(
            503,
            "GARMIN_PLAN_SYNC_DISABLED",
            "Garmin 计划写入尚未启用；请设置 GARMIN_PLAN_SYNC_ENABLED=1",
        )
    current_hash = calculate_source_hash(plan_day)
    current_content_hash = calculate_content_hash(plan_day)
    if expected_source_hash != current_hash:
        raise PlanSyncError(
            409, "PLAN_CHANGED", "训记计划已变化，请重新生成预览后再确认"
        )
    mappings = mapping_service.load_all_mappings(session, include_excluded=True)
    preview = map_plan_day(plan_day, mappings=mappings, allow_partial=True)
    result_json = json.dumps(_sync_result(preview), ensure_ascii=False)
    movement_names = [
        str(m.get("name") or "").strip() for m in (plan_day.get("movements") or [])
    ]
    mapping_hash = mapping_service.load_mapping_snapshot_hash(session, movement_names)
    training_date = date.fromisoformat(plan_day["date"])
    pending_reschedule = get_pending_reschedule_for_target(
        session, plan_ref=plan_day["plan_ref"], target_date=training_date
    )
    if pending_reschedule is not None:
        raise PlanSyncError(
            409,
            "RESCHEDULE_CONFIRMATION_REQUIRED",
            "该日期已有顺延待确认训练，请先处理顺延，避免重复创建 Garmin 训练",
        )
    record = get_sync_record(
        session, plan_ref=plan_day["plan_ref"], training_date=training_date
    )
    if record is not None and record.status == "conflict":
        _raise_record_busy_or_conflict(record)
    if record is not None and record.status == "syncing":
        _raise_record_busy_or_conflict(record)
    # partial 即使 hash 相同也必须允许重新 claim（补齐映射后清除缺口）。
    if (
        record is not None
        and record.status != "partial"
        and record.synced_hash == current_hash
        and record.workout_id
        and record.workout_schedule_id
    ):
        record.mapping_hash = mapping_hash
        session.commit()
        return record, False
    if record is not None:
        return _claim_existing(
            session,
            record,
            current_hash=current_hash,
            current_content_hash=current_content_hash,
            payload=preview["workout"],
            mapping_hash=mapping_hash,
            sync_result_json=result_json,
        ), True

    record = GarminPlanSync(
        plan_ref=plan_day["plan_ref"],
        training_date=training_date,
        source_key=preview["source_key"],
        source_hash=current_hash,
        content_hash=current_content_hash,
        payload_json=json.dumps(preview["workout"], ensure_ascii=False),
        sync_result_json=result_json,
        mapping_hash=mapping_hash,
        status="syncing",
        phase="create",
        attempt_count=1,
        # 与恢复判断统一使用本地 naive 时间，避免数据库 UTC 默认值造成误判。
        updated_at=datetime.now(),
    )
    session.add(record)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = get_sync_record(
            session, plan_ref=plan_day["plan_ref"], training_date=training_date
        )
        _raise_record_busy_or_conflict(existing)
    return record, True


def _description_marker(payload: dict[str, Any], key: str) -> str | None:
    for part in str(payload.get("description") or "").split(";"):
        name, separator, value = part.strip().partition("=")
        if separator and name == key:
            return value
    return None


def _workout_id(payload: dict[str, Any]) -> str | None:
    value = payload.get("workoutId")
    return str(value) if value is not None else None


def _schedule_workout_id(payload: dict[str, Any]) -> str | None:
    value = (payload.get("workout") or {}).get("workoutId") or payload.get("workoutId")
    return str(value) if value is not None else None


def _verify_source(record: GarminPlanSync, remote: dict[str, Any]) -> None:
    if _description_marker(remote, "source_key") != record.source_key:
        raise PlanSyncConflict(
            "GARMIN_WORKOUT_SOURCE_MISMATCH",
            "已关联的 Garmin 训练不属于当前来源，已停止覆盖",
        )


def _verify_workout_semantics(
    record: GarminPlanSync,
    remote: dict[str, Any],
    desired: dict[str, Any],
    *,
    mappings: dict | None = None,
) -> None:
    _verify_source(record, remote)
    try:
        matches = expand_workout(remote, mappings=mappings) == expand_workout(
            desired, mappings=mappings
        )
    except (TypeError, ValueError, KeyError) as exc:
        raise PlanSyncConflict(
            "GARMIN_WORKOUT_READBACK_INVALID",
            "Garmin 回读训练结构无法核验，未标记同步成功",
        ) from exc
    if (
        not matches
        or remote.get("workoutName") != desired.get("workoutName")
        or _description_marker(remote, "source_hash") != record.source_hash
    ):
        raise PlanSyncConflict(
            "GARMIN_WORKOUT_READBACK_MISMATCH",
            "Garmin 回读的动作、组次、重量或来源哈希不一致",
        )


def _verify_schedule(
    record: GarminPlanSync, schedule: dict[str, Any]
) -> None:
    if _schedule_workout_id(schedule) != str(record.workout_id):
        raise PlanSyncConflict(
            "GARMIN_SCHEDULE_WORKOUT_MISMATCH",
            "Garmin 日程关联了其他训练，未自动改期或新增日程",
        )
    if schedule.get("calendarDate") != record.training_date.isoformat():
        raise PlanSyncConflict(
            "GARMIN_SCHEDULE_DATE_MISMATCH",
            "Garmin 日程日期与训记计划不一致，请人工核对后再恢复",
        )


def _finish(
    session: Session,
    record: GarminPlanSync,
    *,
    started_at: datetime,
    expected_attempt: int,
    status: str,
    error_code: str | None = None,
    message: str | None = None,
) -> bool:
    """只结束仍属于当前 attempt 的抢占，旧 runner 不得覆盖恢复后的状态。"""
    finished_at = datetime.now()
    values = {
        GarminPlanSync.status: status,
        GarminPlanSync.error_code: error_code,
        GarminPlanSync.last_error: message,
        GarminPlanSync.updated_at: finished_at,
    }
    if status in ("synced", "partial"):
        values.update(
            {
                GarminPlanSync.phase: "verify",
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
            job_name="garmin_plan_sync",
            started_at=started_at,
            finished_at=finished_at,
            status=status,
            error=message,
            detail_json=json.dumps(
                {
                    "sync_id": record.id,
                    "source_key": record.source_key,
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


def run_plan_sync(
    session: Session,
    record_id: int,
    *,
    adapter: Any | None = None,
) -> None:
    """执行已抢占记录；所有异常只落脱敏状态，不向后台线程外抛。"""
    started_at = datetime.now()
    record = session.get(GarminPlanSync, record_id)
    if record is None or record.status != "syncing":
        return
    expected_attempt = record.attempt_count
    # 结束由 get() 开启的数据库事务，再进行认证和网络调用。
    session.commit()
    try:
        if adapter is None:
            from app.config import get_settings

            adapter = GarminWorkoutAdapter.from_settings(get_settings())
        desired = json.loads(record.payload_json or "{}")
        mappings = mapping_service.load_all_mappings(session)
        if not record.workout_id:
            record.phase = "create"
            session.commit()
            candidates = adapter.find_workouts_by_source_key(record.source_key)
            if len(candidates) > 1:
                raise PlanSyncConflict(
                    "GARMIN_DUPLICATE_WORKOUTS",
                    "发现多个同来源 Garmin 训练，请人工保留并核对关联",
                )
            if len(candidates) == 1:
                candidate_id = _workout_id(candidates[0])
                if candidate_id is None:
                    raise PlanSyncConflict(
                        "GARMIN_INVALID_RESPONSE", "Garmin 候选训练缺少 workoutId"
                    )
                record.workout_id = candidate_id
            else:
                record.workout_id = adapter.create_workout(desired)
            # 创建/认领成功后立即提交，后续失败恢复不得再次 create。
            session.commit()

        remote = adapter.get_workout(record.workout_id)
        _verify_source(record, remote)
        current_description_hash = _description_marker(remote, "source_hash")
        try:
            semantics_match = expand_workout(
                remote, mappings=mappings
            ) == expand_workout(desired, mappings=mappings)
        except (TypeError, ValueError, KeyError):
            semantics_match = False
        if (
            not semantics_match
            or current_description_hash != record.source_hash
            or remote.get("workoutName") != desired.get("workoutName")
        ):
            record.phase = "update"
            session.commit()
            # 保留服务器字段，只替换应用管理的完整训练内容，workoutId 不变。
            adapter.update_workout(record.workout_id, {**remote, **desired})
            remote = adapter.get_workout(record.workout_id)
        _verify_workout_semantics(record, remote, desired, mappings=mappings)

        if not record.workout_schedule_id:
            record.phase = "schedule"
            session.commit()
            schedules = adapter.find_schedules(record.workout_id, record.training_date)
            if len(schedules) > 1:
                raise PlanSyncConflict(
                    "GARMIN_DUPLICATE_SCHEDULES",
                    "发现多个同训练同日期的 Garmin 日程，请人工核对",
                )
            if len(schedules) == 1:
                schedule_id = schedules[0].get("workoutScheduleId")
                if schedule_id is None:
                    raise PlanSyncConflict(
                        "GARMIN_INVALID_RESPONSE", "Garmin 候选日程缺少 workoutScheduleId"
                    )
                record.workout_schedule_id = str(schedule_id)
            else:
                record.workout_schedule_id = adapter.schedule_workout(
                    record.workout_id, record.training_date
                )
            # 日程创建/认领成功同样立即提交。
            session.commit()

        schedule = adapter.get_schedule(record.workout_schedule_id)
        _verify_schedule(record, schedule)
        finite_status = "partial" if _has_skipped(record) else "synced"
        _finish(
            session,
            record,
            started_at=started_at,
            expected_attempt=expected_attempt,
            status=finite_status,
        )
    except PlanSyncConflict as exc:
        _finish(
            session,
            record,
            started_at=started_at,
            expected_attempt=expected_attempt,
            status="conflict",
            error_code=exc.error_code,
            message=exc.public_message,
        )
    except GarminWorkoutAdapterError as exc:
        _finish(
            session,
            record,
            started_at=started_at,
            expected_attempt=expected_attempt,
            status="failed",
            error_code=exc.error_code,
            message=exc.public_message,
        )
    except Exception as exc:  # noqa: BLE001 - 后台任务只保存脱敏异常类型
        _finish(
            session,
            record,
            started_at=started_at,
            expected_attempt=expected_attempt,
            status="failed",
            error_code="GARMIN_SYNC_UNEXPECTED",
            message=f"Garmin 同步失败（{type(exc).__name__}）",
        )


class GarminPlanSyncManager:
    """按同步记录启动后台 runner；claim 在请求事务内完成。"""

    def __init__(self, runner: Callable[[int], None] | None = None) -> None:
        self._runner = runner

    @staticmethod
    def _default_runner(record_id: int) -> None:
        from app.db import SessionLocal

        session = SessionLocal()
        try:
            run_plan_sync(session, record_id)
        finally:
            session.close()

    def _run(self, record_id: int) -> None:
        try:
            (self._runner or self._default_runner)(record_id)
        except Exception:
            # run_plan_sync 自身应落 failed；这里防止注入 runner 异常逃逸线程。
            return

    def start(
        self,
        session: Session,
        plan_day: dict[str, Any],
        *,
        expected_source_hash: str,
        enabled: bool,
    ) -> dict:
        record, should_start = claim_plan_sync(
            session,
            plan_day,
            expected_source_hash=expected_source_hash,
            enabled=enabled,
        )
        if should_start:
            threading.Thread(
                target=self._run,
                args=(record.id,),
                daemon=True,
                name=f"garmin-plan-sync-{record.id}",
            ).start()
        return {"started": should_start, "sync": _record_view(session, record)}


default_garmin_plan_sync_manager = GarminPlanSyncManager()


def get_garmin_plan_sync_manager() -> GarminPlanSyncManager:
    """FastAPI 依赖注入点；测试可替换为同步 runner，绝不真实外呼。"""
    return default_garmin_plan_sync_manager
