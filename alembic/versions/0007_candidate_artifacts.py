"""Bind derived story artifacts to message variants.

Revision ID: 0007
Revises: 0006
"""

import json
from uuid import uuid4

from alembic import op
import sqlalchemy as sa


revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    metadata = sa.MetaData()
    metadata.reflect(bind=bind)
    messages = metadata.tables["messages"]
    variants = metadata.tables["message_variants"]

    existing = set(bind.execute(sa.select(variants.c.message_id)).scalars())
    assistants = bind.execute(sa.select(
        messages.c.id, messages.c.chat_id, messages.c.content, messages.c.created_at
    ).where(messages.c.role == "assistant")).all()
    for message in assistants:
        if message.id in existing:
            continue
        bind.execute(variants.insert().values(
            id=str(uuid4()), chat_id=message.chat_id, message_id=message.id,
            position=0, content=message.content, state_changes_json="[]",
            graph_events_json="[]", selected=True, created_at=message.created_at,
        ))

    nullable_tables = (
        "memories", "roleplay_graph_events", "world_evolutions",
        "timeline_anchors", "state_changes",
    )
    for table_name in nullable_tables:
        with op.batch_alter_table(table_name) as batch:
            batch.add_column(sa.Column("variant_id", sa.String(length=36), nullable=True))
            batch.create_index(f"ix_{table_name}_variant_id", ["variant_id"], unique=False)
            batch.create_foreign_key(
                f"fk_{table_name}_variant_id_message_variants",
                "message_variants", ["variant_id"], ["id"], ondelete="CASCADE",
            )

    with op.batch_alter_table("memories") as batch:
        batch.add_column(sa.Column(
            "variant_ids_json", sa.Text(), nullable=False, server_default="[]"
        ))

    with op.batch_alter_table("narrative_leaves") as batch:
        batch.add_column(sa.Column("variant_id", sa.String(length=36), nullable=True))
        batch.create_index("ix_narrative_leaves_variant_id", ["variant_id"], unique=False)
        batch.create_foreign_key(
            "fk_narrative_leaves_variant_id_message_variants",
            "message_variants", ["variant_id"], ["id"], ondelete="CASCADE",
        )
        batch.drop_constraint("uq_narrative_leaf_message", type_="unique")

    with op.batch_alter_table("narrative_deltas") as batch:
        batch.add_column(sa.Column("variant_id", sa.String(length=36), nullable=True))
        batch.create_index("ix_narrative_deltas_variant_id", ["variant_id"], unique=False)
        batch.create_foreign_key(
            "fk_narrative_deltas_variant_id_message_variants",
            "message_variants", ["variant_id"], ["id"], ondelete="CASCADE",
        )
        batch.drop_constraint("uq_delta_assistant_message", type_="unique")

    with op.batch_alter_table("narrative_summary_nodes") as batch:
        batch.add_column(sa.Column(
            "variant_ids_json", sa.Text(), nullable=False, server_default="[]"
        ))

    metadata = sa.MetaData()
    metadata.reflect(bind=bind)
    variants = metadata.tables["message_variants"]
    selected_by_message = dict(bind.execute(sa.select(
        variants.c.message_id, variants.c.id
    ).where(variants.c.selected.is_(True))).all())
    source_to_variant = dict(selected_by_message)
    ordered_messages = bind.execute(sa.select(
        messages.c.id, messages.c.chat_id, messages.c.role, messages.c.created_at
    ).order_by(messages.c.chat_id, messages.c.created_at)).all()
    latest_user: dict[str, str] = {}
    for message in ordered_messages:
        if message.role == "user":
            latest_user[message.chat_id] = message.id
            continue
        if message.role != "assistant":
            continue
        variant_id = selected_by_message.get(message.id)
        if variant_id and latest_user.get(message.chat_id):
            source_to_variant[latest_user[message.chat_id]] = variant_id

    for table_name in ("narrative_leaves", "narrative_deltas"):
        table = metadata.tables[table_name]
        rows = bind.execute(sa.select(table.c.id, table.c.assistant_message_id)).all()
        for row in rows:
            bind.execute(table.update().where(table.c.id == row.id).values(
                variant_id=selected_by_message[row.assistant_message_id]
            ))

    memories = metadata.tables["memories"]
    leaves = metadata.tables["narrative_leaves"]
    leaf_variants: dict[str, set[str]] = {}
    for row in bind.execute(sa.select(
        leaves.c.id, leaves.c.memory_id, leaves.c.variant_id
    )).all():
        leaf_variants[row.id] = {row.variant_id}
        if row.memory_id:
            bind.execute(memories.update().where(memories.c.id == row.memory_id).values(
                variant_id=row.variant_id,
                variant_ids_json=json.dumps([row.variant_id]),
            ))

    nodes = metadata.tables["narrative_summary_nodes"]
    pending = list(bind.execute(sa.select(
        nodes.c.id, nodes.c.child_refs_json, nodes.c.memory_id
    ).order_by(nodes.c.level)).all())
    node_variants: dict[str, set[str]] = {}
    for row in pending:
        scope: set[str] = set()
        for child_id in json.loads(row.child_refs_json or "[]"):
            scope.update(leaf_variants.get(child_id, node_variants.get(child_id, set())))
        node_variants[row.id] = scope
        encoded = json.dumps(sorted(scope))
        bind.execute(nodes.update().where(nodes.c.id == row.id).values(
            variant_ids_json=encoded
        ))
        if row.memory_id:
            bind.execute(memories.update().where(memories.c.id == row.memory_id).values(
                variant_ids_json=encoded
            ))

    for table_name in (
        "memories", "timeline_anchors", "roleplay_graph_events", "state_changes"
    ):
        table = metadata.tables[table_name]
        rows = bind.execute(sa.select(table.c.id, table.c.source_message_id)).all()
        for row in rows:
            variant_id = source_to_variant.get(row.source_message_id)
            if variant_id:
                values = {"variant_id": variant_id}
                if table_name == "memories":
                    values["variant_ids_json"] = json.dumps([variant_id])
                bind.execute(table.update().where(table.c.id == row.id).values(**values))

    world = metadata.tables["world_evolutions"]
    for row in bind.execute(sa.select(world.c.id, world.c.assistant_message_id)).all():
        variant_id = selected_by_message.get(row.assistant_message_id)
        if variant_id:
            bind.execute(world.update().where(world.c.id == row.id).values(variant_id=variant_id))

    with op.batch_alter_table("narrative_leaves") as batch:
        batch.alter_column("variant_id", existing_type=sa.String(length=36), nullable=False)
        batch.create_unique_constraint(
            "uq_narrative_leaf_variant", ["assistant_message_id", "variant_id"]
        )
    with op.batch_alter_table("narrative_deltas") as batch:
        batch.alter_column("variant_id", existing_type=sa.String(length=36), nullable=False)
        batch.create_unique_constraint(
            "uq_delta_variant", ["assistant_message_id", "variant_id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("narrative_deltas") as batch:
        batch.drop_constraint("uq_delta_variant", type_="unique")
        batch.drop_index("ix_narrative_deltas_variant_id")
        batch.drop_constraint("fk_narrative_deltas_variant_id_message_variants", type_="foreignkey")
        batch.drop_column("variant_id")
        batch.create_unique_constraint("uq_delta_assistant_message", ["assistant_message_id"])
    with op.batch_alter_table("narrative_leaves") as batch:
        batch.drop_constraint("uq_narrative_leaf_variant", type_="unique")
        batch.drop_index("ix_narrative_leaves_variant_id")
        batch.drop_constraint("fk_narrative_leaves_variant_id_message_variants", type_="foreignkey")
        batch.drop_column("variant_id")
        batch.create_unique_constraint("uq_narrative_leaf_message", ["assistant_message_id"])
    with op.batch_alter_table("narrative_summary_nodes") as batch:
        batch.drop_column("variant_ids_json")
    with op.batch_alter_table("memories") as batch:
        batch.drop_column("variant_ids_json")
    for table_name in reversed((
        "memories", "roleplay_graph_events", "world_evolutions",
        "timeline_anchors", "state_changes",
    )):
        with op.batch_alter_table(table_name) as batch:
            batch.drop_index(f"ix_{table_name}_variant_id")
            batch.drop_constraint(
                f"fk_{table_name}_variant_id_message_variants", type_="foreignkey"
            )
            batch.drop_column("variant_id")
