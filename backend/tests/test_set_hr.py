"""V4-7 逐组心率服务层单测：纯函数 + 编排函数幂等落库。"""
import json
import os
from datetime import date

from app.services.fuse import fuse_workout
from app.services.set_hr import (
    align_sets,
    compute_recovery_hr,
    compute_set_stats,
    compute_workout_set_hr,
    extract_active_sets,
    extract_hr_timeline,
)
from tests.conftest import make_garmin_activity, make_xunji_train

DAY = date(2026, 8, 4)


# ---------- 1. extract_hr_timeline ----------

REAL_DETAILS = {
    "metricDescriptors": [
        {"metricsIndex": 0, "key": "directTimestamp", "unit": "ms"},
        {"metricsIndex": 1, "key": "directHeartRate", "unit": "bpm"},
    ],
    "activityDetailMetrics": [
        {"metrics": [1785819172000.0, 80.0]},
        {"metrics": [1785819173000.0, None]},   # null hr 必须过滤
        {"metrics": [1785819174000.0, 82.0]},
        {"metrics": [1785819175000.0, 90.0]},
    ],
}

INDEX_DETAILS = {
    "metricDescriptors": [
        {"index": 0, "key": "directTimestamp"},
        {"index": 1, "key": "directHeartRate"},
    ],
    "activityDetailMetrics": [
        {"metrics": [1785819172000.0, 80.0]},
        {"metrics": [1785819174000.0, 82.0]},
    ],
}


def test_extract_hr_timeline_metrics_index_field():
    """真实佳明结构用 metricsIndex 定位列；null hr 行被过滤；按时间升序。"""
    raw = {"details": REAL_DETAILS}
    timeline = extract_hr_timeline(raw)
    assert timeline == [
        (1785819172000, 80),
        (1785819174000, 82),
        (1785819175000, 90),
    ]


def test_extract_hr_timeline_legacy_index_field():
    """旧测试 fixture 用 index 字段也能识别。"""
    raw = {"details": INDEX_DETAILS}
    assert extract_hr_timeline(raw) == [
        (1785819172000, 80),
        (1785819174000, 82),
    ]


def test_extract_hr_timeline_empty_or_missing():
    """无 details / 无 descriptors / 无 metricsIndex 与 index → []。"""
    assert extract_hr_timeline({}) == []
    assert extract_hr_timeline({"details": None}) == []
    assert extract_hr_timeline({"details": {}}) == []
    assert extract_hr_timeline({
        "details": {
            "metricDescriptors": [{"key": "directSpeed", "metricsIndex": 0}],
            "activityDetailMetrics": [{"metrics": [1.0]}],
        }
    }) == []


# ---------- 2. extract_active_sets ----------

MIXED_EXERCISE_SETS = {
    "exercise_sets": {
        "activityId": 1,
        "exerciseSets": [
            # REST 组（应跳过）
            {
                "setType": "REST",
                "startTime": "2026-08-04T04:50:00.0",
                "duration": 120.0,
                "exercises": [],
                "repetitionCount": None,
            },
            # ACTIVE 组 1：SQUAT
            {
                "setType": "ACTIVE",
                "startTime": "2026-08-04T04:52:52.0",
                "duration": 56.558,
                "exercises": [
                    {"category": "SQUAT", "name": None, "probability": 51.5},
                    {"category": "LUNGE", "name": None, "probability": 23.0},
                ],
                "repetitionCount": 5,
            },
            # ACTIVE 组 2：BENCH_PRESS（早于组 1，验证排序）
            {
                "setType": "ACTIVE",
                "startTime": "2026-08-04T04:51:30.0",
                "duration": 30.0,
                "exercises": [{"category": "BENCH_PRESS", "probability": 80.0}],
                "repetitionCount": 8,
            },
        ],
    }
}


def test_extract_active_sets_filters_and_sorts():
    """只取 ACTIVE，按 startTime 升序，category 取首候选。"""
    sets = extract_active_sets(MIXED_EXERCISE_SETS)
    assert len(sets) == 2
    # 早的 BENCH_PRESS 在前
    assert sets[0]["category"] == "BENCH_PRESS"
    assert sets[0]["start_ms"] == 1785819090000  # 2026-08-04T04:51:30.0
    assert sets[0]["end_ms"] == 1785819090000 + 30000
    assert sets[0]["reps"] == 8
    # 后的 SQUAT
    assert sets[1]["category"] == "SQUAT"
    assert sets[1]["start_ms"] == 1785819172000
    assert sets[1]["end_ms"] == 1785819172000 + 56558
    assert sets[1]["reps"] == 5


def test_extract_active_sets_timestamp_conversion():
    """startTime → epoch ms 换算正确（用例已知时间戳）。"""
    sets = extract_active_sets(MIXED_EXERCISE_SETS)
    squat = next(s for s in sets if s["category"] == "SQUAT")
    assert squat["start_ms"] == 1785819172000


def test_extract_active_sets_missing_exercise_sets_returns_empty():
    """exercise_sets 为 None / 不存在 → []，不抛异常。"""
    assert extract_active_sets({}) == []
    assert extract_active_sets({"exercise_sets": None}) == []
    assert extract_active_sets({"exercise_sets": {"exerciseSets": None}}) == []


# ---------- 3. align_sets 顺序对齐 ----------

def test_align_sets_order_match_all_high():
    """2 动作 × 2 组 = 4 个训项，对齐 4 个 ACTIVE；类别一致时全部 high/order。"""
    movements = [
        {"name": "硬拉", "sets": [{"done": True}, {"done": True}]},
        {"name": "卧推", "sets": [{"done": True}, {"done": True}]},
    ]
    active = [
        {"start_ms": 1_000, "end_ms": 2_000, "category": "DEADLIFT", "reps": 5},
        {"start_ms": 3_000, "end_ms": 4_000, "category": "DEADLIFT", "reps": 5},
        {"start_ms": 5_000, "end_ms": 6_000, "category": "BENCH_PRESS", "reps": 8},
        {"start_ms": 7_000, "end_ms": 8_000, "category": "BENCH_PRESS", "reps": 8},
    ]
    pairs = align_sets(movements, active)
    assert len(pairs) == 4
    assert all(p["confidence"] == "high" for p in pairs)
    assert all(p["match_method"] == "order" for p in pairs)
    assert [(p["movement_name"], p["set_index"]) for p in pairs] == [
        ("硬拉", 1), ("硬拉", 2), ("卧推", 1), ("卧推", 2),
    ]


# ---------- 4. align_sets 类别冲突降级 ----------

def test_align_sets_category_mismatch_downgrades_to_low():
    """佳明首候选 BENCH_PRESS 对齐到训记"硬拉"→ 子串不包含 → low/order_category_mismatch。"""
    movements = [{"name": "硬拉", "sets": [{"done": True}]}]
    active = [{"start_ms": 1, "end_ms": 2, "category": "BENCH_PRESS", "reps": 5}]
    pairs = align_sets(movements, active)
    assert pairs[0]["confidence"] == "low"
    assert pairs[0]["match_method"] == "order_category_mismatch"


def test_align_sets_substring_match_is_high():
    """映射名是 movement_name 子串视为一致：如 硬拉 ∈ 杠铃硬拉 → high。"""
    movements = [{"name": "杠铃硬拉", "sets": [{"done": True}]}]
    active = [{"start_ms": 1, "end_ms": 2, "category": "DEADLIFT", "reps": 5}]
    pairs = align_sets(movements, active)
    assert pairs[0]["confidence"] == "high"
    assert pairs[0]["match_method"] == "order"


def test_align_sets_empty_exercises_keeps_high():
    """佳明组 exercises 为空（无类别信息）→ 跳过校验 → high/order。"""
    movements = [{"name": "硬拉", "sets": [{"done": True}]}]
    active = [{"start_ms": 1, "end_ms": 2, "category": None, "reps": None}]
    pairs = align_sets(movements, active)
    assert pairs[0]["confidence"] == "high"
    assert pairs[0]["match_method"] == "order"


def test_align_sets_unknown_category_keeps_high():
    """未列入映射表的 category → 跳过校验（不降置信度）。"""
    movements = [{"name": "硬拉", "sets": [{"done": True}]}]
    active = [{"start_ms": 1, "end_ms": 2, "category": "SOME_UNKNOWN_CAT", "reps": 5}]
    pairs = align_sets(movements, active)
    assert pairs[0]["confidence"] == "high"
    assert pairs[0]["match_method"] == "order"


# ---------- 5. align_sets 跳过未执行组 ----------

def test_align_sets_skips_undone_groups():
    """训记第 2 组 done=False，佳明 2 个 ACTIVE 组应对齐到第 1、3 组。"""
    movements = [
        {
            "name": "卧推",
            "sets": [
                {"done": True},
                {"done": False},   # 跳过
                {"done": True},
            ],
        }
    ]
    active = [
        {"start_ms": 1, "end_ms": 2, "category": "BENCH_PRESS", "reps": 5},
        {"start_ms": 3, "end_ms": 4, "category": "BENCH_PRESS", "reps": 5},
    ]
    pairs = align_sets(movements, active)
    assert len(pairs) == 2
    assert pairs[0]["set_index"] == 1
    assert pairs[1]["set_index"] == 3


def test_align_sets_done_missing_means_executed():
    """done 字段缺失视为已执行。"""
    movements = [{"name": "卧推", "sets": [{}, {}]}]
    active = [
        {"start_ms": 1, "end_ms": 2, "category": "BENCH_PRESS", "reps": 5},
        {"start_ms": 3, "end_ms": 4, "category": "BENCH_PRESS", "reps": 5},
    ]
    pairs = align_sets(movements, active)
    assert len(pairs) == 2


# ---------- 6. compute_set_stats / compute_recovery_hr ----------

def test_compute_set_stats_window_inclusive_and_rounding():
    """窗口含端点；avg round 转 int。"""
    timeline = [
        (1000, 80),
        (1000, 81),     # 同时间戳多值都计入
        (1500, 100),
        (2000, 120),    # 端点包含
        (2500, 200),    # 窗口外忽略
    ]
    stats = compute_set_stats(timeline, 1000, 2000)
    assert stats == {"avg": 95, "max": 120, "min": 80}


def test_compute_set_stats_no_points_returns_none():
    """窗口无点 → None。"""
    assert compute_set_stats([], 1000, 2000) is None
    assert compute_set_stats([(5000, 90)], 1000, 2000) is None


def test_compute_recovery_hr_picks_closest_to_30s():
    """在 [end+25s, end+35s] 内取最接近 end+30s 的点。"""
    timeline = [
        (25000, 70),     # 差 5s
        (28000, 85),     # 差 2s
        (30000, 90),     # 差 0s → 胜出
        (31000, 92),     # 差 1s
        (35000, 95),     # 差 5s，端点
        (36000, 99),     # 窗口外
    ]
    assert compute_recovery_hr(timeline, 0) == 90


def test_compute_recovery_hr_window_miss_returns_none():
    """±5s 窗口内无点 → None。"""
    assert compute_recovery_hr([], 0) is None
    assert compute_recovery_hr([(40000, 88)], 0) is None   # 差 10s


# ---------- 7. compute_workout_set_hr 端到端幂等 ----------

E2E_MOVEMENTS = [
    {
        "name": "深蹲",
        "sets": [
            {"weight": "60", "unit": "kg", "reps": "8", "done": True},
            {"weight": "60", "unit": "kg", "reps": "8", "done": True},
        ],
    },
    {
        "name": "卧推",
        "sets": [
            {"weight": "40", "unit": "kg", "reps": "10", "done": True},
            {"weight": "40", "unit": "kg", "reps": "10", "done": True},
        ],
    },
]


def _make_mini_raw() -> dict:
    """4 个 ACTIVE 组（SQUAT×2、BENCH_PRESS×2）+ 充足 HR 点。"""
    # 组 1: SQUAT [0, 30s)；组 2: SQUAT [40s, 70s)；组 3: BENCH_PRESS [80s, 110s)；组 4: BENCH_PRESS [120s, 150s)
    starts_ms = [0, 40_000, 80_000, 120_000]
    durations_ms = [30_000, 30_000, 30_000, 30_000]
    categories = ["SQUAT", "SQUAT", "BENCH_PRESS", "BENCH_PRESS"]
    sets = []
    for st, dur, cat in zip(starts_ms, durations_ms, categories):
        sets.append({
            "setType": "ACTIVE",
            "startTime": _epoch_ms_to_iso(st),
            "duration": dur / 1000,
            "exercises": [{"category": cat, "probability": 80.0}],
            "repetitionCount": 5,
        })

    # HR timeline：每秒一点（组 1 窗口 [1000, 29000]，组 2 [41000, 69000]...）
    metrics = []
    for sec in range(0, 155):
        metrics.append({"metrics": [float(sec * 1000), float(100 + (sec % 5))]})
    # 恢复窗点：组 4 结束 (150000ms) +30s → 180000ms（常规序列止于 154s，窗口 [175000, 185000] 内唯一候选）
    metrics.append({"metrics": [180_000.0, 88.0]})

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


def _epoch_ms_to_iso(ms: int) -> str:
    from datetime import datetime, timezone, timedelta
    dt = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(milliseconds=ms)
    # 输出形如 "1970-01-01T00:00:30.0"
    sec = int(dt.timestamp())
    msec = ms - sec * 1000
    base = datetime.utcfromtimestamp(sec).strftime("%Y-%m-%dT%H:%M:%S")
    return f"{base}.{msec}"


def test_compute_workout_set_hr_end_to_end_idempotent(session):
    """完整链路：融合 workout → 解析 → 对齐 → 统计 → 落库；连调两次行数与数值一致。"""
    train = make_xunji_train(session, DAY, movements=E2E_MOVEMENTS)
    activity = make_garmin_activity(session, DAY, activity_id="g_e2e")
    activity.raw_json = json.dumps(_make_mini_raw(), ensure_ascii=False)
    session.commit()

    workout = fuse_workout(session, DAY, xunji=train, garmin=activity,
                           match_status="auto_matched")
    rows1 = compute_workout_set_hr(session, workout)
    assert len(rows1) == 4
    # 训记 4 组都参与：深蹲×2（SQUAT→深蹲）+ 卧推×2（BENCH_PRESS→卧推），全 high/order
    by_name = {(r.movement_name, r.set_index): r for r in rows1}
    assert ("深蹲", 1) in by_name and ("深蹲", 2) in by_name
    assert ("卧推", 1) in by_name and ("卧推", 2) in by_name
    for r in rows1:
        assert r.confidence == "high" and r.match_method == "order"
        assert r.hr_avg is not None and r.hr_max is not None and r.hr_min is not None

    # 恢复心率确定性断言：组 1/2/3 恢复目标落在常规网格点（hr=100）；
    # 组 4 结束 150000ms → 目标 180000ms，命中注入点 88（窗口内唯一候选）
    assert by_name[("深蹲", 1)].hr_recovery_30s == 100
    assert by_name[("深蹲", 2)].hr_recovery_30s == 100
    assert by_name[("卧推", 1)].hr_recovery_30s == 100
    assert by_name[("卧推", 2)].hr_recovery_30s == 88

    # 第二次调用应幂等：行数不变，数值一致（按真实 API 场景在两次请求间重开 session，
    # 避免同 session 复用产生 SQLAlchemy identity map 告警）
    from app.db import make_engine, make_session_factory
    engine = make_engine(os.environ["DATABASE_URL"])
    factory = make_session_factory(engine)
    s2 = factory()
    try:
        from app.models import Workout
        w2 = s2.get(Workout, workout.id)
        rows2 = compute_workout_set_hr(s2, w2)
        assert len(rows2) == 4
        by_name2 = {(r.movement_name, r.set_index): r for r in rows2}
        for key, r1 in by_name.items():
            r2 = by_name2[key]
            assert r1.hr_avg == r2.hr_avg
            assert r1.hr_max == r2.hr_max
            assert r1.hr_min == r2.hr_min
            assert r1.hr_recovery_30s == r2.hr_recovery_30s
            assert r1.confidence == r2.confidence
        # 验证数据库行数确实只有 4（不是 8）
        from app.models import WorkoutSetHr
        db_count = s2.query(WorkoutSetHr).filter(
            WorkoutSetHr.workout_id == workout.id
        ).count()
        assert db_count == 4
    finally:
        s2.close()
        engine.dispose()


def test_compute_workout_set_hr_no_exercise_sets_returns_empty_no_row(session):
    """佳明 raw_json 无 exercise_sets → 返回 []，数据库不建行。"""
    train = make_xunji_train(session, DAY, movements=E2E_MOVEMENTS)
    activity = make_garmin_activity(session, DAY, activity_id="g_no_es")
    activity.raw_json = json.dumps(
        {"summary": {}, "details": {}, "exercise_sets": None},
        ensure_ascii=False,
    )
    session.commit()

    from app.models import WorkoutSetHr
    workout = fuse_workout(session, DAY, xunji=train, garmin=activity,
                           match_status="auto_matched")
    rows = compute_workout_set_hr(session, workout)
    assert rows == []
    assert session.query(WorkoutSetHr).filter(
        WorkoutSetHr.workout_id == workout.id
    ).count() == 0


def test_compute_workout_set_hr_xunji_only_no_garmin_returns_empty(session):
    """仅训记 fusion（garmin_only 为反例；xunji_only 也无 raw）→ 返回 []。"""
    train = make_xunji_train(session, DAY, movements=E2E_MOVEMENTS)
    workout = fuse_workout(session, DAY, xunji=train, match_status="xunji_only")
    rows = compute_workout_set_hr(session, workout)
    assert rows == []