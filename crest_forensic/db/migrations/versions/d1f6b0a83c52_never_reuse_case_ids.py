"""never reuse ids of case-linked tables

SQLite hands out max(id)+1 for a plain integer key, so a deleted case's id comes back. AUTOINCREMENT remembers the
highest id ever used, so a deleted id stays retired. The tables are rebuilt in place; their rows are kept.

Revision ID: d1f6b0a83c52
Revises: c9a2e41d7b18
Create Date: 2026-10-07 20:00:00

"""
from typing import Sequence, Union

from alembic import op

revision: str = 'd1f6b0a83c52'
down_revision: Union[str, Sequence[str], None] = 'c9a2e41d7b18'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = ("cases", "case_events", "reviews", "escalations", "agent_sessions", "agent_messages")


def upgrade() -> None:
    for t in TABLES:
        with op.batch_alter_table(t, recreate="always", table_kwargs={"sqlite_autoincrement": True}):
            pass


def downgrade() -> None:
    for t in TABLES:
        with op.batch_alter_table(t, recreate="always"):
            pass
