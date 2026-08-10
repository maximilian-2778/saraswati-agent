"""Alembic 基线、旧库接管和往返迁移测试。"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from alembic import command
from sqlalchemy import inspect, select

from backend.database import Base, Database
from backend.migrations import alembic_config, current_revision, upgrade_database
from backend.models import ChatRecord


def test_empty_database_upgrades_to_head_and_matches_metadata(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path / "empty.db")
    try:
        assert upgrade_database(database) == "upgraded"
        assert current_revision(database) == "0004"
        assert "messages" in inspect(database.engine).get_table_names()
        assert "chat_skill_bindings" in inspect(database.engine).get_table_names()
        assert "world_evolutions" in inspect(database.engine).get_table_names()
        command.check(alembic_config(database.database_url))

        assert upgrade_database(database) == "upgraded"
        assert current_revision(database) == "0004"
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
        assert current_revision(database) == "0004"
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
        assert current_revision(database) == "0004"

        command.downgrade(config, "base")
        assert current_revision(database) is None
        assert "messages" not in inspect(database.engine).get_table_names()

        command.upgrade(config, "head")
        assert current_revision(database) == "0004"
        assert "messages" in inspect(database.engine).get_table_names()
    finally:
        database.close()


def _database(path: Path) -> Database:
    return Database(f"sqlite:///{path.as_posix()}")
