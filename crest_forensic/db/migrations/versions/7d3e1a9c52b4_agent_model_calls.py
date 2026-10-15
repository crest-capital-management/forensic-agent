"""agent model calls

Revision ID: 7d3e1a9c52b4
Revises: 61ca55fb9280
Create Date: 2026-10-06 12:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '7d3e1a9c52b4'
down_revision: Union[str, Sequence[str], None] = '61ca55fb9280'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('agent_messages') as batch:
        batch.add_column(sa.Column('model_calls', sa.Integer(), nullable=False, server_default='0'))


def downgrade() -> None:
    with op.batch_alter_table('agent_messages') as batch:
        batch.drop_column('model_calls')
