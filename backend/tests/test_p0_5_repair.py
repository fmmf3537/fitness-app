"""2026-11-13 生产事故回归：`verified_level='none'` 不等于「目标无效」。

事故经过：ADR-P0-5 的存量迁移把「目标未验证」当成「目标无效」，
把线上 292 条合法映射踢出了 active（active 308 → 16）。

两个根因：
① `generate_all` 把目录生成的映射写成 `verified_level="none"`，
   但 `none` 的语义是「连目录都没查过」，这些组合本来就取自目录 → 至少是 `catalog`；
② 迁移的退出判据用了 `verified_level in _TARGET_VALID_LEVELS`，
   把「未验证」与「目录里不存在」混为一谈。

本文件锁住三件事：
- 迁移只按「目录里是否存在该组合」判断目标无效；
- `repair_verified_levels` 只把目录里确实存在的组合提升为 `catalog`；
- `restore_migration_exits` 依据审计精确恢复被误退出的行，且幂等。
"""

from __future__ import annotations

from sqlalchemy import select

from app.models import ExerciseMapping, ExerciseMappingAudit
from app.services.exercise_mapping import seed_mappings
from app.services.exercise_mapping_relation import (
    migrate_existing_active,
    repair_verified_levels,
    restore_migration_exits,
)


def _mk(session, name, *, exercise="DUMBBELL_BENCH_PRESS", verified="none",
        status="draft", relation="EXACT", version=2):
    row = ExerciseMapping(
        xunji_name=name,
        garmin_category="BENCH_PRESS",
        garmin_exercise_name=exercise,
        garmin_display_name="Dumbbell Bench Press",
        status=status,
        source="auto",
        relation=relation,
        confidence="high",
        verified_level=verified,
        mapping_version=version,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


class TestRepairVerifiedLevels:
    def test_valid_pair_upgraded_to_catalog(self, session):
        row = _mk(session, "修复-合法", verified="none")
        result = repair_verified_levels(session)
        session.refresh(row)
        assert row.verified_level == "catalog"
        assert result["repaired"] >= 1

    def test_invalid_pair_keeps_none(self, session):
        row = _mk(session, "修复-真无效", exercise="NOT_A_REAL_EXERCISE", verified="none")
        repair_verified_levels(session)
        session.refresh(row)
        assert row.verified_level == "none", "目录里不存在的组合不能升级为 catalog"

    def test_idempotent(self, session):
        _mk(session, "修复-幂等", verified="none")
        repair_verified_levels(session)
        second = repair_verified_levels(session)
        assert second["repaired"] == 0


class TestRestoreMigrationExits:
    def _exit_via_audit(self, session, row):
        session.add(
            ExerciseMappingAudit(
                mapping_id=row.id,
                xunji_name=row.xunji_name,
                action="migrate_exit_active",
                before_json='{"status": "active"}',
                after_json='{"status": "draft"}',
                reason="target_unverified",
                actor="user",
            )
        )
        session.commit()

    def test_restores_valid_target(self, session):
        row = _mk(session, "恢复-合法", verified="none", status="draft")
        self._exit_via_audit(session, row)
        result = restore_migration_exits(session)
        session.refresh(row)
        assert row.status == "active"
        assert result["restored"] >= 1

    def test_does_not_restore_invalid_target(self, session):
        row = _mk(session, "恢复-真无效", exercise="NOT_A_REAL_EXERCISE", status="draft")
        self._exit_via_audit(session, row)
        restore_migration_exits(session)
        session.refresh(row)
        assert row.status == "draft", "目录里不存在的组合不得恢复为 active"

    def test_writes_restore_audit(self, session):
        row = _mk(session, "恢复-审计", verified="none", status="draft")
        self._exit_via_audit(session, row)
        restore_migration_exits(session)
        actions = {
            a.action
            for a in session.scalars(
                select(ExerciseMappingAudit).where(
                    ExerciseMappingAudit.mapping_id == row.id
                )
            ).all()
        }
        assert "migrate_restore" in actions

    def test_idempotent(self, session):
        row = _mk(session, "恢复-幂等", verified="none", status="draft")
        self._exit_via_audit(session, row)
        restore_migration_exits(session)
        second = restore_migration_exits(session)
        assert second["restored"] == 0


class TestMigrationNoLongerUsesVerifiedLevel:
    def test_unverified_but_valid_stays_active(self, session):
        """核心回归：未验证但目标合法 → 迁移不得踢出 active。"""
        row = _mk(session, "迁移-未验证合法", verified="none", status="active")
        report = migrate_existing_active(session)
        session.refresh(row)
        assert row.status == "active"
        assert report["exited_active"] == 0

    def test_invalid_target_still_exits(self, session):
        row = _mk(
            session,
            "迁移-真无效",
            exercise="NOT_A_REAL_EXERCISE",
            verified="catalog",
            status="active",
        )
        report = migrate_existing_active(session)
        session.refresh(row)
        assert row.status == "draft"
        assert report["exited_active"] >= 1
        assert report["exited_details"][0]["reason"] == "catalog_missing"
