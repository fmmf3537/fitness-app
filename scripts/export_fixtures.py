"""M7：将真实数据匿名化导出为 tests/fixtures/ 回归夹具。

用法：
    python scripts/export_fixtures.py --days 7

每个有数据的日期生成一个目录：
    backend/tests/fixtures/real_week/<datestr>/
        xunji_trains.json      训记原始记录列表（note 清空，其余结构保留）
        garmin_activities.json 佳明原始记录列表（去除 owner/设备/GPS 等个人信息）
        expected.json          以当前库中 workout/match_candidate 为基准的期望匹配结果

匿名化规则：
    - 佳明 summary 去除 ownerId/ownerDisplayName/ownerFullName/ownerProfileImageUrl*/
      activityUUID/deviceId/userRoles；activityId 替换为顺序假 id（anon-g-N）；
      activityName 替换为「匿名活动」；
    - 佳明 details 去除 geoPolylineDTO（GPS 轨迹）；
    - 训记 note 字段清空，localid 保留（匹配引擎不读取 note）；
    - 时间戳/时长/心率/组次等训练数据原样保留，保证融合引擎行为可复现。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.db import make_engine, make_session_factory  # noqa: E402
from app.models import (  # noqa: E402
    GarminActivity,
    MatchCandidate,
    Workout,
    XunjiTrain,
)

FIXTURE_ROOT = Path(__file__).resolve().parent.parent / "backend" / "tests" / "fixtures" / "real_week"

GARMIN_SUMMARY_DROP_KEYS = {
    "ownerId", "ownerDisplayName", "ownerFullName",
    "ownerProfileImageUrlLarge", "ownerProfileImageUrlMedium",
    "ownerProfileImageUrlSmall", "activityUUID", "deviceId", "userRoles",
}


def _anonymize_garmin_raw(raw_json: str | None, fake_id: str) -> str | None:
    if not raw_json:
        return raw_json
    raw = json.loads(raw_json)
    summary = raw.get("summary")
    if isinstance(summary, dict):
        for k in GARMIN_SUMMARY_DROP_KEYS:
            summary.pop(k, None)
        summary["activityId"] = fake_id
        summary["activityName"] = "匿名活动"
    details = raw.get("details")
    if isinstance(details, dict):
        details.pop("geoPolylineDTO", None)  # GPS 轨迹
        if "activityId" in details:
            details["activityId"] = fake_id
    return json.dumps(raw, ensure_ascii=False, default=str)


def _anonymize_xunji_raw(raw_json: str | None) -> str | None:
    if not raw_json:
        return raw_json
    raw = json.loads(raw_json)
    if isinstance(raw, dict) and "note" in raw:
        raw["note"] = ""
    return json.dumps(raw, ensure_ascii=False, default=str)


def export_fixtures(session, days: int = 7, today: date | None = None) -> list[str]:
    today = today or date.today()
    since = today - timedelta(days=days - 1)
    exported: list[str] = []

    for i in range(days):
        day = since + timedelta(days=i)
        datestr = day.isoformat()
        trains = (
            session.query(XunjiTrain).filter(XunjiTrain.datestr == datestr)
            .order_by(XunjiTrain.localid).all()
        )
        activities = (
            session.query(GarminActivity)
            .filter(GarminActivity.start_ts >= day, GarminActivity.start_ts < day + timedelta(days=1))
            .order_by(GarminActivity.activity_id).all()
        )
        if not trains and not activities:
            continue

        # activity_id 匿名映射（同一活动稳定映射到同一假 id）
        fake_ids = {a.activity_id: f"anon-g-{n}" for n, a in enumerate(activities, 1)}

        day_dir = FIXTURE_ROOT / datestr
        day_dir.mkdir(parents=True, exist_ok=True)

        (day_dir / "xunji_trains.json").write_text(
            json.dumps(
                [
                    {
                        "datestr": t.datestr, "localid": t.localid, "title": t.title,
                        "start_ms": t.start_ms, "end_ms": t.end_ms, "note_json": t.note_json,
                        "raw_json": _anonymize_xunji_raw(t.raw_json),
                    }
                    for t in trains
                ],
                ensure_ascii=False, indent=2,
            ),
            encoding="utf-8",
        )
        (day_dir / "garmin_activities.json").write_text(
            json.dumps(
                [
                    {
                        "activity_id": fake_ids[a.activity_id],
                        "activity_type": a.activity_type, "name": "匿名活动",
                        "start_ts": a.start_ts.isoformat() if a.start_ts else None,
                        "end_ts": a.end_ts.isoformat() if a.end_ts else None,
                        "duration_s": a.duration_s, "calories": a.calories,
                        "avg_hr": a.avg_hr, "max_hr": a.max_hr,
                        "raw_json": _anonymize_garmin_raw(a.raw_json, fake_ids[a.activity_id]),
                    }
                    for a in activities
                ],
                ensure_ascii=False, indent=2,
            ),
            encoding="utf-8",
        )

        # 期望结果：以当前库（已经人工审计）为基准
        workouts = session.query(Workout).filter(Workout.date == day).order_by(Workout.id).all()
        localid_of = {t.id: t.localid for t in trains}
        fake_of_rowid = {a.id: fake_ids[a.activity_id] for a in activities}
        candidates = (
            session.query(MatchCandidate)
            .filter(MatchCandidate.status == "pending").all()
        )
        expected = {
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
                for c in candidates
                if localid_of.get(c.xunji_train_id) or fake_of_rowid.get(c.garmin_activity_id)
            ],
        }
        (day_dir / "expected.json").write_text(
            json.dumps(expected, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        exported.append(datestr)

    (FIXTURE_ROOT / "manifest.json").write_text(
        json.dumps({"days": exported}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return exported


def main() -> None:
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="导出匿名化回归夹具")
    parser.add_argument("--days", type=int, default=7)
    args = parser.parse_args()

    session = make_session_factory(make_engine())()
    try:
        exported = export_fixtures(session, days=args.days)
    finally:
        session.close()
    print(f"已导出 {len(exported)} 天夹具: {', '.join(exported)}")


if __name__ == "__main__":
    main()
