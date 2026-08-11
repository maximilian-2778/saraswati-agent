"""Alembic 基线、旧库接管和往返迁移测试。"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from alembic import command
from sqlalchemy import inspect, select, text

from backend.database import Base, Database
from backend.migrations import alembic_config, current_revision, upgrade_database
from backend.models import ChatRecord


def test_empty_database_upgrades_to_head_and_matches_metadata(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path / "empty.db")
    try:
        assert upgrade_database(database) == "upgraded"
        assert current_revision(database) == "0008"
        assert "messages" in inspect(database.engine).get_table_names()
        assert "chat_skill_bindings" in inspect(database.engine).get_table_names()
        assert "world_evolutions" in inspect(database.engine).get_table_names()
        assert "setting_changes" in inspect(database.engine).get_table_names()
        command.check(alembic_config(database.database_url))

        assert upgrade_database(database) == "upgraded"
        assert current_revision(database) == "0008"
    finally:
        database.close()


def test_unversioned_database_is_completed_stamped_and_keeps_data(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path / "legacy.db")
    Base.metadata.create_all(database.engine)
    chat = ChatRecord(
        id="00000000-0000-0000-0000-000000000001",
        title="旧故事",
        system_prompt="保留这条数据。",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    with database.session_factory() as session:
        session.add(chat)
        session.commit()

    try:
        assert current_revision(database) is None
        assert upgrade_database(database) == "legacy_stamped"
        assert current_revision(database) == "0008"
        with database.session_factory() as session:
            restored = session.scalar(select(ChatRecord).where(ChatRecord.id == chat.id))
            assert restored is not None
            assert restored.title == "旧故事"
    finally:
        database.close()


def test_baseline_can_downgrade_and_upgrade_again(tmp_path: Path) -> None:
    database = _database(tmp_path / "roundtrip.db")
    config = alembic_config(database.database_url)
    try:
        command.upgrade(config, "head")
        assert current_revision(database) == "0008"

        command.downgrade(config, "base")
        assert current_revision(database) is None
        assert "messages" not in inspect(database.engine).get_table_names()

        command.upgrade(config, "head")
        assert current_revision(database) == "0008"
        assert "messages" in inspect(database.engine).get_table_names()
    finally:
        database.close()


def test_candidate_artifact_migration_backfills_existing_turn_data(tmp_path: Path) -> None:
    database = _database(tmp_path / "candidate-backfill.db")
    config = alembic_config(database.database_url)
    now = datetime.now(UTC)
    try:
        command.upgrade(config, "0006")
        with database.engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO chats (id, title, system_prompt, created_at, updated_at) "
                "VALUES ('chat', 'legacy', '', :now, :now)"
            ), {"now": now})
            connection.execute(text(
                "INSERT INTO messages (id, chat_id, role, content, created_at) VALUES "
                "('user', 'chat', 'user', 'go', :now), "
                "('assistant', 'chat', 'assistant', 'arrive', :later)"
            ), {"now": now, "later": now.replace(microsecond=min(now.microsecond + 1, 999999))})
            connection.execute(text(
                "INSERT INTO memories (id, chat_id, kind, content, importance, embedding_json, "
                "source_message_id, access_count, last_accessed_at, created_at) "
                "VALUES ('memory', 'chat', 'episodic', 'summary', 0.5, '[]', "
                "'assistant', 0, NULL, :now)"
            ), {"now": now})
            connection.execute(text(
                "INSERT INTO narrative_leaves (id, chat_id, user_message_id, assistant_message_id, "
                "memory_id, source_hash, content, detail_mode, time_start, time_end, created_at, updated_at) "
                "VALUES ('leaf', 'chat', 'user', 'assistant', 'memory', 'hash', 'summary', "
                "'brief', NULL, NULL, :now, :now)"
            ), {"now": now})
            connection.execute(text(
                "INSERT INTO narrative_deltas (id, chat_id, user_message_id, assistant_message_id, "
                "source_hash, payload_json, created_at, updated_at) VALUES "
                "('delta', 'chat', 'user', 'assistant', 'hash', '{}', :now, :now)"
            ), {"now": now})
            connection.execute(text(
                "INSERT INTO state_changes (id, chat_id, entity, key, old_value_json, new_value_json, "
                "reason, event_fingerprint, source_message_id, status, created_at, resolved_at) VALUES "
                "('state', 'chat', 'player', 'gold', NULL, '1', 'legacy', NULL, "
                "'user', 'approved', :now, :now)"
            ), {"now": now})
            connection.execute(text(
                "INSERT INTO roleplay_graph_events (id, chat_id, event_type, payload_json, "
                "source_message_id, source_hash, created_at) VALUES "
                "('graph', 'chat', 'scene_upsert', '{}', 'user', 'hash', :now)"
            ), {"now": now})
            connection.execute(text(
                "INSERT INTO timeline_anchors (id, chat_id, story_time, description, is_conflict, "
                "conflict_reason, source_message_id, created_at, updated_at) VALUES "
                "('time', 'chat', 'day one', 'legacy', 0, '', 'assistant', :now, :now)"
            ), {"now": now})

        command.upgrade(config, "head")
        with database.engine.connect() as connection:
            variant_id = connection.execute(text(
                "SELECT id FROM message_variants WHERE message_id = 'assistant' AND selected = 1"
            )).scalar_one()
            for table_name, row_id in (
                ("memories", "memory"), ("narrative_leaves", "leaf"),
                ("narrative_deltas", "delta"), ("state_changes", "state"),
                ("roleplay_graph_events", "graph"), ("timeline_anchors", "time"),
            ):
                stored = connection.execute(text(
                    f"SELECT variant_id FROM {table_name} WHERE id = :row_id"
                ), {"row_id": row_id}).scalar_one()
                assert stored == variant_id
    finally:
        database.close()


def _database(path: Path) -> Database:
    return Database(f"sqlite:///{path.as_posix()}")
