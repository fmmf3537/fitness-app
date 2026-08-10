"""V2-4 健康检查告警推送测试（PRD US / V2-4）。

规则：
- 同一数据源（garmin/xunji）在 health_check 中连续失败 ≥3 次 → 推送告警；
- 告警文案含失败接口、错误摘要、建议操作；
- 同故障 30 分钟冷却，不重复轰炸；冷却期后可再发；
- 通道：Server酱（SERVERCHAN_SENDKEY）/ SMTP 邮件，配置化，可双通道。
"""
import json
from datetime import datetime, timedelta
from unittest.mock import Mock

import pytest

from app.models import JobRun

T0 = datetime(2026, 8, 10, 12, 0, 0)


def _add_health_run(session, failed_sources, *, at=T0, error=None):
    """写一条 health_check 任务日志（failed_sources 为空表示成功）。"""
    run = JobRun(
        job_name="health_check",
        started_at=at,
        finished_at=at,
        status="failed" if failed_sources else "success",
        error=error,
        detail_json=json.dumps({"failed_sources": failed_sources}, ensure_ascii=False),
    )
    session.add(run)
    session.commit()
    return run


def _alert_runs(session):
    return session.query(JobRun).filter(JobRun.job_name == "alert").all()


# ---------- 阈值与计数 ----------


def test_no_alert_below_threshold(session):
    """连续 2 次失败不触发告警。"""
    from app.services.alerts import evaluate_health_alerts

    _add_health_run(session, ["garmin"], error="garmin: boom")
    _add_health_run(session, ["garmin"], at=T0 + timedelta(hours=1), error="garmin: boom")

    notifier = Mock()
    notifier.channels = ["serverchan"]
    out = evaluate_health_alerts(session, notifier=notifier, now=T0 + timedelta(hours=2))

    notifier.send.assert_not_called()
    assert out["alerts"] == []
    assert _alert_runs(session) == []


def test_alert_after_three_consecutive_failures(session):
    """佳明连续 3 次失败 → 发送告警，文案含接口名/错误摘要/建议操作。"""
    from app.services.alerts import evaluate_health_alerts

    for i in range(3):
        _add_health_run(session, ["garmin"], at=T0 + timedelta(hours=i),
                        error="garmin: 429 too many requests")

    notifier = Mock()
    notifier.channels = ["serverchan"]
    notifier.send.return_value = {"sent": ["serverchan"], "failed": {}}
    out = evaluate_health_alerts(session, notifier=notifier, now=T0 + timedelta(hours=3))

    notifier.send.assert_called_once()
    title, content = notifier.send.call_args.args
    assert "佳明" in title or "garmin" in title
    assert "garmin" in content
    assert "429" in content  # 错误摘要
    assert "FIT" in content  # 建议操作：手动导出 FIT 上传

    assert out["alerts"][0]["source"] == "garmin"
    assert out["alerts"][0]["status"] == "sent"
    runs = _alert_runs(session)
    assert len(runs) == 1
    assert runs[0].status == "sent"
    assert json.loads(runs[0].detail_json)["source"] == "garmin"


def test_success_resets_consecutive_count(session):
    """中间穿插一次成功 → 连续计数清零，不告警。"""
    from app.services.alerts import evaluate_health_alerts

    _add_health_run(session, ["xunji"], error="xunji: timeout")
    _add_health_run(session, ["xunji"], at=T0 + timedelta(hours=1), error="xunji: timeout")
    _add_health_run(session, [], at=T0 + timedelta(hours=2))  # 成功
    _add_health_run(session, ["xunji"], at=T0 + timedelta(hours=3), error="xunji: timeout")
    _add_health_run(session, ["xunji"], at=T0 + timedelta(hours=4), error="xunji: timeout")

    notifier = Mock()
    notifier.channels = ["serverchan"]
    evaluate_health_alerts(session, notifier=notifier, now=T0 + timedelta(hours=5))
    notifier.send.assert_not_called()


def test_sources_evaluated_independently(session):
    """训记 3 连败 + 佳明仅 2 连败 → 只告警训记。"""
    from app.services.alerts import evaluate_health_alerts

    for i in range(3):
        _add_health_run(session, ["xunji", "garmin"] if i < 2 else ["xunji"],
                        at=T0 + timedelta(hours=i), error="xunji: down; garmin: down")

    notifier = Mock()
    notifier.channels = ["serverchan"]
    notifier.send.return_value = {"sent": ["serverchan"], "failed": {}}
    evaluate_health_alerts(session, notifier=notifier, now=T0 + timedelta(hours=3))

    notifier.send.assert_called_once()
    title, _ = notifier.send.call_args.args
    assert "训记" in title or "xunji" in title


# ---------- 30 分钟冷却去重 ----------


def test_cooldown_suppresses_repeat_alert(session):
    """同故障 30 分钟内不重复推送；超过冷却期可再发。"""
    from app.services.alerts import evaluate_health_alerts

    notifier = Mock()
    notifier.channels = ["serverchan"]
    notifier.send.return_value = {"sent": ["serverchan"], "failed": {}}

    for i in range(3):
        _add_health_run(session, ["garmin"], at=T0 + timedelta(hours=i), error="garmin: boom")
    evaluate_health_alerts(session, notifier=notifier, now=T0 + timedelta(hours=3))
    assert notifier.send.call_count == 1

    # 25 分钟后（冷却内）第 4 次失败 → 不再发
    _add_health_run(session, ["garmin"], at=T0 + timedelta(hours=3, minutes=25),
                    error="garmin: boom")
    evaluate_health_alerts(session, notifier=notifier, now=T0 + timedelta(hours=3, minutes=25))
    assert notifier.send.call_count == 1

    # 31 分钟后（冷却过期）再失败 → 再发一次
    _add_health_run(session, ["garmin"], at=T0 + timedelta(hours=3, minutes=31),
                    error="garmin: boom")
    evaluate_health_alerts(session, notifier=notifier, now=T0 + timedelta(hours=3, minutes=31))
    assert notifier.send.call_count == 2


# ---------- Notifier 通道 ----------


def test_notifier_dual_channel(session):
    """Server酱 + SMTP 均配置时双通道发送。"""
    from app.services.alerts import AlertNotifier

    post_fn = Mock()
    smtp_fn = Mock()
    notifier = AlertNotifier(
        serverchan_sendkey="SCT123",
        smtp_host="smtp.example.com", smtp_port=465,
        smtp_user="u@example.com", smtp_pass="pw", alert_email="me@example.com",
        post_fn=post_fn, smtp_fn=smtp_fn,
    )
    assert notifier.channels == ["serverchan", "smtp"]

    result = notifier.send("标题", "内容")
    assert result["sent"] == ["serverchan", "smtp"]
    post_fn.assert_called_once()
    assert "SCT123" in post_fn.call_args.args[0]
    assert post_fn.call_args.kwargs["data"]["title"] == "标题"
    assert post_fn.call_args.kwargs["data"]["desp"] == "内容"
    smtp_fn.assert_called_once()


def test_notifier_no_channel_returns_empty(session):
    from app.services.alerts import AlertNotifier

    notifier = AlertNotifier()
    assert notifier.channels == []
    assert notifier.send("t", "c") == {"sent": [], "failed": {}}


def test_notifier_channel_failure_recorded(session):
    """通道异常不向外抛，记入 failed。"""
    from app.services.alerts import AlertNotifier

    post_fn = Mock(side_effect=RuntimeError("network down"))
    notifier = AlertNotifier(serverchan_sendkey="SCT123", post_fn=post_fn)
    result = notifier.send("t", "c")
    assert result["sent"] == []
    assert "serverchan" in result["failed"]


def test_alert_status_skipped_when_no_channel(session):
    """未配置任何通道：告警记入日志 status=skipped，不发送。"""
    from app.services.alerts import AlertNotifier, evaluate_health_alerts

    for i in range(3):
        _add_health_run(session, ["garmin"], at=T0 + timedelta(hours=i), error="garmin: boom")

    out = evaluate_health_alerts(session, notifier=AlertNotifier(), now=T0 + timedelta(hours=3))
    assert out["alerts"][0]["status"] == "skipped"
    assert _alert_runs(session)[0].status == "skipped"


def test_alert_status_failed_when_all_channels_fail(session):
    from app.services.alerts import AlertNotifier, evaluate_health_alerts

    for i in range(3):
        _add_health_run(session, ["garmin"], at=T0 + timedelta(hours=i), error="garmin: boom")

    notifier = AlertNotifier(serverchan_sendkey="K", post_fn=Mock(side_effect=OSError("x")))
    out = evaluate_health_alerts(session, notifier=notifier, now=T0 + timedelta(hours=3))
    assert out["alerts"][0]["status"] == "failed"
    assert _alert_runs(session)[0].status == "failed"


# ---------- health_check 集成 ----------


def test_health_check_triggers_alert_evaluation(session):
    """health_check 写日志后调用告警评估（可注入替换）。"""
    from app.services.sync import health_check

    xunji = Mock()
    xunji.fetch_trains.side_effect = RuntimeError("xunji down")
    garmin = Mock()
    garmin.sync_daily.side_effect = RuntimeError("garmin down")
    evaluator = Mock(return_value={"alerts": []})

    health_check(session=session, xunji=xunji, garmin=garmin, alert_evaluator=evaluator)
    evaluator.assert_called_once()


def test_health_check_end_to_end_alert(session):
    """端到端：已有 2 连败，本次健康检查佳明再失败 → 推送告警。"""
    from app.services.sync import health_check

    _add_health_run(session, ["garmin"], error="garmin: boom")
    _add_health_run(session, ["garmin"], error="garmin: boom")

    xunji = Mock()  # 训记正常
    garmin = Mock()
    garmin.sync_daily.side_effect = RuntimeError("garmin down")
    notifier = Mock()
    notifier.channels = ["serverchan"]
    notifier.send.return_value = {"sent": ["serverchan"], "failed": {}}

    health_check(session=session, xunji=xunji, garmin=garmin, alert_notifier=notifier)
    notifier.send.assert_called_once()
