"""M5-1 排行榜服务层测试。"""
import json
from datetime import date, timedelta

from sqlalchemy import select

from app.models import JobRun, LeaderboardCache, Setting, Workout
from app.services import leaderboard as lb
from app.services import users as user_service

TODAY = date(2026, 8, 25)


def _user(session, name, **kw):
    existing = user_service.get_user_by_username(session, name)
    if existing:
        return existing
    return user_service.create_user(session, username=name, password="test-pass", **kw)


def _workout(session, user_id, day, *, duration_s=3600, calories=300, title="w"):
    w = Workout(
        user_id=user_id, date=day, title=title,
        duration_s=duration_s, calories=calories,
    )
    session.add(w)
    session.commit()
    return w


def _opt_out(session, user_id, metrics: dict):
    row = session.scalars(select(Setting).where(Setting.user_id == user_id)).first()
    if row is None:
        row = Setting(user_id=user_id)
        session.add(row)
        session.flush()
    row.leaderboard_opt_out_json = json.dumps(metrics)
    session.commit()


class TestOptIn:
    def test_default_opted_in(self, session):
        alice = _user(session, "alice")
        assert lb._is_opted_in(session, alice.id, "frequency") is True

    def test_opt_out_metric(self, session):
        alice = _user(session, "alice")
        _opt_out(session, alice.id, {"frequency": True, "volume": False})
        assert lb._is_opted_in(session, alice.id, "frequency") is False
        assert lb._is_opted_in(session, alice.id, "volume") is True


class TestCompute:
    def test_frequency_excludes_opt_out(self, session):
        alice = _user(session, "alice")
        bob = _user(session, "bob")
        _workout(session, alice.id, TODAY)
        _workout(session, alice.id, TODAY - timedelta(days=1))
        _workout(session, bob.id, TODAY)
        _opt_out(session, bob.id, {"frequency": True})

        rows = lb.compute_frequency(session, 7, now=TODAY)
        ids = {r["user_id"] for r in rows}
        assert alice.id in ids
        assert bob.id not in ids
        alice_row = next(r for r in rows if r["user_id"] == alice.id)
        assert alice_row["value"] == 2
        assert alice_row["rank"] == 1

    def test_volume_and_calories_differ(self, session):
        alice = _user(session, "alice")
        _workout(session, alice.id, TODAY, duration_s=7200, calories=500)
        vol = lb.compute_volume(session, 7, now=TODAY)
        cal = lb.compute_calories(session, 7, now=TODAY)
        assert vol[0]["value"] == 7200
        assert cal[0]["value"] == 500

    def test_streak_distinct_dates(self, session):
        alice = _user(session, "alice")
        _workout(session, alice.id, TODAY)
        _workout(session, alice.id, TODAY)  # same day
        _workout(session, alice.id, TODAY - timedelta(days=1))
        rows = lb.compute_streak(session, 7, now=TODAY)
        assert rows[0]["value"] == 2

    def test_compute_metric_ranked(self, session):
        alice = _user(session, "alice")
        bob = _user(session, "bob")
        _workout(session, alice.id, TODAY)
        _workout(session, alice.id, TODAY - timedelta(days=1))
        _workout(session, bob.id, TODAY)
        rows = lb.compute_metric(session, "frequency", 7, now=TODAY)
        assert [r["rank"] for r in rows] == list(range(1, len(rows) + 1))
        assert rows[0]["value"] >= rows[-1]["value"]


class TestCache:
    def test_get_cached_miss(self, session):
        assert lb.get_cached(session, "frequency", "7d") is None

    def test_save_and_get_cached(self, session):
        payload = [{"user_id": 1, "username": "alice", "value": 3, "rank": 1}]
        lb.save_cached(session, "frequency", "7d", payload)
        assert lb.get_cached(session, "frequency", "7d") == payload
        # upsert
        payload2 = [{"user_id": 1, "username": "alice", "value": 5, "rank": 1}]
        lb.save_cached(session, "frequency", "7d", payload2)
        rows = session.scalars(select(LeaderboardCache)).all()
        assert len(rows) == 1
        assert lb.get_cached(session, "frequency", "7d") == payload2


class TestPrecompute:
    def test_writes_eight_rows_and_job_run(self, session):
        alice = _user(session, "alice")
        _workout(session, alice.id, TODAY, duration_s=1800, calories=200)
        result = lb.precompute_leaderboards(session=session, now=TODAY)
        assert result["computed"] == 8
        assert result["failed"] == []
        rows = session.scalars(select(LeaderboardCache)).all()
        assert len(rows) == 8
        combos = {(r.metric, r.window) for r in rows}
        assert combos == {(m, w) for m in lb.METRICS for w in lb.WINDOWS}
        jobs = session.scalars(
            select(JobRun).where(JobRun.job_name == "precompute_leaderboards")
        ).all()
        assert len(jobs) >= 1
        assert jobs[-1].status == "success"
