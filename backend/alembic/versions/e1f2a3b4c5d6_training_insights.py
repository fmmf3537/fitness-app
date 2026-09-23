"""训记协同：计划快照、建议状态、训练反馈和目标。

Revision ID: e1f2a3b4c5d6
Revises: d9e0f1a2b3c4
"""
from alembic import op
import sqlalchemy as sa

revision = "e1f2a3b4c5d6"
down_revision = "d9e0f1a2b3c4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("plan_snapshot",
        sa.Column("date", sa.Date(), primary_key=True),
        sa.Column("plan_json", sa.Text(), nullable=False),
        sa.Column("captured_at", sa.DateTime(), server_default=sa.func.now(), nullable=False))
    op.create_table("advice_action",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("report_id", sa.Integer(), sa.ForeignKey("ai_report.id", ondelete="CASCADE"), nullable=False),
        sa.Column("item_index", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("report_id", "item_index", name="uq_advice_action_item"))
    op.create_table("workout_feedback",
        sa.Column("workout_id", sa.Integer(), sa.ForeignKey("workout.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("fatigue", sa.Integer()), sa.Column("soreness", sa.Integer()),
        sa.Column("discomfort", sa.String(200)), sa.Column("note", sa.Text()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False))
    op.create_table("training_goal",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(30), nullable=False), sa.Column("target", sa.Float(), nullable=False),
        sa.Column("movement", sa.String(100)),
        sa.Column("active", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False))


def downgrade() -> None:
    op.drop_table("training_goal")
    op.drop_table("workout_feedback")
    op.drop_table("advice_action")
    op.drop_table("plan_snapshot")
