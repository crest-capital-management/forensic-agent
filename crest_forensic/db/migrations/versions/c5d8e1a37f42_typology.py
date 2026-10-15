"""Job 3: public_record_items and typology_matches

Revision ID: c5d8e1a37f42
Revises: b3f9d2a65e18
Create Date: 2026-10-14 20:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'c5d8e1a37f42'
down_revision: Union[str, Sequence[str], None] = 'b3f9d2a65e18'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'public_record_items',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('company_id', sa.Integer(), sa.ForeignKey('companies.company_id'), nullable=False),
        sa.Column('kind', sa.String(30), nullable=False),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('source_name', sa.String(120), nullable=False),
        sa.Column('url', sa.String(500), nullable=True),
        sa.Column('published_on', sa.String(10), nullable=True),
        sa.Column('summary', sa.Text(), nullable=False),
        sa.Column('tags', sa.JSON(), nullable=False),
        sa.Column('names_individual', sa.Boolean(), nullable=False),
        sa.Column('added_by', sa.String(60), nullable=False),
        sa.Column('added_at', sa.DateTime(timezone=True), nullable=False),
        sqlite_autoincrement=True,
    )
    op.create_index('ix_public_record_items_company_id', 'public_record_items', ['company_id'])
    op.create_table(
        'typology_matches',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('case_id', sa.Integer(), sa.ForeignKey('cases.id'), nullable=False),
        sa.Column('batch', sa.Integer(), nullable=False),
        sa.Column('scheme_id', sa.String(20), nullable=False),
        sa.Column('scheme_name', sa.String(200), nullable=False),
        sa.Column('class_label', sa.String(80), nullable=False),
        sa.Column('coverage', sa.Float(), nullable=False),
        sa.Column('present', sa.JSON(), nullable=False),
        sa.Column('missing', sa.JSON(), nullable=False),
        sa.Column('against', sa.JSON(), nullable=False),
        sa.Column('innocent_explanations', sa.JSON(), nullable=False),
        sa.Column('evidence_to_confirm', sa.JSON(), nullable=False),
        sa.Column('citations', sa.JSON(), nullable=False),
        sa.Column('named_individual', sa.Boolean(), nullable=False),
        sa.Column('input_hash', sa.String(64), nullable=False),
        sa.Column('created_by', sa.String(60), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('review_status', sa.String(12), nullable=False),
        sa.Column('reviewed_by', sa.String(60), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('review_note', sa.Text(), nullable=True),
        sa.Column('partner_status', sa.String(12), nullable=False),
        sa.Column('partner_by', sa.String(60), nullable=True),
        sa.Column('partner_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('partner_note', sa.Text(), nullable=True),
        sqlite_autoincrement=True,
    )
    op.create_index('ix_typology_matches_case_id', 'typology_matches', ['case_id'])
    op.create_index('ix_typology_matches_batch', 'typology_matches', ['batch'])


def downgrade() -> None:
    op.drop_table('typology_matches')
    op.drop_table('public_record_items')
