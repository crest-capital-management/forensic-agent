"""memos and memo_versions (Job 4 research assessment memo)

Revision ID: a8e3c1f7d204
Revises: f2b8d5a1c7e4
Create Date: 2026-10-08 18:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'a8e3c1f7d204'
down_revision: Union[str, Sequence[str], None] = 'f2b8d5a1c7e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('memos',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('case_id', sa.Integer(), nullable=False),
        sa.Column('reference', sa.String(length=80), nullable=False),
        sa.Column('owner', sa.String(length=60), nullable=False),
        sa.Column('scope_note', sa.Text(), nullable=False),
        sa.Column('created_by', sa.String(length=60), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('signed_version_id', sa.Integer(), nullable=True),
        sa.Column('signed_by', sa.String(length=60), nullable=True),
        sa.Column('signed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['case_id'], ['cases.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('reference'),
        sqlite_autoincrement=True)
    op.create_index(op.f('ix_memos_case_id'), 'memos', ['case_id'], unique=False)
    op.create_table('memo_versions',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('memo_id', sa.Integer(), nullable=False),
        sa.Column('version_no', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=12), nullable=False),
        sa.Column('created_by', sa.String(length=60), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('content', sa.JSON(), nullable=False),
        sa.Column('input_hash', sa.String(length=64), nullable=False),
        sa.Column('change_note', sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(['memo_id'], ['memos.id']),
        sa.PrimaryKeyConstraint('id'),
        sqlite_autoincrement=True)
    op.create_index(op.f('ix_memo_versions_memo_id'), 'memo_versions', ['memo_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_memo_versions_memo_id'), table_name='memo_versions')
    op.drop_table('memo_versions')
    op.drop_index(op.f('ix_memos_case_id'), table_name='memos')
    op.drop_table('memos')
