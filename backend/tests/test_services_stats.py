"""趋势统计纯逻辑单测：部位分类器 / 容量计算 / 周聚合 / 睡眠解析。"""
import json
from datetime import date

from app.services.stats import (
    body_metrics_series,
    classify_part,
    movements_volume_tons,
    parse_movements,
    parse_sleep_hours,
    set_volume_kg,
    sleep_volume_series,
    weekly_trends,
    week_monday,
)


class TestClassifyPart:
    def test_chest(self):
        assert classify_part("杠铃卧推") == "胸"
        assert classify_part("上斜推胸") == "胸"
        assert classify_part("哑铃飞鸟") == "胸"

    def test_back(self):
        assert classify_part("引体向上") == "背"
        assert classify_part("杠铃划船") == "背"
        assert classify_part("高位下拉") == "背"
        assert classify_part("背部训练") == "背"

    def test_legs(self):
        assert classify_part("杠铃深蹲") == "腿"
        assert classify_part("硬拉") == "腿"
        assert classify_part("箭步蹲") == "腿"
        assert classify_part("臀桥") == "腿"

    def test_shoulders(self):
        assert classify_part("哑铃推举") == "肩"
        assert classify_part("侧平举") == "肩"
        assert classify_part("肩部训练") == "肩"

    def test_arms(self):
        assert classify_part("哑铃弯举") == "臂"
        assert classify_part("双杠臂屈伸") == "臂"
        assert classify_part("肱二头肌弯举") == "臂"

    def test_core(self):
        assert classify_part("平板支撑") == "核心"
        assert classify_part("卷腹") == "核心"
        assert classify_part("腹肌轮") == "核心"

    def test_cardio(self):
        assert classify_part("跑步机") == "有氧"
        assert classify_part("动感单车骑行") == "有氧"
        assert classify_part("游泳") == "有氧"
        assert classify_part("椭圆机") == "有氧"

    def test_other(self):
        assert classify_part("俯卧撑") == "其他"  # 不含规格关键词，归其他
        assert classify_part("神秘动作") == "其他"
        assert classify_part("") == "其他"
        assert classify_part(None) == "其他"


class TestSetVolumeKg:
    def test_basic(self):
        assert set_volume_kg({"weight": 60, "reps": 10, "done": True}) == 600.0

    def test_done_missing_counts(self):
        assert set_volume_kg({"weight": 60, "reps": 10}) == 600.0

    def test_done_false_skipped(self):
        assert set_volume_kg({"weight": 60, "reps": 10, "done": False}) == 0.0

    def test_zero_weight_skipped(self):
        assert set_volume_kg({"weight": 0, "reps": 10, "done": True}) == 0.0

    def test_time_set_skipped(self):
        # time 组：reps 为 0 / 缺失，不计容量
        assert set_volume_kg({"weight": 0, "reps": 0, "time": 60, "done": True}) == 0.0
        assert set_volume_kg({"weight": 50, "time": 60, "done": True}) == 0.0

    def test_string_numbers(self):
        assert set_volume_kg({"weight": "80", "reps": "5", "done": True}) == 400.0

    def test_bad_values(self):
        assert set_volume_kg({"weight": "abc", "reps": 10}) == 0.0
        assert set_volume_kg("not-a-dict") == 0.0


class TestMovementsVolumeTons:
    def test_sums_and_rounds(self):
        movements = [
            {"name": "卧推", "sets": [
                {"weight": 60, "reps": 10, "done": True},
                {"weight": 60, "reps": 8, "done": True},
                {"weight": 80, "reps": 5, "done": False},  # 未完成不计
            ]},
            {"name": "引体向上", "sets": [{"weight": 0, "reps": 8, "done": True}]},
        ]
        # (600 + 480) / 1000 = 1.08 吨
        assert movements_volume_tons(movements) == 1.08

    def test_empty(self):
        assert movements_volume_tons([]) == 0.0
        assert movements_volume_tons(None) == 0.0

    def test_non_dict_movement_ignored(self):
        assert movements_volume_tons(["bad", {"name": "卧推", "sets": [
            {"weight": 100, "reps": 10, "done": True}]}]) == 1.0


class TestParseMovements:
    def test_json_string(self):
        assert parse_movements('[{"name": "卧推", "sets": []}]') == [{"name": "卧推", "sets": []}]

    def test_list_passthrough(self):
        assert parse_movements([{"name": "卧推"}]) == [{"name": "卧推"}]

    def test_invalid(self):
        assert parse_movements(None) == []
        assert parse_movements("") == []
        assert parse_movements("not json") == []
        assert parse_movements('{"a": 1}') == []


class TestWeekMonday:
    def test_monday_of_week(self):
        assert week_monday(date(2026, 8, 7)) == date(2026, 8, 3)  # 周五 -> 周一
        assert week_monday(date(2026, 8, 3)) == date(2026, 8, 3)  # 周一当天


class TestWeeklyTrends:
    def test_continuous_weeks_with_zero_fill(self):
        start = date(2026, 7, 15)  # 周三
        end = date(2026, 8, 5)  # 周三，跨 4 个 ISO 周
        weekly_volume, body_part_frequency = weekly_trends([], start, end)
        expected_starts = ["2026-07-13", "2026-07-20", "2026-07-27", "2026-08-03"]
        assert [w["week_start"] for w in weekly_volume] == expected_starts
        assert all(w["volume_tons"] == 0 and w["sessions"] == 0 for w in weekly_volume)
        assert [b["week_start"] for b in body_part_frequency] == expected_starts
        assert all(b["parts"] == {} for b in body_part_frequency)

    def test_aggregates_volume_sessions_and_parts(self):
        start = date(2026, 8, 3)
        end = date(2026, 8, 9)
        workouts = [
            {"date": date(2026, 8, 3), "movements": [
                {"name": "卧推", "sets": [{"weight": 60, "reps": 10, "done": True}]},
                {"name": "飞鸟", "sets": [{"weight": 10, "reps": 10, "done": True}]},
                {"name": "引体向上", "sets": [{"weight": 0, "reps": 8, "done": True}]},
            ]},
            {"date": date(2026, 8, 5), "movements": [
                {"name": "深蹲", "sets": [{"weight": 100, "reps": 5, "done": True}]},
            ]},
            {"date": date(2026, 7, 30), "movements": [  # 范围外，忽略
                {"name": "卧推", "sets": [{"weight": 999, "reps": 10}]},
            ]},
        ]
        weekly_volume, body_part_frequency = weekly_trends(workouts, start, end)
        assert len(weekly_volume) == 1
        w = weekly_volume[0]
        assert w["week_start"] == "2026-08-03"
        assert w["sessions"] == 2
        # 600 + 100 + 500 = 1200 kg = 1.2 吨
        assert w["volume_tons"] == 1.2
        parts = body_part_frequency[0]["parts"]
        assert parts == {"胸": 2, "背": 1, "腿": 1}

    def test_non_dict_movement_ignored_in_parts(self):
        workouts = [{"date": date(2026, 8, 3), "movements": ["bad-entry", None]}]
        weekly_volume, body_part_frequency = weekly_trends(
            workouts, date(2026, 8, 3), date(2026, 8, 9))
        assert weekly_volume[0]["sessions"] == 1
        assert body_part_frequency[0]["parts"] == {}


class TestBodyMetricsSeries:
    def test_splits_by_type(self):
        rows = [
            (date(2026, 7, 15), "weight", 72.4),
            (date(2026, 7, 15), "bodyfat", 18.2),
            (date(2026, 7, 16), "bp_systolic", 120.0),  # 非目标类型忽略
            (date(2026, 7, 16), "weight", 72.1),
        ]
        result = body_metrics_series(rows)
        assert result["weight"] == [
            {"date": "2026-07-15", "value": 72.4},
            {"date": "2026-07-16", "value": 72.1},
        ]
        assert result["bodyfat"] == [{"date": "2026-07-15", "value": 18.2}]

    def test_empty(self):
        assert body_metrics_series([]) == {"weight": [], "bodyfat": []}


class TestParseSleepHours:
    def test_sleep_time_seconds_string(self):
        assert parse_sleep_hours(json.dumps({"sleepTimeSeconds": 25920})) == 7.2

    def test_duration_key(self):
        assert parse_sleep_hours({"duration": 25200}) == 7.0

    def test_snake_case_key(self):
        assert parse_sleep_hours({"sleep_time_seconds": 27000}) == 7.5

    def test_nested_dict(self):
        data = {"dailySleepDTO": {"sleepTimeSeconds": 25920}}
        assert parse_sleep_hours(json.dumps(data)) == 7.2

    def test_unparseable(self):
        assert parse_sleep_hours(None) is None
        assert parse_sleep_hours("not json") is None
        assert parse_sleep_hours({"foo": 1}) is None
        assert parse_sleep_hours([1, 2]) is None


class TestSleepVolumeSeries:
    def test_joins_sleep_with_daily_volume(self):
        sleep_rows = [
            (date(2026, 8, 5), json.dumps({"sleepTimeSeconds": 25920})),
            (date(2026, 8, 4), {"duration": 25200}),
            (date(2026, 8, 3), "garbage"),  # 解析不出，跳过
        ]
        workouts = [
            {"date": date(2026, 8, 5), "movements": [
                {"name": "卧推", "sets": [{"weight": 100, "reps": 10, "done": True}]},
                {"name": "卧推", "sets": [{"weight": 100, "reps": 10, "done": True}]},
            ]},
        ]
        result = sleep_volume_series(sleep_rows, workouts)
        assert result == [
            {"date": "2026-08-04", "sleep_hours": 7.0, "volume_tons": 0.0},
            {"date": "2026-08-05", "sleep_hours": 7.2, "volume_tons": 2.0},
        ]

    def test_empty(self):
        assert sleep_volume_series([], []) == []
