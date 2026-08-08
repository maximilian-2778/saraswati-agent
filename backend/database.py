"""SQLAlchemy 数据库引擎与单次请求的会话管理。"""

from collections.abc import Generator

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
        """创建尚不存在的数据库表。"""
        Base.metadata.create_all(bind=self.engine)

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
