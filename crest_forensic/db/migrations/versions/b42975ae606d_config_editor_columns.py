"""config editor columns

Revision ID: b42975ae606d
Revises: 10cc94d6ed68
Create Date: 2026-10-05 14:12:56.604780

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b42975ae606d'
down_revision: Union[str, Sequence[str], None] = '10cc94d6ed68'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # batch mode so SQLite can add the foreign key; existing rows become origin "file"
    with op.batch_alter_table('config_versions') as batch:
        batch.add_column(sa.Column('origin', sa.String(length=10), nullable=False, server_default='file'))
        batch.add_column(sa.Column('created_by', sa.String(length=60), nullable=True))
        batch.add_column(sa.Column('note', sa.Text(), nullable=True))
        batch.add_column(sa.Column('parent_id', sa.Integer(), nullable=True))
        batch.create_foreign_key('fk_config_versions_parent', 'config_versions', ['parent_id'], ['id'])


def downgrade() -> None:
    with op.batch_alter_table('config_versions') as batch:
        batch.drop_constraint('fk_config_versions_parent', type_='foreignkey')
        batch.drop_column('parent_id')
        batch.drop_column('note')
        batch.drop_column('created_by')
        batch.drop_column('origin')
