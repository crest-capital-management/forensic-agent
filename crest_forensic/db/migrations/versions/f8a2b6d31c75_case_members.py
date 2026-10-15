"""case_members: per-case access (existing cases get their creator as a member)

Revision ID: f8a2b6d31c75
Revises: e7f3a1c95d64
Create Date: 2026-10-15 15:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'f8a2b6d31c75'
down_revision: Union[str, Sequence[str], None] = 'e7f3a1c95d64'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'case_members',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('case_id', sa.Integer(), sa.ForeignKey('cases.id'), nullable=False),
        sa.Column('username', sa.String(60), nullable=False),
        sa.Column('added_by', sa.String(60), nullable=False),
        sa.Column('added_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('removed_by', sa.String(60), nullable=True),
        sa.Column('removed_at', sa.DateTime(timezone=True), nullable=True),
        sqlite_autoincrement=True,
    )
    op.create_index('ix_case_members_case_id', 'case_members', ['case_id'])
    op.create_index('ix_case_members_username', 'case_members', ['username'])
    # every case that exists keeps its creator (and everyone who has a memo on it, or a review or chat there) so nobody loses access they used
    op.execute("INSERT INTO case_members (case_id, username, added_by, added_at) "
               "SELECT id, created_by, created_by, created_at FROM cases")
    op.execute("INSERT INTO case_members (case_id, username, added_by, added_at) "
               "SELECT m.case_id, m.owner, m.created_by, m.created_at FROM memos m "
               "WHERE NOT EXISTS (SELECT 1 FROM case_members x WHERE x.case_id = m.case_id AND x.username = m.owner)")
    op.execute("INSERT INTO case_members (case_id, username, added_by, added_at) "
               "SELECT r.case_id, r.reviewer, r.reviewer, MIN(r.decided_at) FROM reviews r "
               "WHERE NOT EXISTS (SELECT 1 FROM case_members x WHERE x.case_id = r.case_id AND x.username = r.reviewer) "
               "GROUP BY r.case_id, r.reviewer")


def downgrade() -> None:
    op.drop_table('case_members')
