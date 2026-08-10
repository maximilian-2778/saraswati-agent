"""add story-level skill bindings

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-10
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chat_skill_modes",
        sa.Column("chat_id", sa.String(length=36), nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["chat_id"], ["chats.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("chat_id"),
    )
    op.create_table(
        "chat_skill_bindings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("chat_id", sa.String(length=36), nullable=False),
        sa.Column("skill_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["chat_id"], ["chats.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("chat_id", "skill_id", name="uq_chat_skill_binding"),
    )
    op.create_index("ix_chat_skill_bindings_chat_id", "chat_skill_bindings", ["chat_id"])


def downgrade() -> None:
    op.drop_index("ix_chat_skill_bindings_chat_id", table_name="chat_skill_bindings")
    op.drop_table("chat_skill_bindings")
    op.drop_table("chat_skill_modes")
