"""Add variant-scoped story setting evolution events.

Revision ID: 0008
Revises: 0007
"""

from alembic import op
import sqlalchemy as sa


revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "setting_changes",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("chat_id", sa.String(length=36), nullable=False),
        sa.Column("target_type", sa.String(length=20), nullable=False),
        sa.Column("target_id", sa.String(length=36), nullable=False),
        sa.Column("field", sa.String(length=40), nullable=False),
        sa.Column("base_value", sa.Text(), nullable=False),
        sa.Column("new_value", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False, server_default=""),
        sa.Column("importance", sa.String(length=20), nullable=False, server_default="major"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("source_message_id", sa.String(length=36), nullable=True),
        sa.Column("variant_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["chat_id"], ["chats.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_message_id"], ["messages.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["variant_id"], ["message_variants.id"], ondelete="CASCADE"),
    )
    for column in ("chat_id", "target_type", "target_id", "source_message_id", "variant_id", "status"):
        op.create_index(f"ix_setting_changes_{column}", "setting_changes", [column], unique=False)


def downgrade() -> None:
    op.drop_table("setting_changes")
