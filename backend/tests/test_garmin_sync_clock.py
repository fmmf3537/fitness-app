"""Garmin 同步时间戳时钟一致性回归测试。

背景（2026-11-12 生产事故）：`GarminPlanSync.created_at` 走 `server_default=func.now()`、
`updated_at` 走 `onupdate=func.now()`，两者都由**数据库会话时区**（生产为 UTC）生成；
而同表的显式写入用 `datetime.now()`（容器 TZ=Asia/Shanghai）。同一行里混存 UTC 与本地，
`recover_stale_syncing` 做差时相差正好 8 小时，**刚创建的 syncing 记录会被立刻误判超时**，
把已经成功写到远端的同步标成 failed，UI 显示「Garmin 同步失败」。

修复：这两个列改为 Python 侧本地 naive（`default/onupdate=lambda: local_now()`），
与 `datetime.now()` 同口径；并在恢复判断里对「观测值比现在还新」做防御。
"""
from datetime import date, datetime, timedelta

import pytest

from app import models as models_mod
from app.models import GarminPlanSync
from app.services import garmin_plan_sync as sync_service


def _make_syncing(session, *, attempt: int = 1) -> GarminPlanSync:
    record = GarminPlanSync(
        plan_ref="test:1",
        training_date=date(2026, 11, 12),
        source_key="test:1:2026-11-12",
        source_hash="a" * 64,
        status="syncing",
        phase="create",
        attempt_count=attempt,
    )
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


class TestLocalClockColumns:
    def test_created_at_uses_local_now_not_db_default(self, session, monkeypatch):
        """created_at 必须由 Python 侧本地时间生成，不能落到 server_default 的 UTC。"""
        fixed = datetime(2026, 11, 12, 15, 18, 24, 500000)
        monkeypatch.setattr(models_mod, "local_now", lambda: fixed)

        record = _make_syncing(session)
        assert record.created_at == fixed

    def test_updated_at_uses_local_now_on_insert(self, session, monkeypatch):
        fixed = datetime(2026, 11, 12, 15, 18, 24, 500000)
        monkeypatch.setattr(models_mod, "local_now", lambda: fixed)

        record = _make_syncing(session)
        assert record.updated_at == fixed

    def test_onupdate_keeps_local_time(self, session, monkeypatch):
        """只改 phase（不显式设 updated_at）时，onupdate 也必须写本地时间。

        这条是本次事故的直接回归点：修复前 onupdate=func.now() 会写成 DB 会话 UTC，
        导致 updated_at 比 datetime.now() 晚 8 小时。
        """
        base = datetime(2026, 11, 12, 15, 18, 24, 500000)
        monkeypatch.setattr(models_mod, "local_now", lambda: base)
        record = _make_syncing(session)

        later = base + timedelta(seconds=3)
        monkeypatch.setattr(models_mod, "local_now", lambda: later)
        record.phase = "schedule"
        session.commit()
        session.refresh(record)

        assert record.updated_at == later
        # 与"现在"的差必须接近 0，绝不会是 8 小时
        assert abs((later - record.updated_at).total_seconds()) < 1


class TestRecoverStaleSyncing:
    def test_fresh_syncing_is_not_recovered(self, session, monkeypatch):
        """刚抢占的记录（几秒前更新）绝不能被判超时。"""
        now = datetime(2026, 11, 12, 15, 18, 30)
        record = _make_syncing(session)
        record.updated_at = now - timedelta(seconds=3)
        session.commit()

        changed = sync_service.recover_stale_syncing(session, record, now=now)
        assert changed is False
        session.refresh(record)
        assert record.status == "syncing"

    def test_genuinely_stale_syncing_is_recovered(self, session, monkeypatch):
        """真正超时（超过阈值）的记录仍应被判失败。"""
        now = datetime(2026, 11, 12, 15, 30, 0)
        record = _make_syncing(session)
        record.updated_at = now - timedelta(seconds=1200)
        session.commit()

        changed = sync_service.recover_stale_syncing(
            session, record, now=now, stale_after_seconds=900
        )
        assert changed is True
        session.refresh(record)
        assert record.status == "failed"
        assert record.error_code == sync_service.STALE_SYNC_ERROR_CODE

    def test_future_timestamp_is_treated_as_active(self, session):
        """观测值比"现在"还新（时钟错位的历史行）应视为活跃，不判超时。"""
        now = datetime(2026, 11, 12, 15, 0, 0)
        record = _make_syncing(session)
        # 模拟历史行：updated_at 是 DB UTC，比本地"现在"还晚
        record.updated_at = now + timedelta(hours=8)
        session.commit()

        changed = sync_service.recover_stale_syncing(session, record, now=now)
        assert changed is False
        session.refresh(record)
        assert record.status == "syncing"
