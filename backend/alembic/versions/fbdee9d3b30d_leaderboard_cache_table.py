"""M5-1: leaderboard_cache 表

Revision ID: fbdee9d3b30d
Revises: 55163cf925d2
Create Date: 2026-08-26 00:08:24.628159

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "fbdee9d3b30d"
down_revision: Union[str, None] = "55163cf925d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "leaderboard_cache",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("metric", sa.String(length=20), nullable=False),
        sa.Column("window", sa.String(length=10), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("computed_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("metric", "window", name="uq_leaderboard_cache_metric_window"),
    )


def downgrade() -> None:
    op.drop_table("leaderboard_cache")
