"""peer_links: the peer set for Job 2 peer comparisons

Revision ID: e7f3a1c95d64
Revises: d6e9f2b48a53
Create Date: 2026-10-15 12:30:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'e7f3a1c95d64'
down_revision: Union[str, Sequence[str], None] = 'd6e9f2b48a53'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'peer_links',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('company_id', sa.Integer(), sa.ForeignKey('companies.company_id'), nullable=False),
        sa.Column('peer_company_id', sa.Integer(), sa.ForeignKey('companies.company_id'), nullable=False),
        sa.Column('approved_by', sa.String(120), nullable=False),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        sa.UniqueConstraint('company_id', 'peer_company_id', name='uq_peer_link'),
        sqlite_autoincrement=True,
    )
    op.create_index('ix_peer_links_company_id', 'peer_links', ['company_id'])
    op.create_index('ix_peer_links_peer_company_id', 'peer_links', ['peer_company_id'])


def downgrade() -> None:
    op.drop_table('peer_links')
