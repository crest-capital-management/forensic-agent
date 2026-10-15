"""case events (close / reopen)

Revision ID: c9a2e41d7b18
Revises: b7c19d4e2a50
Create Date: 2026-10-07 19:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'c9a2e41d7b18'
down_revision: Union[str, Sequence[str], None] = 'b7c19d4e2a50'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('case_events',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('case_id', sa.Integer(), nullable=False),
        sa.Column('action', sa.String(length=10), nullable=False),
        sa.Column('by', sa.String(length=60), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ),
        sa.PrimaryKeyConstraint('id'))
    op.create_index(op.f('ix_case_events_case_id'), 'case_events', ['case_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_case_events_case_id'), table_name='case_events')
    op.drop_table('case_events')
