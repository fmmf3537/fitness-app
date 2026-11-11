"""L2 目录动作真实创建探针。

**本模块会真实创建并删除 Garmin Workout**。仅在
`GARMIN_PLAN_SYNC_ENABLED=1` 且调用方显式给出 pairs 时运行；
每次创建的对象都会在回读后被删除（除非 `keep=True`）；**不创建任何日程**。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ExerciseMapping
from app.services.garmin_workout_mapper import (
    CONDITION_REPS,
    NO_TARGET,
    SPORT,
    STEP_INTERVAL,
    WEIGHT_KG,
)

PROBE_MAX_ITEMS = 30


@dataclass(frozen=True)
class ProbeResult:
    category: str
    exercise_name: str
    status: str  # "verified" / "normalized" / "failed"
    observed_category: str | None
    observed_exercise_name: str | None
    observed_display_name: str | None
    workout_id: str | None
    deleted: bool
    note: str | None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def build_probe_payload(category: str, exercise_name: str) -> dict:
    """构造 1 步 × 1 次的最小力量训练 payload（纯函数，可单测）。

    复用 garmin_workout_mapper 的常量；workoutName 必须以 "PROBE｜" 开头且含"请删除"。
    """
    return {
        "sportType": SPORT,
        "subSportType": None,
        "workoutName": f"PROBE｜{category}｜{exercise_name}｜请删除",
        "workoutSegments": [
            {
                "segmentOrder": 1,
                "sportType": SPORT,
                "workoutSteps": [
                    {
                        "type": "ExecutableStepDTO",
                        "stepOrder": 1,
                        "stepType": STEP_INTERVAL,
                        "endCondition": CONDITION_REPS,
                        "endConditionValue": 1.0,
                        "targetType": NO_TARGET,
                        "category": category,
                        "exerciseName": exercise_name,
                        "weightValue": None,
                        "weightUnit": WEIGHT_KG,
                        "description": "PROBE",
                    }
                ],
            }
        ],
    }


def _first_step(workout: dict[str, Any]) -> dict[str, Any]:
    segments = workout.get("workoutSegments") or []
    if not segments:
        return {}
    steps = segments[0].get("workoutSteps") or []
    if not steps:
        return {}
    step = steps[0]
    return step if isinstance(step, dict) else {}


def probe_one(
    adapter: Any,
    category: str,
    exercise_name: str,
    *,
    keep: bool = False,
) -> ProbeResult:
    """创建 → 回读 → （默认）删除。"""
    workout_id: str | None = None
    deleted = False
    note: str | None = None
    observed_category: str | None = None
    observed_exercise_name: str | None = None
    observed_display_name: str | None = None
    status = "failed"

    try:
        payload = build_probe_payload(category, exercise_name)
        workout_id = adapter.create_workout(payload)
        workout = adapter.get_workout(workout_id)
        step = _first_step(workout if isinstance(workout, dict) else {})
        observed_category = step.get("category")
        observed_exercise_name = step.get("exerciseName")
        display = step.get("displayName")
        observed_display_name = display if isinstance(display, str) else None

        if observed_category == category and observed_exercise_name == exercise_name:
            status = "verified"
        elif observed_category == category:
            status = "normalized"
            note = f"exerciseName: {exercise_name} → {observed_exercise_name!r}"
        else:
            status = "failed"
    except Exception as exc:  # noqa: BLE001 - 探针必须吞掉远端异常并脱敏
        status = "failed"
        note = type(exc).__name__

    if not keep and workout_id:
        try:
            adapter.delete_workout(workout_id)
            deleted = True
        except Exception as exc:  # noqa: BLE001
            deleted = False
            extra = (
                f"删除失败（{type(exc).__name__}），请手动删除 {workout_id}"
            )
            note = f"{note}；{extra}" if note else extra

    return ProbeResult(
        category=category,
        exercise_name=exercise_name,
        status=status,
        observed_category=observed_category,
        observed_exercise_name=observed_exercise_name,
        observed_display_name=observed_display_name,
        workout_id=workout_id,
        deleted=deleted,
        note=note,
    )


def probe_batch(
    adapter: Any,
    pairs: list[tuple[str, str]],
    *,
    keep: bool = False,
    max_items: int = PROBE_MAX_ITEMS,
) -> dict:
    """批量探测。返回统计与 results（ProbeResult 的 dict 列表）。"""
    if not pairs:
        return {
            "requested": 0,
            "processed": 0,
            "verified": 0,
            "normalized": 0,
            "failed": 0,
            "results": [],
        }

    seen: set[tuple[str, str]] = set()
    unique: list[tuple[str, str]] = []
    for pair in pairs:
        if pair in seen:
            continue
        seen.add(pair)
        unique.append(pair)

    selected = unique[:max_items]
    results: list[ProbeResult] = [
        probe_one(adapter, category, exercise_name, keep=keep)
        for category, exercise_name in selected
    ]

    verified = sum(1 for r in results if r.status == "verified")
    normalized = sum(1 for r in results if r.status == "normalized")
    failed = sum(1 for r in results if r.status == "failed")
    return {
        "requested": len(pairs),
        "processed": len(results),
        "verified": verified,
        "normalized": normalized,
        "failed": failed,
        "results": [asdict(r) for r in results],
    }


def apply_probe_results(session: Session, results: list[ProbeResult]) -> dict:
    """把探测结果写回 exercise_mapping。返回 {"updated": n, "skipped": m}。"""
    updated = 0
    skipped = 0
    for result in results:
        rows = list(
            session.scalars(
                select(ExerciseMapping).where(
                    ExerciseMapping.garmin_category == result.category,
                    ExerciseMapping.garmin_exercise_name == result.exercise_name,
                )
            ).all()
        )
        if not rows:
            skipped += 1
            continue

        for row in rows:
            if result.status == "verified":
                row.verified_level = "created"
                row.verified_at = _utcnow()
            elif result.status == "normalized":
                row.verified_level = "created"
                row.verified_at = _utcnow()
                row.garmin_exercise_name = result.observed_exercise_name
                row.note = f"L2 探针：{result.note}"
            elif result.status == "failed":
                probe_note = f"L2 探针：{result.note}" if result.note else "L2 探针：failed"
                row.note = f"{row.note}；{probe_note}" if row.note else probe_note
            updated += 1

    session.commit()
    return {"updated": updated, "skipped": skipped}


__all__ = [
    "PROBE_MAX_ITEMS",
    "ProbeResult",
    "apply_probe_results",
    "build_probe_payload",
    "probe_batch",
    "probe_one",
]
