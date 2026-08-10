"""Narrative integrity: timeline conflicts, scene aliases and item idempotency.

Revision ID: 0006
Revises: 0005
"""

from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("scene_nodes") as batch:
        batch.add_column(sa.Column("aliases_json", sa.Text(), nullable=False, server_default="[]"))
    with op.batch_alter_table("timeline_anchors") as batch:
        batch.add_column(sa.Column("is_conflict", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("conflict_reason", sa.Text(), nullable=False, server_default=""))
    with op.batch_alter_table("state_changes") as batch:
        batch.add_column(sa.Column("event_fingerprint", sa.String(length=64), nullable=True))
        batch.create_index("ix_state_changes_event_fingerprint", ["event_fingerprint"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("state_changes") as batch:
        batch.drop_index("ix_state_changes_event_fingerprint")
        batch.drop_column("event_fingerprint")
    with op.batch_alter_table("timeline_anchors") as batch:
        batch.drop_column("conflict_reason")
        batch.drop_column("is_conflict")
    with op.batch_alter_table("scene_nodes") as batch:
        batch.drop_column("aliases_json")
