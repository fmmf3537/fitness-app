"""workout add tags column (garmin activity type as tag, PRD 5.2)

Revision ID: a1b2c3d4e5f6
Revises: 215ca0d68b0b
Create Date: 2026-08-04 11:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '215ca0d68b0b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('workout', sa.Column('tags', sa.String(length=200), nullable=True))


def downgrade() -> None:
    op.drop_column('workout', 'tags')
