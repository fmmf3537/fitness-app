"""新增训记计划到 Garmin 的同步状态表。

Revision ID: a3b4c5d6e7f8
Revises: f2a3b4c5d6e7
Create Date: 2026-11-10
"""
from alembic import op
import sqlalchemy as sa


revision = "a3b4c5d6e7f8"
down_revision = "f2a3b4c5d6e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "garmin_plan_sync",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("plan_ref", sa.String(length=100), nullable=False),
        sa.Column("training_date", sa.Date(), nullable=False),
        sa.Column("source_key", sa.String(length=255), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("synced_hash", sa.String(length=64), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=True),
        sa.Column("workout_id", sa.String(length=64), nullable=True),
        sa.Column("workout_schedule_id", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("phase", sa.String(length=32), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("synced_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_key", name="uq_garmin_plan_sync_source_key"),
        sa.UniqueConstraint(
            "plan_ref", "training_date", name="uq_garmin_plan_sync_plan_date"
        ),
    )


def downgrade() -> None:
    op.drop_table("garmin_plan_sync")
