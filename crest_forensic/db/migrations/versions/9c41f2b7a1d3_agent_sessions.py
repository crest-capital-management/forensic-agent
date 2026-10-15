"""agent chat sessions

Revision ID: 9c41f2b7a1d3
Revises: 7a0ec99da000
Create Date: 2026-10-07 14:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '9c41f2b7a1d3'
down_revision: Union[str, Sequence[str], None] = '7a0ec99da000'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('agent_sessions',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('case_id', sa.Integer(), nullable=False),
        sa.Column('created_by', sa.String(length=60), nullable=False),
        sa.Column('title', sa.String(length=120), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ),
        sa.PrimaryKeyConstraint('id'))
    op.create_index(op.f('ix_agent_sessions_case_id'), 'agent_sessions', ['case_id'], unique=False)
    with op.batch_alter_table('agent_messages') as batch:
        batch.add_column(sa.Column('session_id', sa.Integer(), nullable=True))
        batch.create_index(op.f('ix_agent_messages_session_id'), ['session_id'], unique=False)
        batch.create_foreign_key('fk_agent_messages_session', 'agent_sessions', ['session_id'], ['id'])

    # Old messages go into one chat per case and asker, so nothing is lost or left without a chat.
    bind = op.get_bind()
    groups = bind.execute(sa.text(
        "SELECT case_id, asked_by, MIN(id), MIN(created_at) FROM agent_messages GROUP BY case_id, asked_by")).fetchall()
    for case_id, asked_by, first_id, first_at in groups:
        first_q = bind.execute(sa.text("SELECT question FROM agent_messages WHERE id = :i"), {"i": first_id}).scalar() or "Earlier chat"
        bind.execute(sa.text("INSERT INTO agent_sessions (case_id, created_by, title, created_at) VALUES (:c, :u, :t, :a)"),
                     {"c": case_id, "u": asked_by, "t": first_q.strip().replace("\n", " ")[:60], "a": first_at})
        sid = bind.execute(sa.text("SELECT MAX(id) FROM agent_sessions")).scalar()
        bind.execute(sa.text("UPDATE agent_messages SET session_id = :s WHERE case_id = :c AND asked_by = :u"),
                     {"s": sid, "c": case_id, "u": asked_by})


def downgrade() -> None:
    with op.batch_alter_table('agent_messages') as batch:
        batch.drop_constraint('fk_agent_messages_session', type_='foreignkey')
        batch.drop_index(op.f('ix_agent_messages_session_id'))
        batch.drop_column('session_id')
    op.drop_index(op.f('ix_agent_sessions_case_id'), table_name='agent_sessions')
    op.drop_table('agent_sessions')
