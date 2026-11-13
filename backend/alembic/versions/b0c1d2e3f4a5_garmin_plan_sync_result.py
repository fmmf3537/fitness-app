"""ADR-P0-3b：garmin_plan_sync 增加 sync_result_json

记录 partial 同步的 written / skipped / excluded 三类结果（ADR §7.2）。
不得复用 payload_json（R1）：后者是期望 Workout payload，被回读比对与
stale 判定消费。

Revision ID: b0c1d2e3f4a5
Revises: a9b0c1d2e3f4
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b0c1d2e3f4a5"
down_revision = "a9b0c1d2e3f4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "garmin_plan_sync",
        sa.Column("sync_result_json", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("garmin_plan_sync", "sync_result_json")
