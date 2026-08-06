"""M7 匹配准确率审计脚本（scripts/match_audit.py）单元测试。"""
import sys
from datetime import date, datetime
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT_DIR))

from scripts.match_audit import compute_accuracy, collect_audit, render_report  # noqa: E402
from tests.conftest import make_garmin_activity, make_xunji_train  # noqa: E402

TODAY = date(2026, 8, 6)


def _fused(session, day, status, localid="1", activity_id="g1"):
    from app.services.fuse import fuse_workout

    train = activity = None
    if status != "garmin_only":
        train = make_xunji_train(session, day, localid=localid)
    if status != "xunji_only":
        activity = make_garmin_activity(session, day, activity_id=activity_id)
    return fuse_workout(
        session, day, xunji=train, garmin=activity, match_status=status
    )


# ---------- compute_accuracy 纯函数 ----------

@pytest.mark.parametrize(
    "auto_matched, auto_corrected, expected",
    [
        (10, 0, 1.0),
        (9, 1, 0.9),
        (8, 2, 0.8),
        (0, 0, None),
    ],
)
def test_compute_accuracy(auto_matched, auto_corrected, expected):
    assert compute_accuracy(auto_matched, auto_corrected) == pytest.approx(expected) \
        if expected is not None else compute_accuracy(auto_matched, auto_corrected) is None


# ---------- collect_audit 汇总逻辑 ----------

def test_collect_audit_status_distribution_and_accuracy(session):
    day = date(2026, 8, 4)
    _fused(session, day, "auto_matched", localid="1", activity_id="g1")
    _fused(session, date(2026, 8, 5), "auto_matched", localid="1", activity_id="g2")
    _fused(session, date(2026, 8, 5), "xunji_only", localid="2")
    _fused(session, date(2026, 8, 6), "garmin_only", activity_id="g3")
    # 窗口外（10 天前）的记录不应计入
    _fused(session, date(2026, 7, 20), "auto_matched", localid="1", activity_id="g9")

    result = collect_audit(session, days=7, today=TODAY)
    assert result["window"] == {"since": "2026-07-31", "until": "2026-08-06", "days": 7}
    assert result["workout_total"] == 4
    assert result["status_dist"] == {
        "auto_matched": 2, "xunji_only": 1, "garmin_only": 1
    }
    assert result["auto_matched"] == 2
    assert result["auto_corrected"] == 0
    assert result["accuracy"] == 1.0
    assert result["corrections"] == []


def test_collect_audit_lists_manual_corrections(session):
    from app.models import MatchCandidate

    day = date(2026, 8, 4)
    train = make_xunji_train(session, day, localid="1", title="胸训")
    activity = make_garmin_activity(session, day, activity_id="g1", name="力量")
    c = MatchCandidate(
        xunji_train_id=train.id, garmin_activity_id=activity.id,
        reason="time_close", status="merged", resolved_at=datetime(2026, 8, 4, 22, 0),
    )
    pending = MatchCandidate(
        xunji_train_id=train.id, garmin_activity_id=activity.id,
        reason="time_close", status="pending",
    )
    session.add_all([c, pending])
    session.commit()

    result = collect_audit(session, days=7, today=TODAY)
    assert len(result["corrections"]) == 1
    corr = result["corrections"][0]
    assert corr["status"] == "merged" and corr["reason"] == "time_close"
    assert corr["xunji"] == {"datestr": "2026-08-04", "title": "胸训"}
    assert corr["garmin"]["activity_id"] == "g1"
    assert corr["undid_auto_match"] is False  # merged 的是待确认候选，非自动匹配
    assert result["pending_candidates"] == 1


def test_collect_audit_detects_corrected_auto_match(session):
    """人工 split 掉一对仍为 auto_matched 的组合 → 计入被纠正，准确率下降。"""
    from app.models import MatchCandidate

    day = date(2026, 8, 4)
    w = _fused(session, day, "auto_matched", localid="1", activity_id="g1")
    c = MatchCandidate(
        xunji_train_id=w.xunji_train_id, garmin_activity_id=w.garmin_activity_id,
        reason="time_close", status="split", resolved_at=datetime(2026, 8, 4, 23, 0),
    )
    session.add(c)
    session.commit()

    result = collect_audit(session, days=7, today=TODAY)
    assert result["auto_corrected"] == 1
    # 1 条自动匹配 + 1 条被纠正 = 总数 2，未被纠正 1 → 50%
    assert result["accuracy"] == 0.5


# ---------- render_report 报告渲染 ----------

def test_render_report_pass_and_fail(tmp_path=None):
    base = {
        "window": {"since": "2026-07-31", "until": "2026-08-06", "days": 7},
        "workout_total": 10,
        "status_dist": {"auto_matched": 9, "xunji_only": 1},
        "corrections": [],
        "pending_candidates": 0,
        "auto_matched": 9,
        "auto_corrected": 0,
        "accuracy": 1.0,
    }
    report = render_report(base)
    assert "100.0%" in report and "达标" in report

    bad = dict(base, auto_matched=7, auto_corrected=2, accuracy=7 / 9)
    report = render_report(bad)
    assert "77.8%" in report and "未达标" in report

    empty = dict(base, workout_total=0, status_dist={}, auto_matched=0, accuracy=None)
    report = render_report(empty)
    assert "样本不足" in report and "无法判定" in report
