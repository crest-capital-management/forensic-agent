"""auth_events: append-only log of sign-ins and account changes

Revision ID: f2b8d5a1c7e4
Revises: e4a7c2d19b63
Create Date: 2026-10-08 13:30:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'f2b8d5a1c7e4'
down_revision: Union[str, Sequence[str], None] = 'e4a7c2d19b63'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('auth_events',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('event', sa.String(length=30), nullable=False),
        sa.Column('username', sa.String(length=60), nullable=False),
        sa.Column('actor', sa.String(length=60), nullable=True),
        sa.Column('ip', sa.String(length=45), nullable=True),
        sa.Column('detail', sa.String(length=200), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sqlite_autoincrement=True)
    op.create_index(op.f('ix_auth_events_created_at'), 'auth_events', ['created_at'], unique=False)
    op.create_index(op.f('ix_auth_events_event'), 'auth_events', ['event'], unique=False)
    op.create_index(op.f('ix_auth_events_username'), 'auth_events', ['username'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_auth_events_username'), table_name='auth_events')
    op.drop_index(op.f('ix_auth_events_event'), table_name='auth_events')
    op.drop_index(op.f('ix_auth_events_created_at'), table_name='auth_events')
    op.drop_table('auth_events')
