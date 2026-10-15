"""cases.name: an optional free-text name for a case

Revision ID: b3f9d2a65e18
Revises: a8e3c1f7d204
Create Date: 2026-10-09 18:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'b3f9d2a65e18'
down_revision: Union[str, Sequence[str], None] = 'a8e3c1f7d204'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('cases') as batch:
        batch.add_column(sa.Column('name', sa.String(length=120), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('cases') as batch:
        batch.drop_column('name')
