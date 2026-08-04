"""M4 字段级融合测试（严格按 PRD §5.2）。

动作维度 → 训记；时长/热量/心率 → 佳明；标题 → 训记（佳明类型作标签）。
"""
import json
from datetime import date

import pytest
from tests.conftest import make_garmin_activity, make_xunji_train

from app.models import Workout
from app.services.fuse import fuse_workout

DAY = date(2026, 8, 3)

MOVEMENTS = [
    {"name": "引体向上", "sets": [{"weight": "0", "unit": "kg", "reps": "8", "done": True}]},
    {"name": "杠铃划船", "sets": [{"weight": "60", "unit": "kg", "reps": "10", "done": True}]},
]


def test_fuse_both_sides_field_priority(session):
    """双侧融合：movements 取训记，时长/热量/心率取佳明，标题取训记，佳明类型作标签。"""
    x = make_xunji_train(session, DAY, localid="1", title="背二头2", movements=MOVEMENTS)
    g = make_garmin_activity(session, DAY, activity_id="g1",
                             activity_type="strength_training", name="力量训练",
                             duration_s=3600, calories=456, avg_hr=118, max_hr=152)

    w = fuse_workout(session, DAY, xunji=x, garmin=g, match_status="auto_matched")

    assert w.date == DAY
    assert w.title == "背二头2"                       # 标题取训记
    assert w.tags == "strength_training"              # 佳明类型作标签
    assert w.duration_s == 3600                       # 时长/热量/心率取佳明
    assert w.calories == 456
    assert w.avg_hr == 118
    assert w.max_hr == 152
    assert json.loads(w.movements_json) == MOVEMENTS  # 动作维度取训记
    assert w.match_status == "auto_matched"


def test_fuse_foreign_keys_traceable(session):
    """融合记录保留两侧外键，可追溯回原始记录。"""
    x = make_xunji_train(session, DAY, localid="1", movements=MOVEMENTS)
    g = make_garmin_activity(session, DAY, activity_id="g1")

    w = fuse_workout(session, DAY, xunji=x, garmin=g, match_status="auto_matched")

    assert w.xunji_train_id == x.id
    assert w.garmin_activity_id == g.id
    # 外键有效：能查回原始行
    assert session.get(type(x), w.xunji_train_id).localid == "1"
    assert session.get(type(g), w.garmin_activity_id).activity_id == "g1"


def test_fuse_xunji_only_keeps_only_xunji_fields(session):
    """缺佳明数据：workout 仅训记维度，佳明字段为空。"""
    x = make_xunji_train(session, DAY, localid="1", title="背二头2", movements=MOVEMENTS)

    w = fuse_workout(session, DAY, xunji=x, match_status="xunji_only")

    assert w.title == "背二头2"
    assert json.loads(w.movements_json) == MOVEMENTS
    assert w.duration_s is None
    assert w.calories is None
    assert w.avg_hr is None
    assert w.max_hr is None
    assert w.tags is None
    assert w.garmin_activity_id is None
    assert w.xunji_train_id == x.id


def test_fuse_garmin_only_keeps_only_garmin_fields(session):
    """缺训记数据：workout 仅佳明维度，动作/标题取佳明兜底。"""
    g = make_garmin_activity(session, DAY, activity_id="g1",
                             activity_type="running", name="晨跑", calories=200)

    w = fuse_workout(session, DAY, garmin=g, match_status="garmin_only")

    assert w.title == "晨跑"
    assert w.tags == "running"
    assert w.calories == 200
    assert w.movements_json is None
    assert w.xunji_train_id is None
    assert w.garmin_activity_id == g.id


def test_fuse_neither_side_raises(session):
    with pytest.raises(ValueError):
        fuse_workout(session, DAY, match_status="xunji_only")


def test_fuse_xunji_without_movements(session):
    """训记原始数据无 movements 字段时 movements_json 为 None。"""
    x = make_xunji_train(session, DAY, localid="1", title="有氧")  # 无 movements

    w = fuse_workout(session, DAY, xunji=x, match_status="xunji_only")

    assert w.movements_json is None


def test_fuse_xunji_empty_movements_list(session):
    """movements 为空列表时视为无动作数据。"""
    x = make_xunji_train(session, DAY, localid="1", movements=[])

    w = fuse_workout(session, DAY, xunji=x, match_status="xunji_only")

    assert w.movements_json is None


def test_fuse_xunji_corrupt_raw_json(session):
    """raw_json 损坏时不抛错，movements_json 为 None。"""
    x = make_xunji_train(session, DAY, localid="1", movements=MOVEMENTS)
    x.raw_json = "{not valid json"
    session.commit()

    w = fuse_workout(session, DAY, xunji=x, match_status="xunji_only")

    assert w.movements_json is None


def test_fuse_persists_to_db(session):
    x = make_xunji_train(session, DAY, localid="1", movements=MOVEMENTS)

    fuse_workout(session, DAY, xunji=x, match_status="xunji_only")

    assert session.query(Workout).count() == 1
