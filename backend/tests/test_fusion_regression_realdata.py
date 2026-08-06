"""M7 真实数据回归测试：以匿名化真机夹具（tests/fixtures/real_week/）为基准。

夹具由 scripts/export_fixtures.py 从真实库导出并匿名化，
expected.json 记录了经人工审计的匹配结果，作为融合引擎的长期回归基准。
"""
import json
from datetime import date, datetime
from pathlib import Path

import pytest

from app.models import GarminActivity, MatchCandidate, Workout, XunjiTrain
from app.services.matcher import match_day

FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "real_week"


def _load_days() -> list[str]:
    manifest = json.loads((FIXTURE_ROOT / "manifest.json").read_text(encoding="utf-8"))
    return manifest["days"]


def _insert_day(session, day_dir: Path) -> dict:
    """把一天的夹具记录写入临时库，返回 {fake_activity_id: row_id} 等映射。"""
    trains = json.loads((day_dir / "xunji_trains.json").read_text(encoding="utf-8"))
    activities = json.loads((day_dir / "garmin_activities.json").read_text(encoding="utf-8"))
    for t in trains:
        session.add(XunjiTrain(
            datestr=t["datestr"], localid=t["localid"], title=t["title"],
            start_ms=t["start_ms"], end_ms=t["end_ms"], note_json=t["note_json"],
            raw_json=t["raw_json"],
        ))
    id_map = {}
    for a in activities:
        row = GarminActivity(
            activity_id=a["activity_id"], activity_type=a["activity_type"], name=a["name"],
            start_ts=datetime.fromisoformat(a["start_ts"]) if a["start_ts"] else None,
            end_ts=datetime.fromisoformat(a["end_ts"]) if a["end_ts"] else None,
            duration_s=a["duration_s"], calories=a["calories"],
            avg_hr=a["avg_hr"], max_hr=a["max_hr"], raw_json=a["raw_json"],
        )
        session.add(row)
        session.flush()
        id_map[a["activity_id"]] = row.id
    session.commit()
    return id_map


def _actual_result(session, day: date) -> dict:
    """运行匹配引擎并收集与 expected.json 同构的实际结果。"""
    match_day(session, day)
    workouts = session.query(Workout).filter(Workout.date == day).order_by(Workout.id).all()
    localid_of = {
        t.id: t.localid
        for t in session.query(XunjiTrain).filter(XunjiTrain.datestr == day.isoformat())
    }
    fake_of_rowid = {v: k for k, v in
                     ((a.activity_id, a.id) for a in session.query(GarminActivity).all())}
    return {
        "workouts": [
            {
                "xunji_localid": localid_of.get(w.xunji_train_id),
                "garmin_activity_id": fake_of_rowid.get(w.garmin_activity_id),
                "match_status": w.match_status,
            }
            for w in workouts
        ],
        "candidates": [
            {
                "xunji_localid": localid_of.get(c.xunji_train_id),
                "garmin_activity_id": fake_of_rowid.get(c.garmin_activity_id),
                "reason": c.reason,
            }
            for c in session.query(MatchCandidate)
            .filter(MatchCandidate.status == "pending").all()
        ],
    }


@pytest.mark.parametrize("datestr", _load_days())
def test_real_week_matching_regression(session, datestr):
    """真实一周数据：匹配引擎输出必须与人工审计基准一致。"""
    day_dir = FIXTURE_ROOT / datestr
    _insert_day(session, day_dir)
    expected = json.loads((day_dir / "expected.json").read_text(encoding="utf-8"))

    actual = _actual_result(session, date.fromisoformat(datestr))

    # workout 顺序无关比较（多训练日 id 顺序可能受插入序影响）
    sort_key = lambda w: (w["xunji_localid"] or "", w["garmin_activity_id"] or "")
    assert sorted(actual["workouts"], key=sort_key) == sorted(expected["workouts"], key=sort_key)
    assert sorted(actual["candidates"], key=sort_key) == sorted(expected["candidates"], key=sort_key)


def test_real_2026_08_03_heart_rate_series_over_100_points(session):
    """心率修复回归：真实 2026-08-03 力量活动心率序列必须 > 100 点。"""
    from app.api.workouts import extract_heart_rate_series

    activities = json.loads(
        (FIXTURE_ROOT / "2026-08-03" / "garmin_activities.json").read_text(encoding="utf-8")
    )
    strength = next(a for a in activities if a["activity_type"] == "strength_training")
    series = extract_heart_rate_series(strength["raw_json"])
    assert len(series) > 100
    assert all(0 < p["hr"] < 250 for p in series)


def test_fixtures_anonymized():
    """夹具不得残留个人信息字段（防回归泄漏）。"""
    banned = ["ownerDisplayName", "ownerFullName", "ownerId", "ProfileImage",
              "activityUUID", "deviceId", "geoPolylineDTO"]
    for f in FIXTURE_ROOT.rglob("*.json"):
        text = f.read_text(encoding="utf-8")
        for key in banned:
            assert key not in text, f"{f.name} 残留个人信息字段 {key}"
