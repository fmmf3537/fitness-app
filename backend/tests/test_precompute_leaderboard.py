"""M5-1 precompute_leaderboards 端到端测试。"""
import json
from datetime import date, timedelta

from sqlalchemy import select

from app.models import LeaderboardCache, Setting, Workout
from app.services import leaderboard as lb
from app.services import users as user_service

TODAY = date(2026, 8, 25)


def test_precompute_eight_rows_excludes_opt_out(session):
    alice = user_service.get_user_by_username(session, "alice")
    bob = user_service.create_user(session, username="bob", password="test-pass")
    carol = user_service.create_user(session, username="carol", password="test-pass")

    for u, n in ((alice, 3), (bob, 2), (carol, 1)):
        for i in range(n):
            session.add(Workout(
                user_id=u.id,
                date=TODAY - timedelta(days=i),
                title=f"{u.username}-{i}",
                duration_s=1800 * (i + 1),
                calories=100 * (i + 1),
            ))
    session.commit()

    # carol 全部指标 opt-out
    row = Setting(
        user_id=carol.id,
        leaderboard_opt_out_json=json.dumps({
            "frequency": True, "volume": True, "calories": True, "streak": True,
        }),
    )
    session.add(row)
    session.commit()

    result = lb.precompute_leaderboards(session=session, now=TODAY)
    assert result["computed"] == 8
    assert result["failed"] == []

    caches = list(session.scalars(select(LeaderboardCache)))
    assert len(caches) == 8
    for c in caches:
        payload = json.loads(c.payload_json)
        assert isinstance(payload, list)
        ids = {e["user_id"] for e in payload}
        assert carol.id not in ids
        # alice/bob 至少应出现在 frequency 中
        if c.metric == "frequency":
            assert alice.id in ids
            assert bob.id in ids
