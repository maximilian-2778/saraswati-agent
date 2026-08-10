"""Preserve third-party character-card and lorebook metadata.

Revision ID: 0005
Revises: 0004
"""

from alembic import op
import sqlalchemy as sa


revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


TABLES = (
    "character_templates",
    "story_characters",
    "world_book_templates",
    "story_world_books",
)


def upgrade() -> None:
    for table in TABLES:
        op.add_column(
            table,
            sa.Column("compatibility_data_json", sa.Text(), nullable=False, server_default="{}"),
        )


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_column(table, "compatibility_data_json")
