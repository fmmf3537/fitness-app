"""V5-3 L3 长期统计：query_longterm_stats 聚合与过滤。"""
from __future__ import annotations

import json
from datetime import date, timedelta

from app.models import BodyMetric, Workout
from app.services.longterm_stats import (
    LONGTERM_WEEKS,
    _last_n_weeks_range,
    query_longterm_stats,
)

ANCHOR = date(2026, 9, 1)


def _mv(name: str, weight: float, reps: int = 10) -> dict:
    return {
        "name": name,
        "sets": [{"weight": weight, "unit": "kg", "reps": reps, "done": True}],
    }


def _add_workout(session, day: date, movements, *, duration_s=3600, calories=300, title="训"):
    w = Workout(
        date=day,
        title=title,
        match_status="auto_matched",
        duration_s=duration_s,
        calories=calories,
        movements_json=json.dumps(movements, ensure_ascii=False),
    )
    session.add(w)
    session.commit()
    return w


class TestLastNWeeksRange:
    def test_range_excludes_anchor(self):
        start, end = _last_n_weeks_range(ANCHOR, weeks=12)
        assert start == ANCHOR - timedelta(days=84)
        assert end == ANCHOR - timedelta(days=1)


class TestQueryLongtermStats:
    def test_empty_db_returns_none(self, session):
        assert query_longterm_stats(session, ANCHOR) is None

    def test_anchor_excluded(self, session):
        # 锚点日当天有训练，窗口内无 → None
        _add_workout(session, ANCHOR, [_mv("卧推", 60)])
        assert query_longterm_stats(session, ANCHOR) is None

        # 锚点前一天有训练 → 计入
        _add_workout(session, ANCHOR - timedelta(days=1), [_mv("卧推", 60)])
        result = query_longterm_stats(session, ANCHOR)
        assert result is not None
        assert "训练频率" in result

    def test_training_frequency_per_week(self, session):
        # 3 个训练日分布在锚点前 1/2/3 天
        # 公式 training_days / weeks = 3 / 12 = 0.25 → _fmt_freq → round(0.25, 1) = 0.2
        for i in range(3):
            _add_workout(
                session,
                ANCHOR - timedelta(days=1 + i),
                [_mv("深蹲", 100)],
            )
        result = query_longterm_stats(session, ANCHOR)
        assert result is not None
        assert result["训练频率"] == "0.2 次/周（3 个训练日，共 12 周）"

    def test_total_volume_and_avg_duration(self, session):
        # 卧推 50×10 = 500kg；两次各 3600s → 平均 60 分钟
        _add_workout(
            session, ANCHOR - timedelta(days=2),
            [_mv("卧推", 50, 10)], duration_s=3600, calories=200,
        )
        _add_workout(
            session, ANCHOR - timedelta(days=5),
            [_mv("卧推", 50, 10)], duration_s=3600, calories=400,
        )
        result = query_longterm_stats(session, ANCHOR)
        assert result is not None
        assert result["总容量"] == "1000 kg（2 次有效组）"
        assert result["平均时长"] == "60 分钟/次"

    def test_avg_calories(self, session):
        _add_workout(
            session, ANCHOR - timedelta(days=3),
            [_mv("深蹲", 80)], duration_s=1800, calories=200,
        )
        _add_workout(
            session, ANCHOR - timedelta(days=10),
            [_mv("深蹲", 80)], duration_s=1800, calories=400,
        )
        result = query_longterm_stats(session, ANCHOR)
        assert result is not None
        assert result["平均热量"] == "300 千卡/次"

    def test_part_distribution_top_5(self, session):
        # 6 个部位，容量降序；只取 top-5
        parts = [
            ("卧推", 100),   # 胸 1000
            ("深蹲", 80),    # 腿 800
            ("划船", 70),    # 背 700
            ("推举", 50),    # 肩 500
            ("弯举", 40),    # 臂 400
            ("卷腹", 10),    # 核心 100 — 应被裁掉
        ]
        movements = [_mv(name, w, 10) for name, w in parts]
        _add_workout(session, ANCHOR - timedelta(days=4), movements)
        result = query_longterm_stats(session, ANCHOR)
        assert result is not None
        dist = result["部位分布"]
        assert dist.startswith("胸 1000 kg")
        assert "腿 800 kg" in dist
        assert "背 700 kg" in dist
        assert "肩 500 kg" in dist
        assert "臂 400 kg" in dist
        assert "核心" not in dist
        assert dist.count(" / ") == 4  # 5 段

    def test_pr_events_count(self, session):
        # 窗口前历史最佳 60；窗口内 80 → 1 次 PR
        hist = ANCHOR - timedelta(days=90)
        _add_workout(session, hist, [_mv("卧推", 60)])
        _add_workout(session, ANCHOR - timedelta(days=7), [_mv("卧推", 80)])
        result = query_longterm_stats(session, ANCHOR)
        assert result is not None
        assert result["PR 事件"] == "1 次突破历史最大重量"

    def test_pr_events_zero_hidden(self, session):
        # 仅窗口内训练、无历史最佳 → 不算 PR，字段不出现
        _add_workout(session, ANCHOR - timedelta(days=7), [_mv("卧推", 80)])
        result = query_longterm_stats(session, ANCHOR)
        assert result is not None
        assert "PR 事件" not in result

    def test_weight_trend_with_delta(self, session):
        start, end = _last_n_weeks_range(ANCHOR)
        session.add(BodyMetric(date=start, type="weight", value=75.0, unit="kg"))
        session.add(BodyMetric(date=end, type="weight", value=73.5, unit="kg"))
        _add_workout(session, ANCHOR - timedelta(days=2), [_mv("深蹲", 100)])
        session.commit()
        result = query_longterm_stats(session, ANCHOR)
        assert result is not None
        assert result["体重趋势"] == "73.5 kg（Δ-1.5）"

    def test_weight_trend_no_data_hidden(self, session):
        _add_workout(session, ANCHOR - timedelta(days=2), [_mv("深蹲", 100)])
        result = query_longterm_stats(session, ANCHOR)
        assert result is not None
        assert "体重趋势" not in result

    def test_short_window_2_weeks(self, session):
        # weeks=2：仅最近 14 天；更早的不计入
        _add_workout(session, ANCHOR - timedelta(days=3), [_mv("卧推", 60)])
        _add_workout(session, ANCHOR - timedelta(days=20), [_mv("深蹲", 100)])
        result = query_longterm_stats(session, ANCHOR, weeks=2)
        assert result is not None
        assert "共 2 周" in result["训练频率"]
        assert result["训练频率"] == "0.5 次/周（1 个训练日，共 2 周）"
        # 总容量只有卧推 60×10
        assert result["总容量"].startswith("600 kg")

    def test_default_weeks_constant(self):
        assert LONGTERM_WEEKS == 12
