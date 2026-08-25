"""M4-1 sync_all_users 测试：多用户串行同步、失败隔离、绑定筛选、耗时告警。"""
import time
from datetime import date
from unittest.mock import Mock

import pytest
from sqlalchemy import select

from app.config import encrypt_value
from app.models import JobRun, Setting, User
from app.services import users as user_service
from app.services.sync import SYNC_ALL_USERS_ALERT_THRESHOLD_S, sync_all_users

DAY = date(2026, 8, 25)


def _ensure_user(session, username: str, *, is_active: bool = True) -> User:
    existing = user_service.get_user_by_username(session, username)
    if existing is not None:
        if existing.is_active != is_active:
            existing.is_active = is_active
            session.commit()
        return existing
    return user_service.create_user(
        session, username=username, password="test-pass", role="user", is_active=is_active
    )


def _bind_garmin(session, user_id: int) -> Setting:
    row = session.scalars(select(Setting).where(Setting.user_id == user_id)).first()
    if row is None:
        row = Setting(user_id=user_id)
        session.add(row)
        session.flush()
    row.garmin_email_enc = encrypt_value(f"u{user_id}@example.com")
    row.garmin_password_enc = encrypt_value("pw")
    session.commit()
    return row


def _ok_result(day=DAY):
    return {"date": day.isoformat(), "status": "success", "error": None, "detail": {}}


class TestSyncAllUsersEmpty:
    def test_no_users_returns_zero_attempted(self, session):
        # conftest 预建了 alice，但未绑定 → 应跳过
        result = sync_all_users(DAY, session=session, daily_sync_fn=Mock())
        assert result["users_attempted"] == 0
        assert result["users_succeeded"] == 0
        assert result["users_failed"] == 0
        assert result["date"] == "2026-08-25"
        assert isinstance(result["total_duration_s"], float)
        assert result["alert"] is None
        assert result["per_user"] == []


class TestSyncAllUsersSingle:
    def test_single_bound_user_success(self, session):
        alice = _ensure_user(session, "alice")
        _bind_garmin(session, alice.id)
        mock_sync = Mock(return_value=_ok_result())

        result = sync_all_users(DAY, session=session, daily_sync_fn=mock_sync)

        assert result["users_attempted"] == 1
        assert result["users_succeeded"] == 1
        assert result["users_failed"] == 0
        mock_sync.assert_called_once()
        kwargs = mock_sync.call_args.kwargs
        assert kwargs["user_id"] == alice.id
        assert mock_sync.call_args.args[0] == DAY


class TestSyncAllUsersSerial:
    def test_multi_user_serial_order_and_duration(self, session):
        alice = _ensure_user(session, "alice")
        bob = _ensure_user(session, "bob")
        charlie = _ensure_user(session, "charlie")
        for u in (alice, bob, charlie):
            _bind_garmin(session, u.id)

        call_order: list[int] = []

        def slow_sync(day, *, user_id=None, sleep=None):
            call_order.append(user_id)
            time.sleep(0.01)
            return _ok_result(day)

        t0 = time.monotonic()
        result = sync_all_users(DAY, session=session, daily_sync_fn=slow_sync)
        elapsed = time.monotonic() - t0

        assert result["users_attempted"] == 3
        assert result["users_succeeded"] == 3
        assert call_order == sorted(call_order)  # 按 id 升序串行
        assert set(call_order) == {alice.id, bob.id, charlie.id}
        assert elapsed >= 0.03
        assert result["total_duration_s"] >= 0.03


class TestSyncAllUsersFailureIsolation:
    def test_one_failure_continues_to_next(self, session):
        alice = _ensure_user(session, "alice")
        bob = _ensure_user(session, "bob")
        _bind_garmin(session, alice.id)
        _bind_garmin(session, bob.id)

        def flaky(day, *, user_id=None, sleep=None):
            if user_id == alice.id:
                raise RuntimeError("alice boom")
            return _ok_result(day)

        result = sync_all_users(DAY, session=session, daily_sync_fn=flaky)

        assert result["users_attempted"] == 2
        assert result["users_succeeded"] == 1
        assert result["users_failed"] == 1
        by_uid = {e["user_id"]: e for e in result["per_user"]}
        assert by_uid[alice.id]["status"] == "failed"
        assert "alice boom" in (by_uid[alice.id]["error"] or "")
        assert by_uid[bob.id]["status"] == "success"

        # 单用户失败写了 daily_sync job_run
        fails = session.scalars(
            select(JobRun).where(
                JobRun.job_name == "daily_sync",
                JobRun.user_id == alice.id,
                JobRun.status == "failed",
            )
        ).all()
        assert len(fails) >= 1


class TestSyncAllUsersFilters:
    def test_inactive_user_skipped(self, session):
        alice = _ensure_user(session, "alice", is_active=True)
        diana = _ensure_user(session, "diana", is_active=False)
        _bind_garmin(session, alice.id)
        _bind_garmin(session, diana.id)
        mock_sync = Mock(return_value=_ok_result())

        result = sync_all_users(DAY, session=session, daily_sync_fn=mock_sync)

        assert result["users_attempted"] == 1
        called_uids = [c.kwargs["user_id"] for c in mock_sync.call_args_list]
        assert called_uids == [alice.id]
        assert diana.id not in called_uids

    def test_unbound_user_skipped(self, session):
        alice = _ensure_user(session, "alice")
        eve = _ensure_user(session, "eve")
        _bind_garmin(session, alice.id)
        # eve：无 settings 行
        mock_sync = Mock(return_value=_ok_result())

        result = sync_all_users(DAY, session=session, daily_sync_fn=mock_sync)

        called_uids = [c.kwargs["user_id"] for c in mock_sync.call_args_list]
        assert alice.id in called_uids
        assert eve.id not in called_uids
        assert result["users_attempted"] == 1


class TestSyncAllUsersAlert:
    def test_alert_when_total_over_5_minutes(self, session):
        alice = _ensure_user(session, "alice")
        bob = _ensure_user(session, "bob")
        _bind_garmin(session, alice.id)
        _bind_garmin(session, bob.id)

        # 用可控时钟：开始 0，每用户 +70s，结束时总时长 > 300
        ticks = iter([0.0, 0.0, 70.0, 70.0, 140.0, 301.0])

        def fake_time():
            return next(ticks)

        alert_evaluator = Mock()
        mock_sync = Mock(return_value=_ok_result())

        result = sync_all_users(
            DAY,
            session=session,
            daily_sync_fn=mock_sync,
            time_fn=fake_time,
            alert_evaluator=alert_evaluator,
        )

        assert result["total_duration_s"] > SYNC_ALL_USERS_ALERT_THRESHOLD_S
        assert result["alert"] is not None
        assert "multi_user_sync_took_" in result["alert"]["message"]
        alert_evaluator.assert_called_once()
        assert alert_evaluator.call_args.args[1] is result["alert"]
