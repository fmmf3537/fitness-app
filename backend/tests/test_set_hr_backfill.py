"""V4-9 存量逐组心率回填脚本 + session_review prompt 注入段测试。

参照既有模式：conftest helpers + fuse_workout 构造数据；佳明 raw_json 手工构造小型
details+exercise_sets（不 import 其他测试模块的私有函数）。
"""
import json
from datetime import date

from app.models import Workout, WorkoutSetHr
from app.services.ai import (
    build_session_review_prompt,
    generate_session_review,
)
from app.services.fuse import fuse_workout
from app.services.workouts import delete_workout
from scripts.backfill_set_hr import run_backfill
from tests.conftest import make_garmin_activity, make_xunji_train

DAY = date(2026, 8, 5)


# ---------- 共享夹具：2 组（深蹲×2，1 low）+ 充足 HR 点 + 恢复点 ----------

BACKFILL_MOVEMENTS = [
    {
        "name": "深蹲",
        "sets": [
            {"weight": "60", "unit": "kg", "reps": "8", "done": True},
            {"weight": "60", "unit": "kg", "reps": "8", "done": True},
        ],
    },
]


def _epoch_ms_to_iso(ms: int) -> str:
    from datetime import datetime

    sec = int(ms // 1000)
    msec = ms - sec * 1000
    base = datetime.utcfromtimestamp(sec).strftime("%Y-%m-%dT%H:%M:%S")
    return f"{base}.{msec}"


def _build_two_set_raw() -> dict:
    """2 个 ACTIVE 组（SQUAT×2）+ 充足 HR 点 + 恢复点。"""
    starts_ms = [0, 40_000]
    durations_ms = [30_000, 30_000]
    sets = []
    for st, dur in zip(starts_ms, durations_ms):
        sets.append({
            "setType": "ACTIVE",
            "startTime": _epoch_ms_to_iso(st),
            "duration": dur / 1000,
            "exercises": [{"category": "SQUAT", "probability": 80.0}],
            "repetitionCount": 8,
        })
    metrics = []
    for sec in range(0, 80):
        metrics.append({"metrics": [float(sec * 1000), float(100 + (sec % 5))]})
    metrics.append({"metrics": [60_000.0, 95.0]})
    metrics.append({"metrics": [100_000.0, 96.0]})
    return {
        "summary": {},
        "details": {
            "metricDescriptors": [
                {"metricsIndex": 0, "key": "directTimestamp"},
                {"metricsIndex": 1, "key": "directHeartRate"},
            ],
            "activityDetailMetrics": metrics,
        },
        "exercise_sets": {"activityId": 1, "exerciseSets": sets},
    }


def _make_auto_matched_workout(session) -> Workout:
    train = make_xunji_train(session, DAY, localid="bf1", title="腿", movements=BACKFILL_MOVEMENTS)
    activity = make_garmin_activity(session, DAY, activity_id="g_bf_1")
    activity.raw_json = json.dumps(_build_two_set_raw(), ensure_ascii=False)
    session.commit()
    return fuse_workout(session, DAY, xunji=train, garmin=activity, match_status="auto_matched")


# ---------- 1. 回填写行 + 幂等 ----------

def test_run_backfill_writes_rows_and_is_idempotent(session):
    """1 个 auto_matched workout（完整佳明数据，2 组）→ 第一遍 2 行；第二遍行数不变。"""
    workout = _make_auto_matched_workout(session)

    stats1 = run_backfill(session)
    assert stats1["scanned"] == 1
    assert stats1["with_rows"] == 1
    assert stats1["rows"] == 2
    assert stats1["no_data"] == 0
    assert stats1["failed"] == 0
    rows_after_first = session.query(WorkoutSetHr).filter(
        WorkoutSetHr.workout_id == workout.id
    ).all()
    assert len(rows_after_first) == 2

    # 第二遍幂等：行数不变、stats 相同
    stats2 = run_backfill(session)
    assert stats2 == stats1
    rows_after_second = session.query(WorkoutSetHr).filter(
        WorkoutSetHr.workout_id == workout.id
    ).all()
    assert len(rows_after_second) == 2


# ---------- 2. 跳过 unmatched / 已软删 ----------

def test_run_backfill_skips_unmatched_and_deleted(session):
    """xunji_only + garmin_only + 已软删 matched → scanned 只含未删 matched，不产行。"""
    # xunji_only
    x = make_xunji_train(session, DAY, localid="xj_only", title="xj")
    fuse_workout(session, DAY, xunji=x, match_status="xunji_only")
    # garmin_only
    g_only = make_garmin_activity(session, DAY, activity_id="g_only")
    fuse_workout(session, DAY, garmin=g_only, match_status="garmin_only")
    # matched 但被软删
    matched = _make_auto_matched_workout(session)
    delete_workout(session, matched.id)

    stats = run_backfill(session)
    # scanned 只包含未软删 + 双关联的 workout；上面 matched 已被删
    assert stats["scanned"] == 0
    assert stats["with_rows"] == 0
    assert stats["rows"] == 0
    assert stats["no_data"] == 0
    assert stats["failed"] == 0
    # 整个库也没建 WorkoutSetHr 行
    assert session.query(WorkoutSetHr).count() == 0


# ---------- 3. matched 但无 exercise_sets → no_data ----------

def test_run_backfill_no_exercise_sets_counts_no_data(session):
    """matched 但佳明无 exercise_sets → no_data==1，不建行。"""
    train = make_xunji_train(session, DAY, localid="no_es", title="x", movements=BACKFILL_MOVEMENTS)
    activity = make_garmin_activity(session, DAY, activity_id="g_no_es")
    activity.raw_json = json.dumps(
        {
            "summary": {},
            "details": {
                "metricDescriptors": [
                    {"metricsIndex": 0, "key": "directTimestamp"},
                    {"metricsIndex": 1, "key": "directHeartRate"},
                ],
                "activityDetailMetrics": [{"metrics": [1000.0, 110.0]}],
            },
            "exercise_sets": None,
        },
        ensure_ascii=False,
    )
    session.commit()
    fuse_workout(session, DAY, xunji=train, garmin=activity, match_status="auto_matched")

    stats = run_backfill(session)
    assert stats["scanned"] == 1
    assert stats["no_data"] == 1
    assert stats["with_rows"] == 0
    assert stats["rows"] == 0
    assert session.query(WorkoutSetHr).count() == 0


# ---------- 4. builder 注入 set_hr 段（含 1 个 low） ----------

def test_builder_injects_set_hr_section():
    """直接调 build_session_review_prompt，最小 workout + 2 组 set_hr（含 1 个 low）→ user 内容含段标题、均值序列、低置信提示行。"""
    workout_dict = {
        "date": "2026-08-05",
        "title": "腿",
        "movements": [
            {
                "name": "深蹲",
                "sets": [
                    {"weight": "60", "unit": "kg", "reps": "8", "done": True},
                    {"weight": "60", "unit": "kg", "reps": "8", "done": True},
                ],
            },
        ],
    }
    history: dict = {}
    recovery = {"days_count": 0, "weight_trend": []}
    set_hr = [
        {
            "movement_name": "深蹲",
            "set_index": 1,
            "hr_avg": 100,
            "hr_max": 110,
            "hr_min": 95,
            "hr_recovery_30s": 120,
            "confidence": "high",
        },
        {
            "movement_name": "深蹲",
            "set_index": 2,
            "hr_avg": 105,
            "hr_max": 112,
            "hr_min": 99,
            "hr_recovery_30s": 125,
            "confidence": "low",
        },
    ]
    messages = build_session_review_prompt(
        workout_dict, history, recovery, set_hr=set_hr,
    )
    user = messages[1]["content"]
    assert "## 逐组心率（佳明实测，供分析组间强度变化与恢复）" in user
    assert "- 深蹲：" in user
    assert "组中心率均值：100 → 105 bpm" in user
    assert "组中心率峰值：110 → 112 bpm" in user
    assert "组后30秒恢复心率：120 → 125 bpm" in user
    assert "第 2 组为低置信匹配" in user


# ---------- 5. builder 不传 set_hr → 与不传/None 完全一致，且不含段标题 ----------

def test_builder_without_set_hr_unchanged():
    """不传 set_hr vs set_hr=None 输出完全相等，且不含「逐组心率」。"""
    workout_dict = {
        "date": "2026-08-05",
        "title": "腿",
        "movements": [
            {
                "name": "深蹲",
                "sets": [{"weight": "60", "unit": "kg", "reps": "8", "done": True}],
            },
        ],
    }
    history: dict = {}
    recovery = {"days_count": 0, "weight_trend": []}

    msgs_default = build_session_review_prompt(workout_dict, history, recovery)
    msgs_none = build_session_review_prompt(workout_dict, history, recovery, set_hr=None)
    msgs_empty = build_session_review_prompt(workout_dict, history, recovery, set_hr=[])

    assert msgs_default == msgs_none
    assert msgs_default == msgs_empty
    assert "逐组心率" not in msgs_default[1]["content"]


# ---------- 6. generate_session_review 注入（有 WorkoutSetHr 行） ----------

def test_generate_session_review_injects_when_rows_exist(session):
    """fuse workout + 落 WorkoutSetHr 行 + fake chat_fn 捕获 messages → 末条 user 含「## 逐组心率」。"""
    workout = _make_auto_matched_workout(session)

    # 先手动落 WorkoutSetHr 行（绕过 compute_workout_set_hr 的 commit，简化测试）
    s1 = WorkoutSetHr(
        workout_id=workout.id, movement_name="深蹲", set_index=1,
        hr_avg=100, hr_max=110, hr_min=95, hr_recovery_30s=120,
        confidence="high", match_method="order",
    )
    s2 = WorkoutSetHr(
        workout_id=workout.id, movement_name="深蹲", set_index=2,
        hr_avg=105, hr_max=112, hr_min=99, hr_recovery_30s=125,
        confidence="low", match_method="order_category_mismatch",
    )
    session.add_all([s1, s2])
    session.commit()

    captured: dict = {}

    def fake_chat(messages):
        captured["messages"] = messages
        return {
            "content": (
                "## 完成质量\n不错\n## 与历史对比\n持平\n"
                '```json\n{"schema":"session_review_v1","score":82,'
                '"subscores":{"completion":85,"intensity":80,"recovery_fit":82},'
                '"one_liner":"稳定发挥"}\n```'
            ),
            "prompt_tokens": 100,
            "completion_tokens": 20,
        }

    report = generate_session_review(session, workout.id, chat_fn=fake_chat)
    assert report.workout_id == workout.id
    user = captured["messages"][-1]["content"]
    assert "## 逐组心率（佳明实测，供分析组间强度变化与恢复）" in user
    assert "组中心率均值：100 → 105 bpm" in user
    assert "第 2 组为低置信匹配" in user


# ---------- 7. generate_session_review 不注入（无 WorkoutSetHr 行） ----------

def test_generate_session_review_no_rows_no_section(session):
    """无 WorkoutSetHr 行 → prompt 不含「逐组心率」。"""
    workout = _make_auto_matched_workout(session)
    # 不落 WorkoutSetHr 行；直接生成点评
    assert session.query(WorkoutSetHr).filter(WorkoutSetHr.workout_id == workout.id).count() == 0

    captured: dict = {}

    def fake_chat(messages):
        captured["messages"] = messages
        return {
            "content": (
                "## 完成质量\n不错\n## 与历史对比\n持平\n"
                '```json\n{"schema":"session_review_v1","score":80,'
                '"subscores":{"completion":80,"intensity":80,"recovery_fit":80},'
                '"one_liner":"中规中矩"}\n```'
            ),
            "prompt_tokens": 100,
            "completion_tokens": 20,
        }

    report = generate_session_review(session, workout.id, chat_fn=fake_chat)
    assert report.workout_id == workout.id
    user = captured["messages"][-1]["content"]
    assert "逐组心率" not in user
