"""add native world evolution state

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-10
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "world_engine_configs",
        sa.Column("chat_id", sa.String(length=36), nullable=False),
        sa.Column("auto_evolve", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["chat_id"], ["chats.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("chat_id"),
    )
    op.create_table(
        "world_evolutions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("chat_id", sa.String(length=36), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("user_message_id", sa.String(length=36), nullable=True),
        sa.Column("assistant_message_id", sa.String(length=36), nullable=True),
        sa.Column("source_hash", sa.String(length=64), nullable=True),
        sa.Column("before_hash", sa.String(length=64), nullable=False),
        sa.Column("after_state_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["assistant_message_id"], ["messages.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["chat_id"], ["chats.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_message_id"], ["messages.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("chat_id", "sequence", name="uq_world_evolution_sequence"),
    )
    op.create_index("ix_world_evolutions_chat_id", "world_evolutions", ["chat_id"])
    op.create_index("ix_world_evolutions_user_message_id", "world_evolutions", ["user_message_id"])
    op.create_index("ix_world_evolutions_assistant_message_id", "world_evolutions", ["assistant_message_id"])


def downgrade() -> None:
    op.drop_index("ix_world_evolutions_assistant_message_id", table_name="world_evolutions")
    op.drop_index("ix_world_evolutions_user_message_id", table_name="world_evolutions")
    op.drop_index("ix_world_evolutions_chat_id", table_name="world_evolutions")
    op.drop_table("world_evolutions")
    op.drop_table("world_engine_configs")
