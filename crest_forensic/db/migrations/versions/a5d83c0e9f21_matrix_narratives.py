"""matrix narratives

Revision ID: a5d83c0e9f21
Revises: 9c41f2b7a1d3
Create Date: 2026-10-07 16:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'a5d83c0e9f21'
down_revision: Union[str, Sequence[str], None] = '9c41f2b7a1d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('matrix_narratives',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=False),
        sa.Column('basis', sa.String(length=15), nullable=False),
        sa.Column('years', sa.JSON(), nullable=False),
        sa.Column('facts_hash', sa.String(length=16), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=10), nullable=False),
        sa.Column('model', sa.String(length=80), nullable=True),
        sa.Column('warnings', sa.JSON(), nullable=False),
        sa.Column('sources', sa.JSON(), nullable=False),
        sa.Column('input_tokens', sa.Integer(), nullable=True),
        sa.Column('output_tokens', sa.Integer(), nullable=True),
        sa.Column('model_calls', sa.Integer(), nullable=False),
        sa.Column('created_by', sa.String(length=60), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.company_id'], ),
        sa.PrimaryKeyConstraint('id'))
    op.create_index(op.f('ix_matrix_narratives_company_id'), 'matrix_narratives', ['company_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_matrix_narratives_company_id'), table_name='matrix_narratives')
    op.drop_table('matrix_narratives')
