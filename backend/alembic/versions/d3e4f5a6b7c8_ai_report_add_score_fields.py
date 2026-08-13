"""ai_report 增加评分字段（V3-4 session_review 评分体系）

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-08-13
"""
from alembic import op
import sqlalchemy as sa

revision = "d3e4f5a6b7c8"
down_revision = "c2d3e4f5a6b7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("ai_report") as batch_op:
        batch_op.add_column(sa.Column("score", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("one_liner", sa.String(length=200), nullable=True))
        batch_op.add_column(sa.Column("subscores_json", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("ai_report") as batch_op:
        batch_op.drop_column("subscores_json")
        batch_op.drop_column("one_liner")
        batch_op.drop_column("score")
