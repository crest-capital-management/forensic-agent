"""user methodology

Revision ID: b7c19d4e2a50
Revises: a5d83c0e9f21
Create Date: 2026-10-07 18:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'b7c19d4e2a50'
down_revision: Union[str, Sequence[str], None] = 'a5d83c0e9f21'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('user_methodologies',
        sa.Column('username', sa.String(length=60), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('username'))
    with op.batch_alter_table('matrix_narratives') as batch:
        batch.add_column(sa.Column('methodology', sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('matrix_narratives') as batch:
        batch.drop_column('methodology')
    op.drop_table('user_methodologies')
