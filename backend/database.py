"""SQLAlchemy 数据库引擎与单次请求的会话管理。"""

from collections.abc import Generator
from uuid import uuid4

from fastapi import Request
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    """所有数据库模型都要继承的基础类。"""


class Database:
    """管理一个应用实例使用的数据库引擎和会话工厂。"""

    def __init__(self, database_url: str) -> None:
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

    def create_schema(self) -> None:
        """创建尚不存在的数据库表，并迁移 1.0 版故事内设定。"""
        Base.metadata.create_all(bind=self.engine)
        self._migrate_legacy_story_settings()

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
