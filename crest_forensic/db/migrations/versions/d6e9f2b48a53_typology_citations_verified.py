"""typology_matches.citations_verified

Revision ID: d6e9f2b48a53
Revises: c5d8e1a37f42
Create Date: 2026-10-14 20:30:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'd6e9f2b48a53'
down_revision: Union[str, Sequence[str], None] = 'c5d8e1a37f42'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('typology_matches') as batch:
        batch.add_column(sa.Column('citations_verified', sa.Boolean(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('typology_matches') as batch:
        batch.drop_column('citations_verified')
