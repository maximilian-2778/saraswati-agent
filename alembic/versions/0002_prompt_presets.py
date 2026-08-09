"""add prompt presets

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-09
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "prompt_presets",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("temperature", sa.Float(), nullable=False),
        sa.Column("top_p", sa.Float(), nullable=False),
        sa.Column("max_output_tokens", sa.Integer(), nullable=False),
        sa.Column("presence_penalty", sa.Float(), nullable=False),
        sa.Column("frequency_penalty", sa.Float(), nullable=False),
        sa.Column("context_window_tokens", sa.Integer(), nullable=False),
        sa.Column("prompts_json", sa.Text(), nullable=False),
        sa.Column("extra_settings_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )


def downgrade() -> None:
    op.drop_table("prompt_presets")
