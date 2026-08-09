"""SQLAlchemy 数据库引擎与单次请求的会话管理。"""

from collections.abc import Generator
from uuid import uuid4

from fastapi import Request
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    """所有数据库模型都要继承的基础类。"""


class Database:
    """管理一个应用实例使用的数据库引擎和会话工厂。"""

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        connect_args = (
            {"check_same_thread": False}
            if database_url.startswith("sqlite")
            else {}
        )
        self.engine = create_engine(database_url, connect_args=connect_args)
        self.session_factory = sessionmaker(
            bind=self.engine,
            autoflush=False,
            expire_on_commit=False,
        )

        if database_url.startswith("sqlite"):
            event.listen(self.engine, "connect", _enable_sqlite_foreign_keys)

    def prepare_legacy_schema(self) -> None:
        """把没有 Alembic 版本号的旧数据库补齐到 0.9 基线结构。"""
        Base.metadata.create_all(bind=self.engine)
        self._migrate_avatar_columns()
        self._migrate_roleplay_profile_columns()
        self._migrate_message_variant_columns()
        self._migrate_legacy_story_settings()

    def _migrate_avatar_columns(self) -> None:
        """为旧数据库补充角色头像字段。"""
        tables = ("character_templates", "story_characters", "character_profiles")
        with self.engine.begin() as connection:
            inspector = inspect(connection)
            for table in tables:
                columns = {column["name"] for column in inspector.get_columns(table)}
                if "avatar" not in columns:
                    connection.execute(
                        text(f"ALTER TABLE {table} ADD COLUMN avatar TEXT NOT NULL DEFAULT ''")
                    )

    def _migrate_message_variant_columns(self) -> None:
        """为早期 0.7 开发数据库补充候选回复的状态快照。"""
        with self.engine.begin() as connection:
            inspector = inspect(connection)
            columns = {
                column["name"]
                for column in inspector.get_columns("message_variants")
            }
            for name in ("state_changes_json", "graph_events_json"):
                if name not in columns:
                    connection.execute(
                        text(
                            f"ALTER TABLE message_variants ADD COLUMN {name} "
                            "TEXT NOT NULL DEFAULT '[]'"
                        )
                    )

    def _migrate_roleplay_profile_columns(self) -> None:
        """为旧数据库补充角色卡和世界书高级字段。"""
        character_columns = {
            "appearance": "TEXT NOT NULL DEFAULT ''",
            "first_message": "TEXT NOT NULL DEFAULT ''",
            "alternate_greetings_json": "TEXT NOT NULL DEFAULT '[]'",
            "example_dialogue": "TEXT NOT NULL DEFAULT ''",
            "tags_json": "TEXT NOT NULL DEFAULT '[]'",
            "creator_notes": "TEXT NOT NULL DEFAULT ''",
            "system_prompt": "TEXT NOT NULL DEFAULT ''",
            "favorite": "BOOLEAN NOT NULL DEFAULT 0",
            "world_book_ids_json": "TEXT NOT NULL DEFAULT '[]'",
        }
        world_columns = {
            "secondary_keywords_json": "TEXT NOT NULL DEFAULT '[]'",
            "constant": "BOOLEAN NOT NULL DEFAULT 0",
            "case_sensitive": "BOOLEAN NOT NULL DEFAULT 0",
            "scan_depth": "INTEGER NOT NULL DEFAULT 4",
            "insertion_position": "VARCHAR(30) NOT NULL DEFAULT 'before_history'",
            "group_name": "VARCHAR(100) NOT NULL DEFAULT ''",
            "recursive": "BOOLEAN NOT NULL DEFAULT 0",
            "token_budget": "INTEGER NOT NULL DEFAULT 2048",
            "scope": "VARCHAR(30) NOT NULL DEFAULT 'global'",
        }
        with self.engine.begin() as connection:
            inspector = inspect(connection)
            for table in ("character_templates", "story_characters"):
                existing = {item["name"] for item in inspector.get_columns(table)}
                for name, definition in character_columns.items():
                    if name not in existing:
                        connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {definition}"))
            for table in ("world_book_templates", "story_world_books", "world_book_entries"):
                existing = {item["name"] for item in inspector.get_columns(table)}
                for name, definition in world_columns.items():
                    if name not in existing:
                        connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {definition}"))

    def _migrate_legacy_story_settings(self) -> None:
        """把旧版单角色/世界书数据复制到新的故事快照表，原表保留作兼容。"""
        from sqlalchemy import select

        from backend.models import (
            CharacterProfileRecord,
            StoryCharacterRecord,
            StoryWorldBookRecord,
            WorldBookEntryRecord,
        )

        with self.session_factory() as db:
            legacy_characters = db.scalars(select(CharacterProfileRecord)).all()
            for legacy in legacy_characters:
                exists = db.scalar(
                    select(StoryCharacterRecord.id).where(
                        StoryCharacterRecord.chat_id == legacy.chat_id
                    )
                )
                if not exists and legacy.name.strip():
                    db.add(
                        StoryCharacterRecord(
                            id=str(uuid4()),
                            chat_id=legacy.chat_id,
                            source_template_id=None,
                            name=legacy.name,
                            identity=legacy.identity,
                            personality=legacy.personality,
                            speaking_style=legacy.speaking_style,
                            scenario=legacy.scenario,
                            avatar=legacy.avatar,
                            created_at=legacy.updated_at,
                            updated_at=legacy.updated_at,
                        )
                    )

            legacy_world_entries = db.scalars(select(WorldBookEntryRecord)).all()
            migrated_world_chats = set(
                db.scalars(select(StoryWorldBookRecord.chat_id).distinct()).all()
            )
            for legacy in legacy_world_entries:
                if legacy.chat_id not in migrated_world_chats:
                    db.add(
                        StoryWorldBookRecord(
                            id=str(uuid4()),
                            chat_id=legacy.chat_id,
                            source_template_id=None,
                            title=legacy.title,
                            keywords_json=legacy.keywords_json,
                            content=legacy.content,
                            priority=legacy.priority,
                            enabled=legacy.enabled,
                            created_at=legacy.created_at,
                            updated_at=legacy.updated_at,
                        )
                    )
            db.commit()

    def close(self) -> None:
        """释放数据库连接池中的连接。"""
        self.engine.dispose()


def _enable_sqlite_foreign_keys(
    dbapi_connection: object,
    _connection_record: object,
) -> None:
    """为每一个新的 SQLite 连接启用外键约束。"""
    cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def get_db(request: Request) -> Generator[Session, None, None]:
    """为当前 HTTP 请求提供一个 SQLAlchemy 会话。"""
    database: Database = request.app.state.database
    db = database.session_factory()
    try:
        yield db
    finally:
        db.close()
