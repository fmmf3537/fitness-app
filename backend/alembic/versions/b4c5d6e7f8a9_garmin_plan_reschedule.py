"""新增 Garmin 训练顺延检测与恢复字段。

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
Create Date: 2026-11-10
"""
from alembic import op
import sqlalchemy as sa


revision = "b4c5d6e7f8a9"
down_revision = "a3b4c5d6e7f8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("garmin_plan_sync") as batch_op:
        batch_op.add_column(sa.Column("content_hash", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("reschedule_to_date", sa.Date(), nullable=True))
        batch_op.add_column(
            sa.Column("previous_workout_schedule_id", sa.String(length=64), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("garmin_plan_sync") as batch_op:
        batch_op.drop_column("previous_workout_schedule_id")
        batch_op.drop_column("reschedule_to_date")
        batch_op.drop_column("content_hash")
