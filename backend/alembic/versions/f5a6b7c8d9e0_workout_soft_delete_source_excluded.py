"""workout 软删除 deleted_at + 源表 excluded 墓碑（V3-11 手动删除训练）

Revision ID: f5a6b7c8d9e0
Revises: e4f5a6b7c8d9
Create Date: 2026-08-19
"""
from alembic import op
import sqlalchemy as sa

revision = "f5a6b7c8d9e0"
down_revision = "e4f5a6b7c8d9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("workout") as batch_op:
        batch_op.add_column(sa.Column("deleted_at", sa.DateTime(), nullable=True))
    with op.batch_alter_table("garmin_activity") as batch_op:
        batch_op.add_column(
            sa.Column("excluded", sa.Boolean(), nullable=False, server_default="0")
        )
    with op.batch_alter_table("xunji_train") as batch_op:
        batch_op.add_column(
            sa.Column("excluded", sa.Boolean(), nullable=False, server_default="0")
        )


def downgrade() -> None:
    with op.batch_alter_table("xunji_train") as batch_op:
        batch_op.drop_column("excluded")
    with op.batch_alter_table("garmin_activity") as batch_op:
        batch_op.drop_column("excluded")
    with op.batch_alter_table("workout") as batch_op:
        batch_op.drop_column("deleted_at")
