"""保存 Garmin 顺延原日期和原来源键，支持成功后幂等恢复。

Revision ID: c5d6e7f8a9b0
Revises: b4c5d6e7f8a9
Create Date: 2026-11-10
"""
from alembic import op
import sqlalchemy as sa


revision = "c5d6e7f8a9b0"
down_revision = "b4c5d6e7f8a9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("garmin_plan_sync") as batch_op:
        batch_op.add_column(sa.Column("reschedule_from_date", sa.Date(), nullable=True))
        batch_op.add_column(
            sa.Column("reschedule_source_key", sa.String(length=255), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("garmin_plan_sync") as batch_op:
        batch_op.drop_column("reschedule_source_key")
        batch_op.drop_column("reschedule_from_date")
