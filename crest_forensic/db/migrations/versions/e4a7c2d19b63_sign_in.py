"""sign-in: password hashes and cookie sessions

Revision ID: e4a7c2d19b63
Revises: d1f6b0a83c52
Create Date: 2026-10-07 22:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'e4a7c2d19b63'
down_revision: Union[str, Sequence[str], None] = 'd1f6b0a83c52'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('app_users') as batch:
        batch.add_column(sa.Column('password_hash', sa.String(length=300), nullable=True))
        batch.add_column(sa.Column('password_set_at', sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column('active', sa.Boolean(), nullable=False, server_default='1'))
    op.create_table('auth_sessions',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('username', sa.String(length=60), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('revoked', sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint('id'))
    op.create_index(op.f('ix_auth_sessions_token_hash'), 'auth_sessions', ['token_hash'], unique=True)
    op.create_index(op.f('ix_auth_sessions_username'), 'auth_sessions', ['username'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_auth_sessions_username'), table_name='auth_sessions')
    op.drop_index(op.f('ix_auth_sessions_token_hash'), table_name='auth_sessions')
    op.drop_table('auth_sessions')
    with op.batch_alter_table('app_users') as batch:
        batch.drop_column('active')
        batch.drop_column('password_set_at')
        batch.drop_column('password_hash')
